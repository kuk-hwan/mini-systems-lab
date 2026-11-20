"""Run real Apache Bench against static and round-robin proxy paths."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import subprocess

from support import running

parser = argparse.ArgumentParser()
parser.add_argument("--binary", default="build/mini-webserver")
parser.add_argument("--requests", type=int, default=1000)
parser.add_argument("--workers", type=int, default=64)
args = parser.parse_args()
root = Path("public").resolve()
results = []
reports = Path("reports")
reports.mkdir(exist_ok=True)
with running(args.binary, root, "--name", "backend-A") as a:
    with running(args.binary, root, "--name", "backend-B") as b:
        with running(args.binary, root, "--workers", args.workers, "--queue", 512,
                     "--route", f"/api/=127.0.0.1:{a.port},127.0.0.1:{b.port}") as server:
            for path, label in (("/", "static"), ("/api/whoami", "reverse-proxy")):
                for concurrency in (1, 10, 50):
                    for keep_alive in (False, True):
                        command = ["ab", "-n", str(args.requests), "-c", str(concurrency), "-s", "10", "-l"]
                        if keep_alive:
                            command.append("-k")
                        command.append(f"http://127.0.0.1:{server.port}{path}")
                        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
                        if result.returncode:
                            raise RuntimeError(result.stdout + result.stderr)
                        output = result.stdout
                        failed = int(re.search(r"Failed requests:\s+(\d+)", output)[1])
                        complete = int(re.search(r"Complete requests:\s+(\d+)", output)[1])
                        rps = float(re.search(r"Requests per second:\s+([\d.]+)", output)[1])
                        non_2xx = re.search(r"Non-2xx responses:\s+(\d+)", output)
                        entry = {"path": label, "concurrency": concurrency, "keep_alive": keep_alive,
                                 "completed": complete, "failed": failed,
                                 "non_2xx": int(non_2xx[1]) if non_2xx else 0,
                                 "requests_per_second": rps}
                        results.append(entry)
                        print(json.dumps(entry), flush=True)
                        (reports / f"ab-{label}-c{concurrency}-keep{int(keep_alive)}.txt").write_text(output)
summary = {"measured_at_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
           "cpu_count": os.cpu_count(), "compiler": subprocess.check_output(["cc", "--version"], text=True).splitlines()[0],
           "workers": args.workers, "queue": 512, "requests_per_case": args.requests,
           "notes": "Loopback WSL2 measurement; backend connection is deliberately not pooled. Not a C10K proof.",
           "results": results}
(reports / "benchmark.json").write_text(json.dumps(summary, indent=2))
