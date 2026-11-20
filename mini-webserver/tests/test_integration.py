import argparse
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import signal
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading
import time
import unittest

from support import Server, free_port, raw, request, running


def read_message(stream, head=False):
    line = stream.readline()
    if not line:
        raise EOFError("missing response")
    status = int(line.split()[1])
    headers = {}
    while True:
        line = stream.readline()
        if line == b"\r\n":
            break
        if not line:
            raise EOFError("incomplete headers")
        name, value = line.decode("latin1").split(":", 1)
        headers[name.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    body = b"" if head else stream.read(length)
    return status, headers, body


class Backend(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            first = self.rfile.readline().decode("ascii").split()
            if len(first) != 3:
                return
            method, path, _ = first
            headers = {}
            while True:
                line = self.rfile.readline()
                if line == b"\r\n":
                    break
                if not line:
                    return
                key, value = line.decode("latin1").split(":", 1)
                headers[key.lower()] = value.strip()
            body = self.rfile.read(int(headers.get("content-length", "0")))
            if path.startswith("/api/slow"):
                time.sleep(0.5)
            if path.startswith("/api/chunked"):
                self.wfile.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Type: text/plain\r\n\r\n"
                                 b"3;ext=ok\r\nabc\r\n2\r\nde\r\n0\r\nX-Trailer: ignored\r\n\r\n")
                return
            if path.startswith("/api/truncated"):
                self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nshort")
                return
            if path.startswith("/api/ambiguous"):
                self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n")
                return
            if path.startswith("/api/badchunk"):
                self.wfile.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nZ\r\nx\r\n0\r\n\r\n")
                return
            if path.startswith("/api/huge"):
                self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 99999999\r\n\r\n")
                return
            if path.startswith("/api/no-content"):
                self.wfile.write(b"HTTP/1.1 204 No Content\r\n\r\n")
                return
            if path.startswith("/api/informational"):
                self.wfile.write(b"HTTP/1.1 100 Continue\r\n\r\n")
            if path.startswith("/api/echo"):
                result = body
            else:
                result = json.dumps({"backend": self.server.label, "path": path,
                                     "method": method, "headers": headers}).encode()
            status = b"404 Not Found" if path.startswith("/api/notfound") else b"200 OK"
            self.wfile.write(b"HTTP/1.1 " + status + b"\r\nContent-Type: application/json\r\n"
                             b"Connection: close, X-Private\r\nX-Private: secret\r\nSet-Cookie: a=1\r\nSet-Cookie: b=2\r\n")
            if not path.startswith("/api/close-delimited"):
                self.wfile.write(f"Content-Length: {len(result)}\r\n".encode())
            self.wfile.write(b"\r\n")
            if method != "HEAD":
                self.wfile.write(result)
        except (OSError, ValueError):
            pass


class BackendServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="mini-web-integration-")
        cls.root = Path(cls.temp.name)
        (cls.root / "index.html").write_text("<h1>POSIX server</h1>", encoding="utf-8")
        (cls.root / "style.css").write_text("body{color:navy}")
        (cls.root / "space name.txt").write_text("hello")
        (cls.root / "binary.png").write_bytes(bytes(range(256)) * 256)
        (cls.root / "private.txt").write_text("secret")
        (cls.root / "private.txt").chmod(0)
        (cls.root / "escape").symlink_to("/etc/passwd")
        (cls.root / "escaped-dir").symlink_to("/etc", target_is_directory=True)
        (cls.root / "directory").mkdir()
        cls.backends = []
        for label in ("A", "B"):
            backend = BackendServer(("127.0.0.1", 0), Backend)
            backend.label = label
            threading.Thread(target=backend.serve_forever, daemon=True).start()
            cls.backends.append(backend)
        ports = [b.server_address[1] for b in cls.backends]
        cls.server = Server(BINARY, cls.root, "--workers", 8, "--timeout-ms", 1000,
                            "--upstream-timeout-ms", 200,
                            "--route", f"/api/=127.0.0.1:{ports[0]},127.0.0.1:{ports[1]}",
                            "--route", f"/dead/=127.0.0.1:{free_port()}")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.close()
        finally:
            for backend in cls.backends:
                backend.shutdown()
                backend.server_close()
            (cls.root / "private.txt").chmod(0o600)
            cls.temp.cleanup()

    def test_static_html(self):
        status, headers, body = request(self.server.port, "/")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"<h1>POSIX server</h1>")
        self.assertIn("text/html", headers["Content-Type"])
        self.assertEqual(int(headers["Content-Length"]), len(body))

    def test_static_binary(self):
        status, headers, body = request(self.server.port, "/binary.png")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(body, bytes(range(256)) * 256)

    def test_static_mime_and_query(self):
        status, headers, body = request(self.server.port, "/style.css?v=1")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers["Content-Type"])
        self.assertTrue(body)

    def test_percent_encoded_filename(self):
        self.assertEqual(request(self.server.port, "/space%20name.txt")[2], b"hello")

    def test_missing_file(self):
        self.assertEqual(request(self.server.port, "/missing")[0], 404)

    def test_permission_denied(self):
        self.assertEqual(request(self.server.port, "/private.txt")[0], 403)

    def test_directory_denied(self):
        self.assertEqual(request(self.server.port, "/directory")[0], 403)

    def test_traversal_and_symlinks(self):
        for path in ("/../etc/passwd", "/%2e%2e/etc/passwd", "/escape", "/escaped-dir/passwd"):
            with self.subTest(path=path):
                response = raw(self.server.port, f"GET {path} HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n".encode())
                self.assertEqual(int(response.split()[1]), 403)

    def test_head_has_length_without_body(self):
        status, headers, body = request(self.server.port, "/", "HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(int(headers["Content-Length"]), 21)

    def test_post_static_rejected(self):
        self.assertEqual(request(self.server.port, "/", "POST", b"x")[0], 405)

    def test_parser_errors(self):
        cases = [
            (b"GET / HTTP/1.1\r\n\r\n", 400),
            (b"GET / HTTP/1.1\r\nHost: x\r\nHost: y\r\n\r\n", 400),
            (b"GET / HTTP/1.1\r\nHost : x\r\n\r\n", 400),
            (b"GET / HTTP/2.0\r\nHost: x\r\n\r\n", 505),
            (b"DELETE / HTTP/1.1\r\nHost: x\r\n\r\n", 501),
            (b"POST / HTTP/1.1\r\nHost: x\r\n\r\n", 411),
            (b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\n", 400),
            (b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 1\r\nContent-Length: 1\r\n\r\n", 400),
            (b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\nTransfer-Encoding: chunked\r\n\r\n", 400),
            (b"POST / HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n", 501),
            (b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 1048577\r\n\r\n", 413),
            (b"GET /%00 HTTP/1.1\r\nHost: x\r\n\r\n", 400),
            (b"GET / HTTP/1.1\r\nHost: x\r\nX: a\x00b\r\n\r\n", 400),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.assertEqual(int(raw(self.server.port, payload).split()[1]), expected)

    def test_long_uri(self):
        payload = b"GET /" + b"x" * 5000 + b" HTTP/1.1\r\nHost: x\r\n\r\n"
        self.assertEqual(int(raw(self.server.port, payload).split()[1]), 414)

    def test_long_header(self):
        payload = b"GET / HTTP/1.1\r\nHost: x\r\nX-Large: " + b"x" * 17000 + b"\r\n\r\n"
        response = raw(self.server.port, payload)
        self.assertEqual(int(response.split()[1]), 431)

    def test_incomplete_body(self):
        payload = b"POST /api/echo HTTP/1.1\r\nHost: x\r\nContent-Length: 10\r\n\r\nabc"
        self.assertEqual(int(raw(self.server.port, payload).split()[1]), 400)

    def test_incomplete_header_timeout(self):
        response = raw(self.server.port, b"GET / HTTP/1.1\r\nHost:", shutdown=False)
        self.assertEqual(int(response.split()[1]), 408)

    def test_fragmented_post(self):
        body = b"hello\x00binary\xff"
        with socket.create_connection(("127.0.0.1", self.server.port), timeout=5) as sock:
            data = f"POST /api/echo HTTP/1.1\r\nHost: x\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
            for i in range(0, len(data), 7):
                sock.sendall(data[i:i + 7])
                time.sleep(0.001)
            with sock.makefile("rb") as stream:
                status, _, result = read_message(stream)
            self.assertEqual((status, result), (200, body))

    def test_expect_continue(self):
        with socket.create_connection(("127.0.0.1", self.server.port), timeout=5) as sock:
            stream = sock.makefile("rb")
            sock.sendall(b"POST /api/echo HTTP/1.1\r\nHost: x\r\nContent-Length: 3\r\nExpect: 100-continue\r\nConnection: close\r\n\r\n")
            self.assertEqual(read_message(stream)[0], 100)
            sock.sendall(b"abc")
            self.assertEqual(read_message(stream)[2], b"abc")
            stream.close()

    def test_keep_alive_reuses_connection(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        try:
            conn.request("GET", "/health")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            first = conn.sock
            conn.request("GET", "/")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            self.assertIs(conn.sock, first)
        finally:
            conn.close()

    def test_pipeline_preserves_unread_bytes(self):
        with socket.create_connection(("127.0.0.1", self.server.port), timeout=5) as sock:
            sock.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n"
                         b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            with sock.makefile("rb") as stream:
                self.assertEqual(read_message(stream)[0], 200)
                self.assertEqual(read_message(stream)[2], b"<h1>POSIX server</h1>")

    def test_round_robin(self):
        labels = [json.loads(request(self.server.port, "/api/whoami")[2])["backend"] for _ in range(4)]
        self.assertEqual(labels[0], labels[2])
        self.assertEqual(labels[1], labels[3])
        self.assertNotEqual(labels[0], labels[1])

    def test_forwarding_path_and_hop_headers(self):
        status, response_headers, body = request(self.server.port, "/api/inspect?q=hello", headers={
            "Connection": "close, X-Private", "X-Private": "secret", "X-Keep": "yes", "X-Forwarded-For": "spoof"})
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(result["path"], "/api/inspect?q=hello")
        self.assertNotIn("x-private", result["headers"])
        self.assertEqual(result["headers"]["x-keep"], "yes")
        self.assertEqual(result["headers"]["x-forwarded-for"], "127.0.0.1")
        self.assertIn(result["headers"]["host"], [f"127.0.0.1:{b.server_address[1]}" for b in self.backends])
        self.assertNotIn("X-Private", response_headers)

    def test_proxy_post_binary(self):
        body = bytes(range(256)) * 1000
        self.assertEqual(request(self.server.port, "/api/echo", "POST", body)[2], body)

    def test_proxy_chunked_response(self):
        status, headers, body = request(self.server.port, "/api/chunked")
        self.assertEqual((status, body), (200, b"abcde"))
        self.assertEqual(headers["Content-Length"], "5")
        self.assertNotIn("Transfer-Encoding", headers)
        self.assertNotIn("X-Trailer", headers)

    def test_proxy_close_delimited(self):
        status, _, body = request(self.server.port, "/api/close-delimited")
        self.assertEqual(status, 200)
        self.assertIn("backend", json.loads(body))

    def test_proxy_invalid_responses(self):
        for path in ("/api/truncated", "/api/ambiguous", "/api/badchunk", "/api/huge"):
            with self.subTest(path=path):
                self.assertEqual(request(self.server.port, path)[0], 502)

    def test_proxy_timeout(self):
        self.assertEqual(request(self.server.port, "/api/slow")[0], 504)

    def test_proxy_connect_failure(self):
        self.assertEqual(request(self.server.port, "/dead/test")[0], 502)

    def test_proxy_preserves_error_status(self):
        self.assertEqual(request(self.server.port, "/api/notfound")[0], 404)

    def test_proxy_no_content(self):
        self.assertEqual(request(self.server.port, "/api/no-content")[::2], (204, b""))

    def test_proxy_informational_response(self):
        self.assertEqual(request(self.server.port, "/api/informational")[0], 200)

    def test_proxy_head(self):
        status, headers, body = request(self.server.port, "/api/whoami", "HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertGreater(int(headers["Content-Length"]), 0)

    def test_proxy_preserves_duplicate_set_cookie(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        try:
            conn.request("GET", "/api/whoami")
            response = conn.getresponse()
            cookies = [value for key, value in response.getheaders() if key.lower() == "set-cookie"]
            response.read()
            self.assertEqual(cookies, ["a=1", "b=2"])
        finally:
            conn.close()

    def test_slow_input_cannot_reset_deadline(self):
        with running(BINARY, self.root, "--timeout-ms", 200) as server:
            with socket.create_connection(("127.0.0.1", server.port), timeout=5) as sock:
                start = time.monotonic()
                sock.sendall(b"GET / HTTP/1.1\r\n")
                time.sleep(0.12)
                sock.sendall(b"Host: test\r\n")
                with sock.makefile("rb") as stream:
                    self.assertEqual(read_message(stream)[0], 408)
                self.assertLess(time.monotonic() - start, 0.8)

    def test_concurrent_requests(self):
        with ThreadPoolExecutor(max_workers=24) as executor:
            results = list(executor.map(lambda _: request(self.server.port, "/health"), range(100)))
        self.assertTrue(all(status == 200 for status, _, _ in results))

    def test_client_disconnect_does_not_kill_server(self):
        for _ in range(10):
            sock = socket.create_connection(("127.0.0.1", self.server.port), timeout=5)
            sock.sendall(b"GET /binary.png HTTP/1.1\r\nHost: x\r\n\r\n")
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            sock.close()
        self.assertEqual(request(self.server.port)[0], 200)

    def test_bounded_queue(self):
        with running(BINARY, self.root, "--workers", 1, "--queue", 1, "--timeout-ms", 1000) as server:
            a = socket.create_connection(("127.0.0.1", server.port), timeout=5)
            time.sleep(0.05)
            b = socket.create_connection(("127.0.0.1", server.port), timeout=5)
            time.sleep(0.05)
            try:
                response = raw(server.port, b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
                self.assertEqual(int(response.split()[1]), 503)
            finally:
                a.close()
                b.close()

    def test_shutdown_with_idle_connection(self):
        server = Server(BINARY, self.root, "--timeout-ms", 500)
        with socket.create_connection(("127.0.0.1", server.port), timeout=5):
            time.sleep(0.05)
            start = time.monotonic()
            log = server.close(sig=signal.SIGINT)
            self.assertLess(time.monotonic() - start, 3)
            self.assertIn("STOPPED", log)

    def test_fd_recovery(self):
        directory = Path(f"/proc/{self.server.process.pid}/fd")
        if not directory.exists():
            self.skipTest("Linux /proc only")
        time.sleep(0.05)
        before = len(list(directory.iterdir()))
        for _ in range(30):
            request(self.server.port, "/api/whoami")
            request(self.server.port, "/missing")
        time.sleep(0.1)
        self.assertLessEqual(len(list(directory.iterdir())), before + 2)

    def test_bind_failure_is_reported(self):
        result = subprocess.run([BINARY, "--port", str(self.server.port), "--root", str(self.root)], capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"socket/bind/listen", result.stderr)

    def test_invalid_configuration(self):
        for args in (("--port", "70000"), ("--workers", "0"), ("--route", "/x/=not-an-endpoint"), ("--unknown", "x")):
            result = subprocess.run([BINARY, "--root", str(self.root), *args], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="build/mini-webserver")
    args, remaining = parser.parse_known_args()
    BINARY = str(Path(args.binary).resolve())
    unittest.main(argv=[__file__, *remaining], verbosity=2)
