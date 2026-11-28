"""Bring the Agent Hub engine into SPM Studio at an exact commit, with a hash check.

    python tools/vendor_agent_hub.py --from ../Agent-Hub      # copy src/agent_hub, write the pin
    python tools/vendor_agent_hub.py --check                   # verify src/agent_hub against the pin

The engine is developed in its own repository. SPM Studio ships a copy in ``src/agent_hub`` (installed as the
``agent_hub`` package next to ``spm_studio``), so installing or updating SPM Studio never needs access to that
repository. ``src/spm_studio/assistant/agent_hub.pin.json`` records the version, the commit and the SHA-256 of
the copied tree (every file path and content, sorted); the tests and the release check refuse a copy that does
not match.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'src' / 'agent_hub'
PIN = ROOT / 'src' / 'spm_studio' / 'assistant' / 'agent_hub.pin.json'
SKIP = ('__pycache__', '.pyc')


def tree_sha256(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob('*')):
        if p.is_dir() or any(s in str(p) for s in SKIP):
            continue
        rel = p.relative_to(folder).as_posix()
        h.update(rel.encode() + b'\0' + p.read_bytes() + b'\0')
    return h.hexdigest()


def vendor(source_repo: Path) -> dict:
    src = source_repo / 'src' / 'agent_hub'
    if not (src / '__init__.py').is_file():
        raise SystemExit(f'No agent_hub package in {source_repo}')
    status = subprocess.run(['git', '-C', str(source_repo), 'status', '--porcelain', '--', 'src/agent_hub'],
                            capture_output=True, text=True).stdout.strip()
    if status:
        raise SystemExit('The engine has uncommitted changes: commit them first (the pin records a commit).')
    commit = subprocess.run(['git', '-C', str(source_repo), 'rev-parse', 'HEAD'], capture_output=True, text=True,
                            check=True).stdout.strip()
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(src, TARGET, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    sys.path.insert(0, str(ROOT / 'src'))
    namespace = {}
    exec((TARGET / '__init__.py').read_text(encoding='utf8'), namespace)
    host_text = (TARGET / 'host.py').read_text(encoding='utf8')
    contract = [int(x) for x in host_text.split('CONTRACT = (', 1)[1].split(')', 1)[0].split(',')]
    pin = {'package': 'agent-hub', 'version': namespace['__version__'], 'contract': contract, 'commit': commit,
           'tree_sha256': tree_sha256(TARGET)}
    PIN.write_text(json.dumps(pin, indent=1) + '\n', encoding='utf8')
    return pin


def check() -> bool:
    pin = json.loads(PIN.read_text(encoding='utf8'))
    actual = tree_sha256(TARGET)
    if actual != pin['tree_sha256']:
        print(f'src/agent_hub does not match the pin ({actual} != {pin["tree_sha256"]})')
        return False
    print(f"src/agent_hub matches Agent Hub {pin['version']} @ {pin['commit'][:10]}")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='source', type=Path)
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args(argv)
    if args.source:
        print(json.dumps(vendor(args.source.resolve()), indent=1))
    return 0 if check() else 1


if __name__ == '__main__':
    sys.exit(main())
