#include "web.h"
#include <errno.h>
#include <netdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>

static int forward_request(int upstream, int client, const backend_t *b,
                           const request_t *req, int64_t deadline) {
    char head[HEADER_LIMIT + 4096], peer[1025];
    struct sockaddr_storage addr; socklen_t addrlen = sizeof(addr);
    strcpy(peer, "unknown");
    if (getpeername(client, (struct sockaddr *)&addr, &addrlen) == 0)
        getnameinfo((struct sockaddr *)&addr, addrlen, peer, sizeof(peer), NULL, 0, NI_NUMERICHOST);
    int n = snprintf(head, sizeof(head), "%s %s HTTP/1.1\r\nHost: %s\r\n"
        "Connection: close\r\nContent-Length: %zu\r\nVia: 1.1 mini-c-web\r\n"
        "X-Forwarded-For: %s\r\nX-Forwarded-Proto: http\r\n",
        req->method, req->target, b->authority, req->content_length, peer);
    if (n < 0 || (size_t)n >= sizeof(head)) return -1;
    size_t used = (size_t)n;
    for (size_t i = 0; i < req->headers.count; i++) {
        const header_t *h = &req->headers.items[i];
        if (hop_header(&req->headers, h->name) || !strcasecmp(h->name, "Host") ||
            !strcasecmp(h->name, "Content-Length") || !strcasecmp(h->name, "Expect") ||
            !strcasecmp(h->name, "Via") || !strcasecmp(h->name, "Forwarded") ||
            !strncasecmp(h->name, "X-Forwarded-", 12)) continue;
        n = snprintf(head + used, sizeof(head) - used, "%s: %s\r\n", h->name, h->value);
        if (n < 0 || (size_t)n >= sizeof(head) - used) return -1;
        used += (size_t)n;
    }
    if (used + 2 > sizeof(head)) return -1;
    memcpy(head + used, "\r\n", 2); used += 2;
    if (send_all(upstream, head, used, deadline) < 0) return -1;
    return send_all(upstream, req->body, req->content_length, deadline);
}

static int length_value(const char *s, size_t *out) {
    if (!s || !*s) return -1;
    size_t n = 0;
    for (; *s; s++) {
        if (*s < '0' || *s > '9' || n > (SIZE_MAX - (size_t)(*s - '0')) / 10) return -1;
        n = n * 10 + (size_t)(*s - '0');
    }
    *out = n; return 0;
}

static int upstream_head(stream_t *s, headers_t *headers, int *status) {
    for (int informational = 0; informational < 8; informational++) {
        char text[HEADER_LIMIT + 1];
        if (read_head(s, text, sizeof(text))) return -1;
        char *end = strstr(text, "\r\n");
        if (!end) return -1;
        *end = 0;
        size_t len = strlen(text);
        if (len < 13 || (strncmp(text, "HTTP/1.1 ", 9) && strncmp(text, "HTTP/1.0 ", 9)) ||
            text[9] < '1' || text[9] > '5' || text[10] < '0' || text[10] > '9' ||
            text[11] < '0' || text[11] > '9' || text[12] != ' ') return -1;
        for (size_t i = 13; i < len; i++)
            if ((unsigned char)text[i] < 32 || (unsigned char)text[i] == 127) return -1;
        *status = (text[9] - '0') * 100 + (text[10] - '0') * 10 + text[11] - '0';
        if (parse_headers(end + 2, headers)) return -1;
        if (*status == 101) return -1; /* No protocol upgrades/tunneling in this scope. */
        if (*status >= 200) return 0;
    }
    return -1;
}

static int append(unsigned char **body, size_t *used, const void *data, size_t n) {
    if (n > UPSTREAM_LIMIT - *used) { errno = EOVERFLOW; return -1; }
    unsigned char *p = realloc(*body, *used + n + 1);
    if (!p) return -1;
    *body = p; memcpy(p + *used, data, n); *used += n;
    return 0;
}

