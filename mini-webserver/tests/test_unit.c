#include "web.h"
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static unsigned checks;
#define CHECK(condition) do { checks++; if (!(condition)) { \
    fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #condition); exit(1); \
} } while (0)

static int parse(const char *text, request_t *request) {
    char copy[HEADER_LIMIT + 1];
    CHECK(strlen(text) < sizeof(copy)); strcpy(copy, text);
    return parse_request_head(copy, request);
}

static void parser_tests(void) {
    request_t r;
    CHECK(parse("GET / HTTP/1.1\r\nHost: localhost\r\n\r\n", &r) == 0);
    CHECK(r.keep_alive && !strcmp(r.target, "/") && !r.content_length);
    CHECK(parse("POST /api/echo HTTP/1.1\r\nhost: test\r\nContent-Length: 3\r\nConnection: CLOSE\r\n\r\n", &r) == 0);
    CHECK(!r.keep_alive && r.content_length == 3);
    CHECK(parse("GET / HTTP/1.0\r\n\r\n", &r) == 0 && !r.keep_alive);
    CHECK(parse("GET / HTTP/1.0\r\nConnection: keep-alive\r\n\r\n", &r) == 0 && r.keep_alive);
    CHECK(parse("GET / HTTP/1.1\r\n\r\n", &r) == 400);
    CHECK(parse("GET / HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n", &r) == 400);
    CHECK(parse("GET / HTTP/1.1\r\nHost: a b\r\n\r\n", &r) == 400);
    CHECK(parse("POST / HTTP/1.1\r\nHost: x\r\n\r\n", &r) == 411);
    CHECK(parse("POST / HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\n", &r) == 400);
    CHECK(parse("POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 1,1\r\n\r\n", &r) == 400);
    CHECK(parse("POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 1\r\nContent-Length: 1\r\n\r\n", &r) == 400);
    CHECK(parse("POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\nTransfer-Encoding: chunked\r\n\r\n", &r) == 400);
    CHECK(parse("POST / HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n", &r) == 501);
    CHECK(parse("POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 1048577\r\n\r\n", &r) == 413);
    CHECK(parse("POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 999999999999999999999999\r\n\r\n", &r) == 413);
    CHECK(parse("POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\nExpect: strange\r\n\r\n", &r) == 417);
    CHECK(parse("POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\nExpect: 100-continue\r\n\r\n", &r) == 0 && r.expect_continue);
    CHECK(parse("GET / HTTP/2.0\r\nHost: x\r\n\r\n", &r) == 505);
    CHECK(parse("GET / junk\r\nHost: x\r\n\r\n", &r) == 400);
    CHECK(parse("DELETE / HTTP/1.1\r\nHost: x\r\n\r\n", &r) == 501);
    CHECK(parse("GET http://evil/ HTTP/1.1\r\nHost: x\r\n\r\n", &r) == 400);
    CHECK(parse("GET /#fragment HTTP/1.1\r\nHost: x\r\n\r\n", &r) == 400);
    CHECK(parse("GET / HTTP/1.1\r\nHost : x\r\n\r\n", &r) == 400);
    CHECK(parse("GET / HTTP/1.1\r\nHost: x\r\n folded: value\r\n\r\n", &r) == 400);
    CHECK(parse("GET / HTTP/1.1\r\nHost: x\r\nX: value\001\r\n\r\n", &r) == 400);
    CHECK(header_has_token("keep-alive, CLOSE", "close"));
    CHECK(!header_has_token("disclose", "close"));
    char headers[] = "Connection: keep-alive, X-Secret\r\nX-Secret: hidden\r\n\r\n";
    headers_t h;
    CHECK(parse_headers(headers, &h) == 0);
    CHECK(hop_header(&h, "x-secret") && hop_header(&h, "Transfer-Encoding"));
    CHECK(!hop_header(&h, "Content-Type"));
}

