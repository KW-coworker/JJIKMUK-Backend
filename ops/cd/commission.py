"""Explicit post-install baseline enrollment. Never edits systemd, IAM, or application files."""
import argparse
import json
import re
from pathlib import Path

from deploy import load_config
from host import Host, atomic_json, deployment_lock, http_check
from manifest import make_manifest, require


def commission(commit, expected_hash):
    require(re.fullmatch('[0-9a-f]{40}',commit) and re.fullmatch('[0-9a-f]{64}',expected_hash), 'INVALID_BASELINE_IDENTITY')
    config = load_config(require_baseline=False)
    root = Path(config['root'])
    with deployment_lock(root):
        require(not (root / 'baseline.json').exists(), 'BASELINE_ALREADY_EXISTS')
        folder = root / 'releases' / f'{commit}-1-1'
        manifest = make_manifest(folder / 'backend.jar', commit, '1', '1')
        require(manifest['jar_sha256'] == expected_hash, 'BOOTSTRAP_HASH_MISMATCH')
        host = Host.__new__(Host)
        host.config, host.root = config, root
        pid = int(host.unit('MainPID'))
        release = {'manifest': manifest, 'protected': host.protected(),
                   'environment_sha256':host.environment(pid,config['expected_argv'])}
        # Every program/config path is installed and reviewed before this enrollment.
        atomic_json(folder / 'manifest.json', manifest)
        host.runtime(release)
        host.database(manifest)
        for check in config['health_checks']: http_check(check)
        atomic_json(root / 'baseline.json', release)
        print(json.dumps({'status':'BASELINE_ENROLLED','jar_sha256':expected_hash}))


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--commit',required=True)
    p.add_argument('--expected-jar-sha256',required=True)
    p.add_argument('--approve-baseline-enrollment',action='store_true',required=True)
    a=p.parse_args()
    try: commission(a.commit,a.expected_jar_sha256)
    except Exception:
        print(json.dumps({'status':'BASELINE_NOT_ENROLLED_REVIEW_REQUIRED'}))
        raise SystemExit(1)
