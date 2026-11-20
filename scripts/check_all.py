"""Run independent project checks from one place, without mixing Python modules."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def check(command, directory=ROOT):
    print(f'\n[{directory.name}] {" ".join(map(str, command))}', flush=True)
    subprocess.run(command, cwd=directory, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--e2e', action='store_true', help='Also run installed Playwright Chromium')
    args = parser.parse_args()
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    if not npm:
        raise SystemExit('Install Node.js 24 and npm first; run npm ci in mini-react-fiber-lab.')
    check([sys.executable, 'scripts/verify_history.py', '--fsck'])
    check([npm, 'run', 'check'], ROOT / 'mini-react-fiber-lab')
    if args.e2e:
        check([npm, 'run', 'test:e2e'], ROOT / 'mini-react-fiber-lab')
    check([sys.executable, '-m', 'unittest', 'discover', '-s', '.'], ROOT / 'mini-redis')
    check([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], ROOT / 'mini-dbms')
    print('\nPASS: requested project checks completed.', flush=True)