static void path_tests(void) {
    char path[URI_LIMIT + 1];
    CHECK(decode_path("/hello%20world.txt?q=1", path, sizeof(path)) == 0 && !strcmp(path, "/hello world.txt"));
    CHECK(decode_path("/../secret", path, sizeof(path)) == 403);
    CHECK(decode_path("/%2e%2e/secret", path, sizeof(path)) == 403);
    CHECK(decode_path("/safe/%2f..%2fsecret", path, sizeof(path)) == 403);
    CHECK(decode_path("/a%00.txt", path, sizeof(path)) == 400);
    CHECK(decode_path("/a%0d%0a.txt", path, sizeof(path)) == 400);
    CHECK(decode_path("/a%5cb", path, sizeof(path)) == 400);
    CHECK(decode_path("/%GG", path, sizeof(path)) == 400);
    CHECK(decode_path("/%", path, sizeof(path)) == 400);
    CHECK(!strcmp(mime_type("a.HTML"), "text/html; charset=utf-8"));
    CHECK(!strcmp(mime_type("x.png"), "image/png"));
    CHECK(!strcmp(mime_type("x.jpg"), "image/jpeg"));
    CHECK(!strcmp(mime_type("x.css"), "text/css; charset=utf-8"));
    CHECK(!strcmp(mime_type("x.js"), "text/javascript; charset=utf-8"));
    CHECK(!strcmp(mime_type("x.unknown"), "application/octet-stream"));
    char directory[] = "/tmp/mini-web-unit-XXXXXX";
    CHECK(mkdtemp(directory) != NULL);
    int root = open(directory, O_RDONLY | O_DIRECTORY); CHECK(root >= 0);
    int file = openat(root, "index.html", O_CREAT | O_WRONLY, 0600); CHECK(file >= 0); close(file);
    CHECK(symlinkat("/etc/passwd", root, "escape") == 0);
    CHECK(mkdirat(root, "folder", 0700) == 0);
    int status;
    file = static_open(root, "/", &status); CHECK(file >= 0 && status == 200); close(file);
    CHECK(static_open(root, "/escape", &status) < 0 && status == 403);
    CHECK(static_open(root, "/missing", &status) < 0 && status == 404);
    CHECK(static_open(root, "/folder", &status) < 0 && status == 403);
    CHECK(static_open(root, "/../etc/passwd", &status) < 0 && status == 403);
    unlinkat(root, "index.html", 0); unlinkat(root, "escape", 0); unlinkat(root, "folder", AT_REMOVEDIR);
    close(root); rmdir(directory);
}

static void routing_tests(void) {
    config_t *c = calloc(1, sizeof(*c)); CHECK(c != NULL);
    strcpy(c->routes[0].prefix, "/api/"); c->routes[0].count = 2;
    strcpy(c->routes[1].prefix, "/api/admin/"); c->routes[1].count = 1;
    strcpy(c->routes[2].prefix, "/service"); c->route_count = 3;
    CHECK(pthread_mutex_init(&c->routes[0].lock, NULL) == 0);
    CHECK(route_match(c, "/api/echo?x=1") == &c->routes[0]);
    CHECK(route_match(c, "/api/admin/users") == &c->routes[1]);
    CHECK(route_match(c, "/apix") == NULL);
    CHECK(route_match(c, "/service?q=1") == &c->routes[2]);
    CHECK(route_match(c, "/service-other") == NULL);
    CHECK(route_next(&c->routes[0]) == &c->routes[0].backends[0]);
    CHECK(route_next(&c->routes[0]) == &c->routes[0].backends[1]);
    CHECK(route_next(&c->routes[0]) == &c->routes[0].backends[0]);
    pthread_mutex_destroy(&c->routes[0].lock); free(c);
}

int main(void) {
    parser_tests(); path_tests(); routing_tests();
    printf("PASS: %u unit assertions (HTTP framing, paths, MIME, routing, round-robin)\n", checks);
    return 0;
}
