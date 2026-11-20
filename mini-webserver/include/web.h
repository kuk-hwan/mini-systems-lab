#ifndef MINI_WEB_H
#define MINI_WEB_H

#define _POSIX_C_SOURCE 200809L
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdatomic.h>
#include <pthread.h>
#include <sys/socket.h>

#define HEADER_LIMIT 16384
#define URI_LIMIT 4096
#define HEADER_COUNT 64
#define BODY_LIMIT (1024 * 1024)
#define UPSTREAM_LIMIT (8 * 1024 * 1024)
#define ROUTE_LIMIT 16
#define BACKEND_LIMIT 8
#define REQUEST_LIMIT 100

typedef struct { char name[64]; char value[2048]; } header_t;
typedef struct { header_t items[HEADER_COUNT]; size_t count; } headers_t;
typedef struct {
    char method[16], target[URI_LIMIT + 1];
    int minor;
    headers_t headers;
    size_t content_length;
    unsigned char *body;
    bool keep_alive, expect_continue;
} request_t;
typedef struct {
    int fd;
    unsigned char buf[HEADER_LIMIT];
    size_t start, end;
    int64_t deadline;
} stream_t;
typedef struct {
    char host[256], port[6], authority[272];
    struct sockaddr_storage address;
    socklen_t address_len;
} backend_t;
typedef struct {
    char prefix[URI_LIMIT + 1];
    backend_t backends[BACKEND_LIMIT];
    size_t count, next;
    pthread_mutex_t lock;
} route_t;
typedef struct {
    char host[256], port[6], root[4096], name[64];
    int workers, queue_size, timeout_ms, upstream_timeout_ms, root_fd;
    route_t routes[ROUTE_LIMIT];
    size_t route_count;
    atomic_bool stopping;
} config_t;

int64_t now_ms(void);
int nonblocking(int fd);
int tcp_prepare(int fd);
int wait_fd(int fd, short events, int64_t deadline);
int send_all(int fd, const void *buf, size_t len, int64_t deadline);
void connection_close(int fd);
void stream_init(stream_t *s, int fd, int64_t deadline);
int stream_line(stream_t *s, char *out, size_t capacity);
int stream_exact(stream_t *s, void *out, size_t len);
int stream_some(stream_t *s, void *out, size_t capacity);
int net_listen(const config_t *cfg);
int net_connect(const backend_t *b, int64_t deadline);

const char *header_get(const headers_t *h, const char *name);
bool header_has_token(const char *value, const char *token);
bool hop_header(const headers_t *h, const char *name);
int parse_headers(char *text, headers_t *headers);
int parse_request_head(char *text, request_t *request);
int read_head(stream_t *s, char *text, size_t capacity);
int read_request(stream_t *s, request_t *request);
void request_free(request_t *request);
const char *status_reason(int status);
int response_head(int fd, int status, const char *type, size_t length,
                  bool keep, const headers_t *extra, int64_t deadline);
int response_body(int fd, int status, const char *type, const void *body,
                  size_t length, bool keep, bool head, int64_t deadline);
int response_error(int fd, int status, bool head, int64_t deadline);

int config_init(config_t *cfg, int argc, char **argv);
void config_destroy(config_t *cfg);
route_t *route_match(config_t *cfg, const char *path);
backend_t *route_next(route_t *route);
const char *mime_type(const char *path);
int decode_path(const char *target, char *out, size_t capacity);
int static_open(int root_fd, const char *path, int *status);
int serve_static(config_t *cfg, int fd, const request_t *req,
                 bool keep, int64_t deadline);
int serve_proxy(config_t *cfg, route_t *route, int fd,
                const request_t *req, bool keep, int64_t deadline);
void handle_connection(config_t *cfg, int fd);

typedef struct {
    config_t *config;
    int *queue;
    size_t head, count, capacity;
    bool stopping;
    pthread_mutex_t lock;
    pthread_cond_t ready;
    pthread_t *threads;
    size_t thread_count;
} pool_t;
int pool_init(pool_t *pool, config_t *cfg);
bool pool_submit(pool_t *pool, int fd);
void pool_stop(pool_t *pool);
#endif
