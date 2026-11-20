#include "web.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <time.h>

const char *header_get(const headers_t *h, const char *name) {
    for (size_t i = 0; i < h->count; i++)
        if (!strcasecmp(h->items[i].name, name)) return h->items[i].value;
    return NULL;
}

bool header_has_token(const char *value, const char *token) {
    if (!value) return false;
    while (*value) {
        while (*value == ',' || *value == ' ' || *value == '\t') value++;
        const char *end = strchr(value, ',');
        if (!end) end = value + strlen(value);
        const char *trim = end;
        while (trim > value && (trim[-1] == ' ' || trim[-1] == '\t')) trim--;
        if ((size_t)(trim - value) == strlen(token) && !strncasecmp(value, token, strlen(token))) return true;
        value = end;
    }
    return false;
}

bool hop_header(const headers_t *h, const char *name) {
    const char *fixed[] = {"Connection", "Proxy-Connection", "Keep-Alive", "TE",
        "Trailer", "Transfer-Encoding", "Upgrade", "Proxy-Authorization", "Proxy-Authenticate"};
    for (size_t i = 0; i < sizeof(fixed) / sizeof(*fixed); i++)
        if (!strcasecmp(fixed[i], name)) return true;
    return header_has_token(header_get(h, "Connection"), name);
}

static bool token_char(unsigned char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
        (c >= '0' && c <= '9') || strchr("!#$%&'*+-.^_`|~", c) != NULL;
}

int parse_headers(char *text, headers_t *h) {
    h->count = 0;
    while (*text) {
        char *end = strstr(text, "\r\n");
        if (!end) return 400;
        if (end == text) return end[2] ? 400 : 0;
        *end = 0;
        if (h->count == HEADER_COUNT) return 431;
        char *colon = strchr(text, ':');
        if (!colon || colon == text) return 400;
        for (char *p = text; p < colon; p++) if (!token_char((unsigned char)*p)) return 400;
        *colon = 0;
        char *value = colon + 1;
        while (*value == ' ' || *value == '\t') value++;
        char *tail = end;
        while (tail > value && (tail[-1] == ' ' || tail[-1] == '\t')) *--tail = 0;
        for (char *p = value; *p; p++)
            if (((unsigned char)*p < 32 && *p != '\t') || (unsigned char)*p == 127) return 400;
        if (strlen(text) >= sizeof(h->items[0].name) || strlen(value) >= sizeof(h->items[0].value)) return 431;
        /* Reject ambiguous singleton fields, including duplicate identical lengths. */
        const char *single[] = {"Host", "Content-Length", "Transfer-Encoding", "Connection", "Expect"};
        for (size_t i = 0; i < sizeof(single) / sizeof(*single); i++)
            if (!strcasecmp(text, single[i]) && header_get(h, text)) return 400;
        strcpy(h->items[h->count].name, text);
        strcpy(h->items[h->count++].value, value);
        text = end + 2;
    }
    return 400; /* An explicit terminating empty line is required. */
}

static int parse_length(const char *s, size_t *length) {
    size_t n = 0;
    if (!s || !*s) return 400;
    for (; *s; s++) {
        if (*s < '0' || *s > '9') return 400;
        if (n > (SIZE_MAX - (size_t)(*s - '0')) / 10) return 413;
        n = n * 10 + (size_t)(*s - '0');
    }
    *length = n; return 0;
}

int parse_request_head(char *text, request_t *r) {
    memset(r, 0, sizeof(*r));
    char *end = strstr(text, "\r\n");
    if (!end) return 400;
    *end = 0;
    char *space = strchr(text, ' ');
    if (!space || space == text) return 400;
    *space++ = 0;
    if (strlen(text) >= sizeof(r->method)) return 501;
    for (char *p = text; *p; p++) if (!token_char((unsigned char)*p)) return 400;
    strcpy(r->method, text);
    char *version = strchr(space, ' ');
    if (!version || version == space) return 400;
    *version++ = 0;
    if (strlen(space) > URI_LIMIT) return 414;
    for (char *p = space; *p; p++) if ((unsigned char)*p <= 32 || (unsigned char)*p == 127) return 400;
    if (*space != '/' || strchr(space, '#')) return 400;
    strcpy(r->target, space);
    if (!strcmp(version, "HTTP/1.1")) r->minor = 1;
    else if (!strcmp(version, "HTTP/1.0")) r->minor = 0;
    else return !strncmp(version, "HTTP/", 5) ? 505 : 400;
    int status = parse_headers(end + 2, &r->headers);
    if (status) return status;
    const char *host = header_get(&r->headers, "Host");
    if (r->minor == 1 && (!host || !*host)) return 400;
    if (host) for (const unsigned char *p = (const unsigned char *)host; *p; p++)
        if (*p <= 32 || *p == 127 || strchr("/@,\\", *p)) return 400;
    const char *cl = header_get(&r->headers, "Content-Length");
    const char *te = header_get(&r->headers, "Transfer-Encoding");
    if (cl && te) return 400;
    if (te) return 501; /* Limited scope: request framing uses Content-Length. */
    if (cl && (status = parse_length(cl, &r->content_length))) return status;
    if (r->content_length > BODY_LIMIT) return 413;
    if (!strcmp(r->method, "POST") && !cl) return 411;
    const char *expect = header_get(&r->headers, "Expect");
    if (expect && strcasecmp(expect, "100-continue")) return 417;
    r->expect_continue = expect != NULL;
    const char *connection = header_get(&r->headers, "Connection");
    r->keep_alive = r->minor ? !header_has_token(connection, "close") :
        header_has_token(connection, "keep-alive") && !header_has_token(connection, "close");
    if (strcmp(r->method, "GET") && strcmp(r->method, "POST") && strcmp(r->method, "HEAD")) return 501;
    return 0;
}

