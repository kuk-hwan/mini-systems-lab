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
    parser.add_argument('--skip-c', action='store_true', help='Only when POSIX build tools are unavailable')
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
    if not args.skip_c:
        if os.name == 'nt':
            wsl = shutil.which('wsl')
            if not wsl:
                raise SystemExit('C checks require Linux/macOS or WSL2 Ubuntu.')
            path = subprocess.check_output([wsl, '-d', 'Ubuntu', '--exec', 'wslpath', '-a',
                                            (ROOT / 'mini-webserver').as_posix()],
                                           encoding='utf-8').strip()
            check([wsl, '-d', 'Ubuntu', '--exec', 'make', '-C', path, 'test', 'smoke'])
        else:
            check(['make', 'test', 'smoke'], ROOT / 'mini-webserver')
    print('\nPASS: requested project checks completed.', flush=True)
