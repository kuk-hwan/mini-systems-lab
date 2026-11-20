#include "web.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

const char *mime_type(const char *path) {
    const char *ext = strrchr(path, '.');
    if (!ext) return "application/octet-stream";
    const char *types[][2] = {{".html", "text/html; charset=utf-8"}, {".htm", "text/html; charset=utf-8"},
        {".css", "text/css; charset=utf-8"}, {".js", "text/javascript; charset=utf-8"},
        {".json", "application/json; charset=utf-8"}, {".txt", "text/plain; charset=utf-8"},
        {".png", "image/png"}, {".jpg", "image/jpeg"}, {".jpeg", "image/jpeg"},
        {".gif", "image/gif"}, {".svg", "image/svg+xml"}, {".ico", "image/x-icon"}};
    for (size_t i = 0; i < sizeof(types) / sizeof(*types); i++)
        if (!strcasecmp(ext, types[i][0])) return types[i][1];
    return "application/octet-stream";
}

static int hex(unsigned char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

int decode_path(const char *target, char *out, size_t cap) {
    size_t used = 0;
    if (*target != '/') return 400;
    for (size_t i = 0; target[i] && target[i] != '?'; i++) {
        unsigned char c = (unsigned char)target[i];
        if (c == '%') {
            if (!target[i + 1] || !target[i + 2]) return 400;
            int a = hex((unsigned char)target[i + 1]), b = hex((unsigned char)target[i + 2]);
            if (a < 0 || b < 0) return 400;
            c = (unsigned char)(a * 16 + b); i += 2;
        }
        if (c < 32 || c == 127 || c == '\\' || c == '#') return 400;
        if (used + 1 >= cap) return 414;
        out[used++] = (char)c;
    }
    out[used] = 0;
    const char *p = out;
    while (*p) {
        while (*p == '/') p++;
        const char *end = strchr(p, '/');
        if (!end) end = p + strlen(p);
        size_t len = (size_t)(end - p);
        if ((len == 1 && p[0] == '.') || (len == 2 && p[0] == '.' && p[1] == '.')) return 403;
        p = end;
    }
    return 0;
}

/* Open each component relative to a trusted directory FD. Symlinks are never followed,
 * so a symlink swap cannot race a realpath()+open() containment check. */
int static_open(int root_fd, const char *path, int *status) {
    char copy[URI_LIMIT + 16];
    size_t len = strlen(path);
    if (!len || len > URI_LIMIT) { *status = 414; return -1; }
    strcpy(copy, path);
    if (copy[len - 1] == '/') strcat(copy, "index.html");
    int dir = dup(root_fd);
    if (dir < 0) { *status = 500; return -1; }
    char *save = NULL, *part = strtok_r(copy, "/", &save);
    while (part) {
        if (!strcmp(part, ".") || !strcmp(part, "..")) { close(dir); *status = 403; return -1; }
        char *next = strtok_r(NULL, "/", &save);
        int flags = O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK;
        if (next) flags |= O_DIRECTORY;
        int fd = openat(dir, part, flags);
        int error = errno; close(dir);
        if (fd < 0) {
            *status = error == ENOENT ? 404 : (error == EACCES || error == ELOOP || error == ENOTDIR ? 403 : 500);
            return -1;
        }
        if (!next) {
            struct stat st;
            if (fstat(fd, &st) < 0) { close(fd); *status = 500; return -1; }
            if (!S_ISREG(st.st_mode) || !(st.st_mode & 0444)) { close(fd); *status = 403; return -1; }
            *status = 200; return fd;
        }
        dir = fd; part = next;
    }
    close(dir); *status = 403; return -1;
}

int serve_static(config_t *cfg, int fd, const request_t *req, bool keep, int64_t deadline) {
    bool head = !strcmp(req->method, "HEAD");
    if (strcmp(req->method, "GET") && !head) {
        response_error(fd, 405, false, deadline); return -1;
    }
    char path[URI_LIMIT + 1];
    int status = decode_path(req->target, path, sizeof(path));
    if (status) { response_error(fd, status, head, deadline); return -1; }
    int file = static_open(cfg->root_fd, path, &status);
    if (file < 0) { response_error(fd, status, head, deadline); return -1; }
    struct stat st;
    if (fstat(file, &st) < 0 || st.st_size < 0 || (uintmax_t)st.st_size > SIZE_MAX) {
        close(file); response_error(fd, 500, head, deadline); return -1;
    }
    const char *type = mime_type(path[strlen(path) - 1] == '/' ? "index.html" : path);
    int rc = response_head(fd, 200, type, (size_t)st.st_size, keep, NULL, deadline);
    if (head || rc < 0) { close(file); return rc; }
    unsigned char buf[32768]; size_t left = (size_t)st.st_size;
    while (left) {
        size_t wanted = left < sizeof(buf) ? left : sizeof(buf);
        ssize_t n = read(file, buf, wanted);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0 || send_all(fd, buf, (size_t)n, deadline) < 0) { rc = -1; break; }
        left -= (size_t)n;
    }
    close(file); return rc;
}
