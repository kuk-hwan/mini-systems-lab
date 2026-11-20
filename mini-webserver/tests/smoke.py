"""Use actual curl against the static demo and three C server processes."""
import argparse
import json
from pathlib import Path
import subprocess

from support import running

parser = argparse.ArgumentParser()
parser.add_argument("--binary", default="build/mini-webserver")
args = parser.parse_args()
root = Path("public").resolve()
with running(args.binary, root, "--name", "backend-A") as a:
    with running(args.binary, root, "--name", "backend-B") as b:
        with running(args.binary, root, "--route",
                     f"/api/=127.0.0.1:{a.port},127.0.0.1:{b.port}") as proxy:
            base = f"http://127.0.0.1:{proxy.port}"
            def curl(path, *extra, input=None):
                return subprocess.check_output(["curl", "--fail", "--silent", "--show-error", *extra, base + path],
                                               input=input, timeout=5)
            assert b"socketlab" in curl("/")
            assert b".flow" in curl("/style.css")
            assert b"fetch(" in curl("/app.js")
            assert b"<svg" in curl("/icon.svg")
            assert json.loads(curl("/health"))["status"] == "ok"
            assert [json.loads(curl("/api/whoami"))["backend"] for _ in range(4)] == [
                "backend-A", "backend-B", "backend-A", "backend-B"]
            body = "안녕하세요, POSIX!".encode()
            assert curl("/api/echo", "--data-binary", "@-", input=body) == body
            print("PASS: actual curl, HTML/CSS/JS/SVG, health, A/B round-robin, UTF-8 POST")
