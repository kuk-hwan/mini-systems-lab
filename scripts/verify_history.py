"""Verify original refs and commits without rewriting or fetching source repos."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def local_ref(ref):
    candidates = [ref]
    if ref.startswith('refs/heads/'):
        candidates.append('refs/remotes/origin/' + ref.removeprefix('refs/heads/'))
    for candidate in candidates:
        result = subprocess.run(['git', 'rev-parse', '--verify', candidate], cwd=ROOT,
                                text=True, capture_output=True)
        if result.returncode == 0:
            return result.stdout.strip()
    raise AssertionError(f'Missing ref {ref}; fetch all remote branches first')


def verify(remote=None, fsck=False):
    manifest = json.loads((ROOT / 'docs/import-manifest.json').read_text(encoding='utf-8'))
    main_sha = local_ref('refs/heads/main')
    reachable = set(git('rev-list', main_sha).splitlines())
    original = set()
    ref_count = 0
    by_project = []
    remote_refs = {}
    if remote:
        for line in git('ls-remote', '--refs', remote).splitlines():
            sha, ref = line.split()
            remote_refs[ref] = sha
    for source in manifest['sources']:
        commits = set(source['commits'])
        original.update(commits)
        missing = commits - reachable
        if missing:
            raise AssertionError(f"Missing commits for {source['repository']}: {sorted(missing)}")
        for ref in source['refs']:
            actual = local_ref(ref['destination_ref'])
            if actual != ref['sha']:
                raise AssertionError(f"Changed original ref: {ref['destination_ref']}")
            if remote and remote_refs.get(ref['destination_ref']) != ref['sha']:
                raise AssertionError(f"Remote ref mismatch: {ref['destination_ref']}")
            ref_count += 1
        by_project.append({'repository': source['repository'], 'commits': len(commits),
                           'refs': len(source['refs']), 'all_original_shas_preserved': True})
    if remote and remote_refs.get('refs/heads/main') != main_sha:
        raise AssertionError('Remote main does not match local main')
    if fsck:
        git('fsck', '--full')
    return {'source_repositories': len(by_project), 'source_refs_preserved': ref_count,
            'unique_source_commits_preserved': len(original),
            'all_original_commits_reachable_from_main': True,
            'remote_verified': bool(remote), 'git_fsck_passed': fsck,
            'projects': by_project}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--remote', help='Also compare every archived ref and main on this remote')
    parser.add_argument('--fsck', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.remote, args.fsck)
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