static int chunked_body(stream_t *s, unsigned char **body, size_t *used) {
    char line[8192]; unsigned char buf[16384];
    for (;;) {
        int n = stream_line(s, line, sizeof(line));
        if (n <= 0) return -1;
        line[n - 2] = 0;
        char *p = line; size_t size = 0, digits = 0;
        while (*p && *p != ';') {
            unsigned char c = (unsigned char)*p++;
            int v = c >= '0' && c <= '9' ? c - '0' :
                (c >= 'a' && c <= 'f' ? c - 'a' + 10 : (c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1));
            if (v < 0 || size > (SIZE_MAX - (size_t)v) / 16) return -1;
            size = size * 16 + (size_t)v; digits++;
        }
        if (!digits || size > UPSTREAM_LIMIT - *used) return -1;
        if (!size) {
            /* Consume bounded trailers but never promote them into response headers. */
            size_t total = 0;
            for (;;) {
                n = stream_line(s, line, sizeof(line));
                if (n <= 0 || (total += (size_t)n) > HEADER_LIMIT) return -1;
                if (n == 2) return 0;
                if (line[0] == ' ' || line[0] == '\t' || !strchr(line, ':')) return -1;
            }
        }
        while (size) {
            size_t wanted = size < sizeof(buf) ? size : sizeof(buf);
            if (stream_exact(s, buf, wanted) < 0 || append(body, used, buf, wanted) < 0) return -1;
            size -= wanted;
        }
        unsigned char crlf[2];
        if (stream_exact(s, crlf, 2) < 0 || memcmp(crlf, "\r\n", 2)) return -1;
    }
}

int serve_proxy(config_t *cfg, route_t *route, int client, const request_t *req,
                bool keep, int64_t deadline) {
    int64_t upstream_deadline = now_ms() + cfg->upstream_timeout_ms;
    if (upstream_deadline > deadline) upstream_deadline = deadline;
    backend_t *b = route_next(route);
    int fd = net_connect(b, upstream_deadline), status = 502, result = -1;
    unsigned char *body = NULL; size_t length = 0, declared = 0;
    headers_t headers;
    bool head = !strcmp(req->method, "HEAD");
    if (fd < 0) goto failed;
    if (forward_request(fd, client, b, req, upstream_deadline) < 0) goto failed;
    stream_t stream; stream_init(&stream, fd, upstream_deadline);
    if (upstream_head(&stream, &headers, &status) < 0) goto failed;
    const char *te = header_get(&headers, "Transfer-Encoding");
    const char *cl = header_get(&headers, "Content-Length");
    if ((te && cl) || (te && strcasecmp(te, "chunked"))) goto failed;
    if (cl && length_value(cl, &declared) < 0) goto failed;
    if (head || status == 204 || status == 304) {
        length = 0;
    } else if (te) {
        if (chunked_body(&stream, &body, &length) < 0) goto failed;
    } else if (cl) {
        if (declared > UPSTREAM_LIMIT) goto failed;
        body = malloc(declared + 1);
        if (!body || stream_exact(&stream, body, declared) < 0) goto failed;
        length = declared;
    } else {
        unsigned char buf[16384]; int n;
        while ((n = stream_some(&stream, buf, sizeof(buf))) > 0)
            if (append(&body, &length, buf, (size_t)n) < 0) goto failed;
        if (n < 0) goto failed;
    }
    close(fd); fd = -1;
    const char *type = header_get(&headers, "Content-Type");
    result = response_head(client, status, type ? type : "application/octet-stream",
        head ? declared : length, keep, &headers, deadline);
    if (result == 0 && !head && length) result = send_all(client, body, length, deadline);
    free(body); return result;
failed: {
    int error = errno;
    if (fd >= 0) close(fd);
    free(body);
    status = error == ETIMEDOUT ? 504 : 502;
    response_error(client, status, head, now_ms() + cfg->timeout_ms);
    return -1; /* No automatic replay: POST could already have changed the backend. */
}
}
