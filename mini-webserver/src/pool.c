#include "web.h"
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void *worker(void *arg) {
    pool_t *p = arg;
    for (;;) {
        pthread_mutex_lock(&p->lock);
        while (!p->count && !p->stopping) pthread_cond_wait(&p->ready, &p->lock);
        if (p->stopping) { pthread_mutex_unlock(&p->lock); return NULL; }
        int fd = p->queue[p->head];
        p->head = (p->head + 1) % p->capacity; p->count--;
        pthread_mutex_unlock(&p->lock);
        handle_connection(p->config, fd);
        connection_close(fd); /* Worker owns every dequeued connection, including error exits. */
    }
}

int pool_init(pool_t *p, config_t *cfg) {
    memset(p, 0, sizeof(*p)); p->config = cfg; p->capacity = (size_t)cfg->queue_size;
    p->queue = calloc(p->capacity, sizeof(int));
    p->threads = calloc((size_t)cfg->workers, sizeof(pthread_t));
    if (!p->queue || !p->threads) { free(p->queue); free(p->threads); return -1; }
    if (pthread_mutex_init(&p->lock, NULL)) { free(p->queue); free(p->threads); return -1; }
    if (pthread_cond_init(&p->ready, NULL)) {
        pthread_mutex_destroy(&p->lock); free(p->queue); free(p->threads); return -1;
    }
    for (int i = 0; i < cfg->workers; i++) {
        if (pthread_create(&p->threads[i], NULL, worker, p)) { pool_stop(p); return -1; }
        p->thread_count++;
    }
    return 0;
}

bool pool_submit(pool_t *p, int fd) {
    pthread_mutex_lock(&p->lock);
    bool accepted = !p->stopping && p->count < p->capacity;
    if (accepted) {
        p->queue[(p->head + p->count) % p->capacity] = fd; p->count++;
        pthread_cond_signal(&p->ready);
    }
    pthread_mutex_unlock(&p->lock); return accepted;
}

void pool_stop(pool_t *p) {
    atomic_store(&p->config->stopping, true);
    pthread_mutex_lock(&p->lock);
    p->stopping = true;
    while (p->count) {
        close(p->queue[p->head]); p->head = (p->head + 1) % p->capacity; p->count--;
    }
    pthread_cond_broadcast(&p->ready);
    pthread_mutex_unlock(&p->lock);
    for (size_t i = 0; i < p->thread_count; i++) pthread_join(p->threads[i], NULL);
    pthread_cond_destroy(&p->ready); pthread_mutex_destroy(&p->lock);
    free(p->queue); free(p->threads);
}
