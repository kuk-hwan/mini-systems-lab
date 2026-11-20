#include "web.h"
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

int64_t now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

int nonblocking(int fd) {
    int flags = fcntl(fd, F_GETFL);
    if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) return -1;
    return fcntl(fd, F_SETFD, FD_CLOEXEC);
}

int tcp_prepare(int fd) {
    int on = 1;
    if (nonblocking(fd) < 0) return -1;
    return setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &on, sizeof(on));
}

/* One absolute deadline prevents a slow peer from resetting the timer per byte. */
int wait_fd(int fd, short events, int64_t deadline) {
    for (;;) {
        int64_t left = deadline - now_ms();
        if (left <= 0) { errno = ETIMEDOUT; return -1; }
        struct pollfd p = {.fd = fd, .events = events};
        int rc = poll(&p, 1, (int)left);
        if (rc > 0) {
            if (p.revents & POLLNVAL) { errno = EBADF; return -1; }
            return 0; /* recv/send/getsockopt diagnoses HUP and ERR. */
        }
        if (rc == 0) { errno = ETIMEDOUT; return -1; }
        if (errno != EINTR) return -1;
    }
}

int send_all(int fd, const void *data, size_t len, int64_t deadline) {
    const unsigned char *p = data;
    while (len) {
        if (now_ms() >= deadline) { errno = ETIMEDOUT; return -1; }
        ssize_t n = send(fd, p, len, 0);
        if (n > 0) { p += n; len -= (size_t)n; continue; }
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            if (wait_fd(fd, POLLOUT, deadline) == 0) continue;
        }
        return -1;
    }
    return 0;
}

void connection_close(int fd) {
    /* Send FIN after the response and discard already-arrived input. Bound the
     * work: a client must not hold a worker by continuously sending junk. */
    shutdown(fd, SHUT_WR);
    unsigned char discard[4096];
    for (int i = 0; i < 16; i++)
        if (recv(fd, discard, sizeof(discard), 0) <= 0) break;
    close(fd);
}

void stream_init(stream_t *s, int fd, int64_t deadline) {
    memset(s, 0, sizeof(*s)); s->fd = fd; s->deadline = deadline;
}

int stream_some(stream_t *s, void *out, size_t cap) {
    if (s->start < s->end) {
        size_t n = s->end - s->start;
        if (n > cap) n = cap;
        memcpy(out, s->buf + s->start, n); s->start += n;
        return (int)n;
    }
    for (;;) {
        if (now_ms() >= s->deadline) { errno = ETIMEDOUT; return -1; }
        ssize_t n = recv(s->fd, out, cap, 0);
        if (n >= 0) return (int)n;
        if (errno == EINTR) continue;
        if (errno != EAGAIN && errno != EWOULDBLOCK) return -1;
        if (wait_fd(s->fd, POLLIN, s->deadline) < 0) return -1;
    }
}

static int stream_byte(stream_t *s, unsigned char *out) {
    if (s->start == s->end) {
        s->start = s->end = 0;
        int n = stream_some(s, s->buf, sizeof(s->buf));
        if (n <= 0) return n;
        s->end = (size_t)n;
    }
    *out = s->buf[s->start++]; return 1;
}

/* Return bytes including CRLF, 0 for clean EOF, -2 for an oversized line. */
int stream_line(stream_t *s, char *out, size_t cap) {
    size_t used = 0;
    while (used + 1 < cap) {
        unsigned char ch;
        int n = stream_byte(s, &ch);
        if (n <= 0) {
            if (n == 0 && used) { errno = EPROTO; return -1; }
            return n;
        }
        if (ch == 0) { errno = EPROTO; return -1; }
        out[used++] = (char)ch;
        if (ch == '\n') {
            if (used < 2 || out[used - 2] != '\r') { errno = EPROTO; return -1; }
            out[used] = 0; return (int)used;
        }
    }
    return -2;
}

int stream_exact(stream_t *s, void *out, size_t len) {
    unsigned char *p = out;
    while (len) {
        int n = stream_some(s, p, len);
        if (n <= 0) { if (n == 0) errno = EPROTO; return -1; }
        p += n; len -= (size_t)n;
    }
    return 0;
}

int net_listen(const config_t *cfg) {
    struct addrinfo hints = {0}, *list = NULL;
    hints.ai_family = AF_UNSPEC; hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags = AI_PASSIVE | AI_NUMERICSERV;
    if (getaddrinfo(cfg->host, cfg->port, &hints, &list)) return -1;
    int fd = -1;
    for (struct addrinfo *p = list; p; p = p->ai_next) {
        fd = socket(p->ai_family, p->ai_socktype, p->ai_protocol);
        if (fd < 0) continue;
        int on = 1;
        if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on)) == 0 &&
            nonblocking(fd) == 0 && bind(fd, p->ai_addr, p->ai_addrlen) == 0 &&
            listen(fd, 128) == 0) break;
        close(fd); fd = -1;
    }
    freeaddrinfo(list); return fd;
}

int net_connect(const backend_t *b, int64_t deadline) {
    int fd = socket(b->address.ss_family, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    if (tcp_prepare(fd) < 0) { close(fd); return -1; }
    if (connect(fd, (const struct sockaddr *)&b->address, b->address_len) == 0) return fd;
    if (errno == EINPROGRESS && wait_fd(fd, POLLOUT, deadline) == 0) {
        int error = 0; socklen_t len = sizeof(error);
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &len) == 0 && !error) return fd;
        if (error) errno = error;
    }
    int saved = errno; close(fd); errno = saved; return -1;
}
