"""Standard-library-only test tooling; the server under test is C/POSIX."""
import contextlib
import http.client
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(port, path="/health", method="GET", body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


class Server:
    def __init__(self, binary, root, *args, prefix=(), env=None):
        self.port = free_port()
        self.log = tempfile.TemporaryFile(mode="w+b")
        self.command = [*prefix, str(Path(binary).resolve()), "--port", str(self.port),
                        "--root", str(root), *map(str, args)]
        self.process = subprocess.Popen(self.command, stdout=self.log, stderr=self.log, env=env)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Server exited {self.process.returncode}: {self.logs()}")
            self.log.seek(0)
            if b"READY " in self.log.read():
                return
            time.sleep(0.02)
        self.close()
        raise RuntimeError("server startup timed out")

    def logs(self):
        if self.log.closed:
            return self.final_log
        self.log.seek(0)
        return self.log.read().decode("utf-8", errors="replace")

    def close(self, sig=signal.SIGTERM):
        if self.process.poll() is None:
            self.process.send_signal(sig)
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
            raise AssertionError("server did not shut down within its deadline")
        log = self.logs()
        self.final_log = log
        self.log.close()
        if self.process.returncode != 0:
            raise AssertionError(f"server exit={self.process.returncode}\n{log}")
        if "ERROR: AddressSanitizer" in log or "runtime error:" in log or "LeakSanitizer" in log:
            raise AssertionError(log)
        return log


@contextlib.contextmanager
def running(binary, root, *args, **kwargs):
    server = Server(binary, root, *args, **kwargs)
    try:
        yield server
    finally:
        server.close()


def raw(port, data, shutdown=True):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(data)
        if shutdown:
            sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            try:
                data = sock.recv(65536)
            except ConnectionResetError:
                if chunks:
                    return b"".join(chunks)
                raise
            if not data:
                return b"".join(chunks)
            chunks.append(data)
