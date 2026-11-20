#include "web.h"
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int number(const char *s, int min, int max) {
    char *end; errno = 0;
    long n = strtol(s, &end, 10);
    return errno || !*s || *end || n < min || n > max ? -1 : (int)n;
}

static int endpoint(char *text, backend_t *b) {
    char *host = text, *port;
    if (*host == '[') {
        host++; char *end = strchr(host, ']');
        if (!end || end[1] != ':') return -1;
        *end = 0; port = end + 2;
    } else {
        port = strrchr(host, ':');
        if (!port) return -1;
        *port++ = 0;
        if (strchr(host, ':')) return -1;
    }
    if (!*host || strlen(host) >= sizeof(b->host) || number(port, 1, 65535) < 0) return -1;
    strcpy(b->host, host); snprintf(b->port, sizeof(b->port), "%u", (unsigned)(unsigned short)number(port, 1, 65535));
    snprintf(b->authority, sizeof(b->authority), strchr(host, ':') ? "[%s]:%s" : "%s:%s", b->host, b->port);
    /* Resolve once at startup: no DNS lookup can stall a request worker. */
    struct addrinfo hints = {0}, *list = NULL;
    hints.ai_family = AF_UNSPEC; hints.ai_socktype = SOCK_STREAM; hints.ai_flags = AI_NUMERICSERV;
    if (getaddrinfo(b->host, b->port, &hints, &list)) return -1;
    if (!list || list->ai_addrlen > sizeof(b->address)) { if (list) freeaddrinfo(list); return -1; }
    memcpy(&b->address, list->ai_addr, list->ai_addrlen);
    b->address_len = list->ai_addrlen;
    freeaddrinfo(list); return 0;
}

static int add_route(config_t *cfg, const char *value) {
    if (cfg->route_count == ROUTE_LIMIT || strlen(value) > 8192) return -1;
    char *copy = strdup(value);
    if (!copy) return -1;
    char *equal = strchr(copy, '=');
    if (!equal) { free(copy); return -1; }
    *equal++ = 0;
    size_t len = strlen(copy);
    if (!len || len > URI_LIMIT || copy[0] != '/' || strchr(copy, '?')) { free(copy); return -1; }
    for (size_t i = 0; i < cfg->route_count; i++)
        if (!strcmp(cfg->routes[i].prefix, copy)) { free(copy); return -1; }
    route_t *r = &cfg->routes[cfg->route_count];
    strcpy(r->prefix, copy);
    char *save = NULL;
    for (char *p = strtok_r(equal, ",", &save); p; p = strtok_r(NULL, ",", &save)) {
        if (r->count == BACKEND_LIMIT || endpoint(p, &r->backends[r->count]) < 0) { free(copy); return -1; }
        r->count++;
    }
    free(copy);
    if (!r->count || pthread_mutex_init(&r->lock, NULL)) return -1;
    cfg->route_count++; return 0;
}

static void usage(const char *name) {
    fprintf(stderr, "Usage: %s [--host 127.0.0.1] [--port 8080] [--root public]\n"
        "  [--workers 4] [--queue 128] [--timeout-ms 5000]\n"
        "  [--upstream-timeout-ms 3000] [--name backend-A]\n"
        "  [--route '/api/=127.0.0.1:8001,127.0.0.1:8002']\n", name);
}

int config_init(config_t *cfg, int argc, char **argv) {
    memset(cfg, 0, sizeof(*cfg)); cfg->root_fd = -1;
    atomic_init(&cfg->stopping, false);
    strcpy(cfg->host, "127.0.0.1"); strcpy(cfg->port, "8080");
    strcpy(cfg->root, "public"); strcpy(cfg->name, "mini-c-web");
    cfg->workers = 4; cfg->queue_size = 128;
    cfg->timeout_ms = 5000; cfg->upstream_timeout_ms = 3000;
    for (int i = 1; i < argc; i++) {
        const char *key = argv[i];
        if (!strcmp(key, "--help")) { usage(argv[0]); return 1; }
        if (++i == argc) goto fail;
        const char *value = argv[i];
        if (!strcmp(key, "--host")) {
            if (strlen(value) >= sizeof(cfg->host)) goto fail;
            strcpy(cfg->host, value);
        } else if (!strcmp(key, "--port")) {
            int n = number(value, 1, 65535); if (n < 0) goto fail;
            snprintf(cfg->port, sizeof(cfg->port), "%u", (unsigned)(unsigned short)n);
        } else if (!strcmp(key, "--root")) {
            if (strlen(value) >= sizeof(cfg->root)) goto fail;
            strcpy(cfg->root, value);
        } else if (!strcmp(key, "--name")) {
            if (!*value || strlen(value) >= sizeof(cfg->name)) goto fail;
            for (const char *p = value; *p; p++)
                if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
                      (*p >= '0' && *p <= '9') || *p == '-' || *p == '_')) goto fail;
            strcpy(cfg->name, value);
        } else if (!strcmp(key, "--workers")) {
            cfg->workers = number(value, 1, 128); if (cfg->workers < 0) goto fail;
        } else if (!strcmp(key, "--queue")) {
            cfg->queue_size = number(value, 1, 4096); if (cfg->queue_size < 0) goto fail;
        } else if (!strcmp(key, "--timeout-ms")) {
            cfg->timeout_ms = number(value, 50, 60000); if (cfg->timeout_ms < 0) goto fail;
        } else if (!strcmp(key, "--upstream-timeout-ms")) {
            cfg->upstream_timeout_ms = number(value, 50, 60000); if (cfg->upstream_timeout_ms < 0) goto fail;
        } else if (!strcmp(key, "--route")) {
            if (add_route(cfg, value) < 0) goto fail;
        } else goto fail;
    }
    cfg->root_fd = open(cfg->root, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (cfg->root_fd < 0) { perror("static root"); goto fail; }
    return 0;
fail:
    usage(argv[0]); config_destroy(cfg); return -1;
}

void config_destroy(config_t *cfg) {
    if (cfg->root_fd >= 0) { close(cfg->root_fd); cfg->root_fd = -1; }
    for (size_t i = 0; i < cfg->route_count; i++) pthread_mutex_destroy(&cfg->routes[i].lock);
    cfg->route_count = 0;
}

route_t *route_match(config_t *cfg, const char *path) {
    route_t *best = NULL; size_t longest = 0;
    size_t path_len = strcspn(path, "?");
    for (size_t i = 0; i < cfg->route_count; i++) {
        route_t *r = &cfg->routes[i]; size_t n = strlen(r->prefix);
        if (n > path_len || strncmp(path, r->prefix, n)) continue;
        if (n && r->prefix[n - 1] != '/' && n != path_len && path[n] != '/') continue;
        if (n > longest) { best = r; longest = n; }
    }
    return best;
}

backend_t *route_next(route_t *r) {
    pthread_mutex_lock(&r->lock);
    backend_t *b = &r->backends[r->next];
    r->next = (r->next + 1) % r->count;
    pthread_mutex_unlock(&r->lock); return b;
}