/* Preserve bytes after the header in stream_t, including pipelined requests. */
int read_head(stream_t *s, char *text, size_t cap) {
    size_t used = 0;
    for (;;) {
        int n = stream_line(s, text + used, cap - used);
        if (n == -2) return 431;
        if (n < 0) return errno == ETIMEDOUT ? 408 : 400;
        if (!n) return used ? 400 : -1;
        used += (size_t)n;
        if (used >= cap) return 431;
        if (n == 2) return 0;
    }
}

int read_request(stream_t *s, request_t *r) {
    char head[HEADER_LIMIT + 1];
    memset(r, 0, sizeof(*r));
    int status = read_head(s, head, sizeof(head));
    if (status) return status;
    status = parse_request_head(head, r);
    if (status) return status;
    if (r->expect_continue && r->content_length) {
        const char msg[] = "HTTP/1.1 100 Continue\r\n\r\n";
        if (send_all(s->fd, msg, sizeof(msg) - 1, s->deadline) < 0) return -1;
    }
    if (r->content_length) {
        r->body = malloc(r->content_length);
        if (!r->body) return 500;
        if (stream_exact(s, r->body, r->content_length) < 0)
            return errno == ETIMEDOUT ? 408 : 400;
    }
    return 0;
}

void request_free(request_t *r) { free(r->body); r->body = NULL; }

const char *status_reason(int status) {
    switch (status) {
    case 200: return "OK"; case 201: return "Created";
    case 204: return "No Content"; case 304: return "Not Modified";
    case 400: return "Bad Request"; case 403: return "Forbidden";
    case 404: return "Not Found"; case 405: return "Method Not Allowed";
    case 408: return "Request Timeout"; case 411: return "Length Required";
    case 413: return "Content Too Large"; case 414: return "URI Too Long";
    case 417: return "Expectation Failed"; case 431: return "Request Header Fields Too Large";
    case 500: return "Internal Server Error"; case 501: return "Not Implemented";
    case 502: return "Bad Gateway"; case 503: return "Service Unavailable";
    case 504: return "Gateway Timeout"; case 505: return "HTTP Version Not Supported";
    default: return "Upstream Response";
    }
}

int response_head(int fd, int status, const char *type, size_t length,
                  bool keep, const headers_t *extra, int64_t deadline) {
    char head[HEADER_LIMIT + 2048], date[64];
    time_t now = time(NULL); struct tm tm;
    gmtime_r(&now, &tm); strftime(date, sizeof(date), "%a, %d %b %Y %H:%M:%S GMT", &tm);
    int n = snprintf(head, sizeof(head),
        "HTTP/1.1 %d %s\r\nServer: mini-c-web\r\nDate: %s\r\n"
        "Connection: %s\r\n", status, status_reason(status), date, keep ? "keep-alive" : "close");
    if (n < 0 || (size_t)n >= sizeof(head)) return -1;
    size_t used = (size_t)n;
    if (status != 204 && status != 304) {
        n = snprintf(head + used, sizeof(head) - used,
            "Content-Length: %zu\r\nContent-Type: %s\r\n", length, type);
        if (n < 0 || (size_t)n >= sizeof(head) - used) return -1;
        used += (size_t)n;
    }
    if (extra) for (size_t i = 0; i < extra->count; i++) {
        const header_t *h = &extra->items[i];
        if (hop_header(extra, h->name) || !strcasecmp(h->name, "Content-Length") ||
            !strcasecmp(h->name, "Content-Type") || !strcasecmp(h->name, "Server") ||
            !strcasecmp(h->name, "Date")) continue;
        n = snprintf(head + used, sizeof(head) - used, "%s: %s\r\n", h->name, h->value);
        if (n < 0 || (size_t)n >= sizeof(head) - used) return -1;
        used += (size_t)n;
    }
    if (used + 2 >= sizeof(head)) return -1;
    memcpy(head + used, "\r\n", 2); used += 2;
    return send_all(fd, head, used, deadline);
}

int response_body(int fd, int status, const char *type, const void *body,
                  size_t len, bool keep, bool head, int64_t deadline) {
    if (response_head(fd, status, type, len, keep, NULL, deadline) < 0) return -1;
    return head || !len ? 0 : send_all(fd, body, len, deadline);
}

int response_error(int fd, int status, bool head, int64_t deadline) {
    char body[256];
    int n = snprintf(body, sizeof(body), "{\"status\":%d,\"error\":\"%s\"}\n", status, status_reason(status));
    return response_body(fd, status, "application/json; charset=utf-8", body,
                         (size_t)n, false, head, deadline);
}
