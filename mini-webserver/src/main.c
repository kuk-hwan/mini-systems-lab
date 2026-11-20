#include "web.h"
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static volatile sig_atomic_t stop_requested;
static int signal_pipe[2] = {-1, -1};

static void on_signal(int signal_number) {
    (void)signal_number;
    int saved = errno;
    stop_requested = 1;
    unsigned char byte = 1;
    if (signal_pipe[1] >= 0) { ssize_t ignored = write(signal_pipe[1], &byte, 1); (void)ignored; }
    errno = saved;
}

int main(int argc, char **argv) {
    config_t *cfg = calloc(1, sizeof(*cfg));
    if (!cfg) return 1;
    int result = config_init(cfg, argc, argv);
    if (result) { free(cfg); return result > 0 ? 0 : 1; }
    int listener = net_listen(cfg);
    if (listener < 0) { perror("socket/bind/listen"); config_destroy(cfg); free(cfg); return 1; }
    if (pipe(signal_pipe) < 0 || nonblocking(signal_pipe[0]) < 0 || nonblocking(signal_pipe[1]) < 0) {
        perror("signal pipe");
        if (signal_pipe[0] >= 0) close(signal_pipe[0]);
        if (signal_pipe[1] >= 0) close(signal_pipe[1]);
        close(listener); config_destroy(cfg); free(cfg); return 1;
    }
    struct sigaction action = {0}; sigemptyset(&action.sa_mask); action.sa_handler = SIG_IGN;
    sigaction(SIGPIPE, &action, NULL);
    action.sa_handler = on_signal;
    sigaction(SIGINT, &action, NULL); sigaction(SIGTERM, &action, NULL);
    /* Only the listener handles termination signals; workers inherit the blocked set. */
    sigset_t signals; sigemptyset(&signals); sigaddset(&signals, SIGINT); sigaddset(&signals, SIGTERM);
    pthread_sigmask(SIG_BLOCK, &signals, NULL);
    pool_t pool;
    if (pool_init(&pool, cfg) < 0) {
        fprintf(stderr, "thread pool initialization failed\n");
        close(listener); close(signal_pipe[0]); close(signal_pipe[1]); config_destroy(cfg); free(cfg); return 1;
    }
    pthread_sigmask(SIG_UNBLOCK, &signals, NULL);
    fprintf(stderr, "READY http://%s:%s workers=%d routes=%zu root=%s\n",
            cfg->host, cfg->port, cfg->workers, cfg->route_count, cfg->root);
    struct pollfd fds[2] = {{.fd = listener, .events = POLLIN}, {.fd = signal_pipe[0], .events = POLLIN}};
    while (!stop_requested) {
        int ready = poll(fds, 2, -1);
        if (ready < 0) { if (errno == EINTR) continue; perror("listener poll"); result = 1; break; }
        if (fds[1].revents || stop_requested) break;
        if (fds[0].revents & POLLIN) {
            for (;;) {
                int fd = accept(listener, NULL, NULL);
                if (fd < 0) {
                    if (errno == EINTR) continue;
                    if (errno != EAGAIN && errno != EWOULDBLOCK) perror("accept");
                    break;
                }
                if (tcp_prepare(fd) < 0) { close(fd); continue; }
                if (!pool_submit(&pool, fd)) {
                    /* Never block the accept loop on an overloaded peer. */
                    const char busy[] = "HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n";
                    ssize_t ignored = send(fd, busy, sizeof(busy) - 1, 0); (void)ignored;
                    connection_close(fd);
                }
                if (stop_requested) break;
            }
        }
    }
    close(listener);
    pool_stop(&pool);
    /* Block handlers before closing their pipe to avoid writing to a reused FD. */
    pthread_sigmask(SIG_BLOCK, &signals, NULL);
    close(signal_pipe[0]); close(signal_pipe[1]);
    config_destroy(cfg); free(cfg);
    fprintf(stderr, "STOPPED workers joined; queued connections and resources released\n");
    return result;
}
