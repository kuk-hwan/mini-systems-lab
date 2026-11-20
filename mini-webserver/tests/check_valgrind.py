import argparse
import json
import re
from pathlib import Path
import tempfile

from support import running, request

parser = argparse.ArgumentParser()
parser.add_argument("--binary", default="build/mini-webserver")
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix="mini-web-valgrind-") as directory:
    root = Path(directory)
    (root / "index.html").write_text("valgrind fixture")
    prefix = ("valgrind", "--leak-check=full", "--show-leak-kinds=all",
              "--errors-for-leak-kinds=all", "--error-exitcode=99", "--track-fds=yes")
    # Exercise proxy buffers and a second thread pool under the same checker.
    with running(args.binary, root, "--workers", 2, prefix=prefix) as backend:
        with running(args.binary, root, "--workers", 2, "--timeout-ms", 1000,
                     "--route", f"/api/=127.0.0.1:{backend.port}", prefix=prefix) as proxy:
            for _ in range(10):
                assert request(proxy.port, "/")[0] == 200
                assert request(proxy.port, "/missing")[0] == 404
                assert request(proxy.port, "/api/echo", "POST", b"a\x00b")[2] == b"a\x00b"
                assert request(proxy.port, "/api/whoami")[0] == 200
        proxy_log = proxy.logs()
    backend_log = backend.logs()
    for log in (proxy_log, backend_log):
        assert "All heap blocks were freed -- no leaks are possible" in log, log
        assert "ERROR SUMMARY: 0 errors" in log, log
        assert re.search(r"FILE DESCRIPTORS:\s+3 open \(3 (?:std|inherited)\)", log), log
    reports = Path("reports")
    reports.mkdir(exist_ok=True)
    (reports / "valgrind.txt").write_text("PROXY\n" + proxy_log + "\nBACKEND\n" + backend_log)
    print(json.dumps({"servers_checked": 2, "requests": 40,
                      "memory_errors": 0, "unfreed_heap_blocks": 0,
                      "non_standard_fds_at_exit": 0}, indent=2))
