"""Fixed SSM entry point; no general-purpose command or path parameters."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

# The installed bin directory is fingerprinted as immutable deployment input.
# Set before sibling imports, including database_probe's first lazy import.
sys.dont_write_bytecode = True

from engine import deploy
from host import Host, deployment_lock, secure
from manifest import require, read_json


def request_from_environment(env):
    fields = {'commit': ('ReleaseCommit', r'[0-9a-f]{40}'),
              'run_id': ('RunId', r'[1-9][0-9]{0,19}'),
              'attempt': ('RunAttempt', r'[1-9][0-9]{0,3}'),
              'jar_sha256': ('JarSha256', r'[0-9a-f]{64}'),
              'jar_version': ('JarVersion', r'[A-Za-z0-9._~+/-]{1,1024}'),
              'manifest_version': ('ManifestVersion', r'[A-Za-z0-9._~+/-]{1,1024}')}
    result = {}
    for key, (name, pattern) in fields.items():
        value = env.get('SSM_' + name, '')
        require(re.fullmatch(pattern, value) is not None and value != 'null', 'INVALID_SSM_PARAMETER')
        result[key] = value
    result['run_key'] = result['run_id'] + '-' + result['attempt']
    return result


def load_config(require_baseline=True, require_enabled=True):
    require(os.name == 'posix' and os.geteuid() == 0, 'ROOT_LINUX_REQUIRED')
    path = Path('/etc/jjikmuk-cd/config.json')
    secure(path)
    for source in Path(__file__).parent.glob('*.py'): secure(source)
    c = read_json(path)
    require(c['enabled'] is require_enabled and c['root'] == '/opt/jjikmuk-cd' and
            c['service'] == 'jjikmuk-backend.service' and c['region'] == 'ap-northeast-2', 'NOT_COMMISSIONED')
    require(str(path) in c['protected_paths'] and '/etc/systemd/system/jjikmuk-backend.service.d' in c['protected_paths'], 'PROTECTION_INCOMPLETE')
    require(all(p in c['protected_paths'] for p in ['/opt/jjikmuk-cd/bin', '/opt/jjikmuk-cd/vendor',
                                                  '/opt/jjikmuk-cd/tools', c['database']['properties_file'],
                                                  c['database']['ca_file']]), 'PROTECTION_INCOMPLETE')
    require({x['kind'] for x in c['health_checks']} >= {'local','public','product','ocr','chatbot','anonymous'}, 'HEALTH_CHECKS_INCOMPLETE')
    if require_baseline: secure(Path(c['root']) / 'baseline.json')
    return c


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['deploy', 'status'])
    args = parser.parse_args()
    c = load_config()
    request = request_from_environment(os.environ) if args.mode == 'deploy' else None
    operation_id = hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest() if request else uuid.uuid4().hex*2
    with deployment_lock(c['root'], operation_id) as guard:
        host = Host(c)
        host.coordinator = guard
        if args.mode == 'status':
            host.runtime(host.baseline)
            guard.record('VERIFIED')
            print(json.dumps({'status': 'CURRENT_VERIFIED', 'commit': host.baseline['manifest']['commit']}))
            return
        result = deploy(host, request)
        if guard.status == 'PREPARING': guard.record(result['status'])
        print(json.dumps({'status': result['status']}))
        if result['status'] != 'SUCCEEDED': raise SystemExit(1)


if __name__ == '__main__':
    try: main()
    except Exception:
        # Neither AWS output nor local exceptions may reveal configuration/credentials.
        print(json.dumps({'status': 'STOP_REVIEW_REQUIRED'}))
        raise SystemExit(1)
