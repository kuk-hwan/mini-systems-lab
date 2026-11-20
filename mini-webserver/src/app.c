#include "web.h"
#include <stdio.h>
#include <string.h>

void handle_connection(config_t *cfg, int fd) {
    stream_t stream; stream_init(&stream, fd, now_ms() + cfg->timeout_ms);
    for (unsigned count = 0; count < REQUEST_LIMIT && !atomic_load(&cfg->stopping); count++) {
        stream.deadline = now_ms() + cfg->timeout_ms;
        request_t req;
        int status = read_request(&stream, &req);
        if (status) {
            if (status > 0) response_error(fd, status, !strcmp(req.method, "HEAD"), now_ms() + 500);
            request_free(&req); return;
        }
        bool keep = req.keep_alive && count + 1 < REQUEST_LIMIT && !atomic_load(&cfg->stopping);
        bool head = !strcmp(req.method, "HEAD");
        char path[URI_LIMIT + 1];
        status = decode_path(req.target, path, sizeof(path));
        int rc;
        route_t *route = route_match(cfg, req.target);
        if (status) {
            rc = response_error(fd, status, head, stream.deadline); keep = false;
        } else if (route) {
            rc = serve_proxy(cfg, route, fd, &req, keep, stream.deadline);
        } else if (!strcmp(path, "/health")) {
            char body[128];
            int n = snprintf(body, sizeof(body), "{\"status\":\"ok\",\"server\":\"%s\"}\n", cfg->name);
            rc = response_body(fd, 200, "application/json; charset=utf-8", body,
                (size_t)n, keep, head, stream.deadline);
        } else if (!strcmp(path, "/api/echo")) {
            rc = response_body(fd, 200, "application/octet-stream", req.body,
                req.content_length, keep, head, stream.deadline);
        } else if (!strcmp(path, "/api/whoami")) {
            char body[256];
            int n = snprintf(body, sizeof(body), "{\"backend\":\"%s\",\"method\":\"%s\"}\n", cfg->name, req.method);
            rc = response_body(fd, 200, "application/json; charset=utf-8", body,
                (size_t)n, keep, head, stream.deadline);
        } else {
            rc = serve_static(cfg, fd, &req, keep, stream.deadline);
        }
        fprintf(stderr, "request method=%s target=%s handler=%s keep=%d\n",
            req.method, req.target, route ? "proxy" : "local", keep ? 1 : 0);
        request_free(&req);
        if (rc < 0 || !keep) return;
    }
}
