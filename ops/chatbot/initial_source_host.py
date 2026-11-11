"""Exact original chatbot source switch. Preserve venv, RAG, environment and DB."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time

COMMIT = '3d0be58e601281d22aef8e08a20e6d9642a48f36'
ARCHIVE = '6ec58d3c1960c7c22025cbbab6e79744123f6c42b15f99518b1cafab8c45fdc1'
OLD = Path('/opt/jjikmuk-github/releases/20261102-v2-gitbytes/AI')
RELEASE = Path('/opt/jjikmuk-chatbot/releases/' + COMMIT + '-43058384792-1')
DROP = Path('/etc/systemd/system/food-chatbot-team.service.d/zzzzzzzz-chatbot-source-20261112.conf')
PYTHON = '/opt/food-chatbot/venv-github-v2-20261102/bin/python'
SERVICE = 'food-chatbot-team.service'
SECURITY = ('User', 'Group', 'ProtectSystem', 'ProtectHome', 'PrivateTmp', 'NoNewPrivileges',
            'ReadWritePaths', 'ReadOnlyPaths', 'IPAddressAllow', 'IPAddressDeny',
            'RestrictAddressFamilies', 'CapabilityBoundingSet', 'MemoryMax', 'MemoryHigh')
DYNAMIC = {'INVOCATION_ID', 'JOURNAL_STREAM', 'SYSTEMD_EXEC_PID', 'NOTIFY_SOCKET', 'WATCHDOG_PID', 'WATCHDOG_USEC'}


def need(ok, code):
    if not ok:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run(args, timeout=30, **kwargs):
    result = subprocess.run(args, capture_output=True, timeout=timeout, **kwargs)
    need(result.returncode == 0, 'CHATBOT_COMMAND_FAILED')
    return result.stdout.decode().strip()


def unit(field):
    return run(['/usr/bin/systemctl', 'show', SERVICE, '--property=' + field, '--value'], 5)


def snapshot():
    from host import secure, digest
    need(unit('ActiveState') == 'active' and unit('User') == 'food-chatbot', 'CHATBOT_SERVICE_IDENTITY')
    pid = unit('MainPID'); need(re.fullmatch('[1-9][0-9]{0,8}', pid), 'CHATBOT_PID')
    need(Path('/proc/' + pid).stat().st_uid == 999, 'CHATBOT_UID')
    args = Path('/proc/' + pid + '/cmdline').read_bytes()
    need(sha(args) == '193ecdfe138824f4fad5567a6ad366c505bfa5773d4995322bd8a5265cc92b02', 'CHATBOT_ARGUMENTS_CHANGED')
    values = dict(p.decode().split('=', 1) for p in Path('/proc/' + pid + '/environ').read_bytes().split(b'\0') if p)
    refs = unit('EnvironmentFiles'); pattern = r'(/[^\s]+) \(ignore_errors=(?:yes|no)\)'
    need(not re.sub(pattern, '', refs).strip(), 'CHATBOT_REFERENCE_SYNTAX')
    files = re.findall(pattern, refs) + [unit('FragmentPath')] + unit('DropInPaths').split()
    fingerprints = {}
    for name in files:
        path = Path(name); secure(path); fingerprints[name] = digest(path)
    security = {key: unit(key) for key in SECURITY}
    for key in ('IPAddressAllow', 'IPAddressDeny'):
        security[key] = ' '.join(sorted(security[key].split()))
    return {'identity': unit('InvocationID'), 'pid': pid, 'cwd': str(Path('/proc/' + pid + '/cwd').resolve()),
            'environment_sha256': sha(json.dumps({k: v for k, v in values.items() if k not in DYNAMIC}, sort_keys=True).encode()),
            'references': fingerprints, 'security': security}, values


def old_source_hash():
    files = sorted((OLD / 'app').rglob('*.py'))
    need(len(files) == 104 and not (OLD / '.env').exists(), 'CHATBOT_OLD_SOURCE_MEMBERS')
    rows = [[p.relative_to(OLD).as_posix(), sha(p.read_bytes())] for p in files]
    return sha(json.dumps(rows, separators=(',', ':')).encode())


def verify_source(folder, manifest):
    from host import secure
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    need(actual == set(manifest['files']), 'CHATBOT_SOURCE_MEMBERS_CHANGED')
    for name, record in manifest['files'].items():
        path = folder / name; secure(path)
        need(path.stat().st_size == record['bytes'] and sha(path.read_bytes()) == record['sha256'], 'CHATBOT_SOURCE_CHANGED')


def same_runtime(before, after, folder, drop_hash=None):
    expected = dict(before['references'])
    if drop_hash:
        expected[str(DROP)] = drop_hash
    need(after['cwd'] == str(folder) and after['environment_sha256'] == before['environment_sha256']
         and after['security'] == before['security'] and after['references'] == expected, 'CHATBOT_RUNTIME_DRIFT')


def candidate_accepted(report, returncode):
    required = {'dependencies_match', 'existing_rag_current', 'candidate_ready', 'deployment_boundary_valid',
                'product_repository_available', 'activity_repository_available', 'conversation_repository_available'}
    return (returncode == 0 and report.get('status') == 'OK' and set(report.get('checks', {})) == required
            and all(v is True for v in report['checks'].values()))


def stable(before, folder, backend, backend_identity, drop_hash=None):
    from host import http_check
    deadline = time.monotonic() + 240
    healthy_since = None; seen = None
    while time.monotonic() < deadline:
        try:
            current, _ = snapshot()
            need(current['identity'] != before['identity'], 'CHATBOT_OLD_PROCESS')
            same_runtime(before, current, folder, drop_hash)
            if current['identity'] != seen:
                healthy_since = None; seen = current['identity']
            backend.runtime(backend.baseline)
            need(backend.identity() == backend_identity, 'BACKEND_RESTARTED_DURING_CHATBOT_SWITCH')
            for check in backend.config['health_checks']:
                http_check(check)
            need(backend.identity() == backend_identity, 'BACKEND_RESTARTED_DURING_CHATBOT_SWITCH')
            if healthy_since is None:
                healthy_since = time.monotonic()
            if time.monotonic() - healthy_since >= 60:
                return current
        except Exception:
            healthy_since = None
        time.sleep(5)
    raise ValueError('CHATBOT_STABILITY_TIMEOUT')


def execute(payload, operation):
    from host import Host, secure, atomic_json
    from deploy import load_config
    from package import unpack
    need(os.geteuid() == 0 and sys.flags.isolated and sys.flags.no_site, 'CHATBOT_ROOT_RUNTIME')
    need(re.fullmatch('[a-f0-9]{64}', operation), 'CHATBOT_OPERATION_ID')
    backend = Host(load_config()); backend.runtime(backend.baseline); backend.database(backend.baseline['manifest'])
    backend_identity = backend.identity()
    need(bool(backend_identity) and any(c['url'] == 'http://127.0.0.1:8000/ready' and c['status'] == 200
                                      for c in backend.config['health_checks']), 'CHATBOT_HEALTH_CHECK_REQUIRED')
    before, environment = snapshot()
    need(before['cwd'] == str(OLD) and not (OLD / '.env').exists(), 'CHATBOT_OLD_SOURCE_OR_DOTENV_CHANGED')
    need(old_source_hash() == 'c88c2314467b31b3147bf9ea419bf765d7b516aad6fb4a0ded22a78ce01e82b6', 'CHATBOT_OLD_SOURCE_CHANGED')
    need(environment.get('CHROMA_DB_DIR') == '/var/lib/food-chatbot/integration-20261015/chroma-github-v2-20261102'
         and environment.get('RAG_DOCS_DIR') == str(OLD.parent / 'rag-official-three'), 'CHATBOT_RAG_CONFIGURATION_CHANGED')
    need(sha((OLD / 'requirements.txt').read_bytes()) == 'ee06144a3a52919d3629d9f713a6908390e9be5d09f2dd05c8500f832e297f91', 'CHATBOT_REQUIREMENTS_CHANGED')
    need(not DROP.exists() and not DROP.is_symlink() and not RELEASE.exists(), 'CHATBOT_SOURCE_ALREADY_PREPARED_NO_REPLAY')
    need(all(Path(path).name < DROP.name for path in unit('DropInPaths').split()), 'CHATBOT_DROPIN_PRECEDENCE')
    secure(DROP.parent); need(shutil.disk_usage('/opt').free > 3*1024**3, 'CHATBOT_DISK_RESERVE')
    manifest = json.loads((payload / 'manifest.json').read_bytes())
    need(manifest['commit'] == COMMIT and manifest['run_id'] == '43058384792'
         and manifest['archive_sha256'] == ARCHIVE, 'CHATBOT_CANDIDATE_IDENTITY')
    for directory in (RELEASE.parent.parent, RELEASE.parent, RELEASE):
        if not directory.exists():
            directory.mkdir(mode=0o755)
        secure(directory)
    unpack(payload / 'chatbot.zip', manifest, RELEASE / 'AI')
    for path in (RELEASE / 'AI').rglob('*'):
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    verify_source(RELEASE / 'AI', manifest)
    probe = RELEASE / 'source-probe.py'
    with probe.open('xb') as f:
        f.write((payload / 'initial_source_probe.py').read_bytes())
    os.chmod(probe, 0o644)
    atomic_json(payload / 'before.json', before)
    addresses = sorted({info[4][0] for info in socket.getaddrinfo(
        'jjikmuk-dev-db.cp22o82i4ex5.ap-northeast-2.rds.amazonaws.com', 3306, socket.AF_INET, socket.SOCK_STREAM)})
    data = json.dumps({'source': str(RELEASE / 'AI'), 'environment': environment, 'database_addresses': addresses}).encode()
    args = ['/usr/bin/systemd-run', '--unit=jjikmuk-chatbot-probe-' + operation[:16], '--quiet', '--pipe', '--wait', '--collect',
            '--property=User=food-chatbot', '--property=Group=food-chatbot', '--property=ProtectSystem=strict',
            '--property=ProtectHome=true', '--property=PrivateTmp=true', '--property=NoNewPrivileges=true',
            '--property=RuntimeMaxSec=180', '--property=MemoryMax=512M',
            '--property=WorkingDirectory=' + str(RELEASE / 'AI'), PYTHON, '-I', '-B', str(probe)]
    result = subprocess.run(args, input=data, capture_output=True, timeout=210)
    with (payload / 'candidate-private-stderr.log').open('xb') as f:
        os.chmod(f.name, 0o600); f.write(result.stderr)
    need(len(result.stdout) < 16384, 'CHATBOT_PROBE_OUTPUT_LIMIT')
    candidate = json.loads(result.stdout)
    atomic_json(payload / 'candidate-report.json', candidate)
    now, _ = snapshot(); need(now == before, 'CHATBOT_CHANGED_DURING_PREPARATION')
    backend.runtime(backend.baseline)
    need(backend.identity() == backend_identity, 'BACKEND_RESTARTED_DURING_PREPARATION')
    if not candidate_accepted(candidate, result.returncode):
        return dict(candidate, status='PREFLIGHT_FAILED')
    return switch_source(payload, before, backend, backend_identity, manifest, candidate.get('counts', {}))


def switch_source(payload, before, backend, backend_identity, manifest, counts):
    from host import atomic_json
    body = ('[Service]\nWorkingDirectory=' + str(RELEASE / 'AI') + '\n').encode()
    drop_hash = sha(body)
    atomic_json(payload / 'switch-intent.json', {'before': before, 'drop_sha256': drop_hash, 'commit': COMMIT})
    switched = False
    try:
        with DROP.open('xb') as f:
            os.chmod(f.name, 0o644); f.write(body); f.flush(); os.fsync(f.fileno())
        switched = True
        run(['/usr/bin/systemctl', 'daemon-reload'])
        # The intent above covers ambiguous restart responses as well as success.
        run(['/usr/bin/systemctl', 'restart', SERVICE], 90)
        after = stable(before, RELEASE / 'AI', backend, backend_identity, drop_hash)
        verify_source(RELEASE / 'AI', manifest)
        need(old_source_hash() == 'c88c2314467b31b3147bf9ea419bf765d7b516aad6fb4a0ded22a78ce01e82b6', 'CHATBOT_OLD_SOURCE_CHANGED')
        atomic_json(payload / 'after.json', after)
        return {'status': 'SUCCEEDED', 'checks': {'github_source_exact': True, 'existing_environment_preserved': True,
                'existing_venv_and_rag_retained': True, 'backend_not_restarted': True, 'stable_health_60_seconds': True},
                'hashes': {'chatbot_commit_sha256': sha(COMMIT.encode())}, 'counts': counts}
    except BaseException:
        # Only the file owned by this attempt may be removed. Existing settings
        # and all data are retained. An unconfirmed rollback remains unresolved.
        atomic_json(payload / 'rollback-intent.json', {'switch_file_created': switched})
        need(DROP.is_file() and not DROP.is_symlink() and sha(DROP.read_bytes()) == drop_hash, 'CHATBOT_ROLLBACK_DROP_DRIFT')
        rollback_identity = unit('InvocationID')
        DROP.unlink()
        run(['/usr/bin/systemctl', 'daemon-reload'])
        run(['/usr/bin/systemctl', 'restart', SERVICE], 90)
        stable(dict(before, identity=rollback_identity), OLD, backend, backend_identity)
        return {'status': 'ROLLED_BACK', 'checks': {'old_chatbot_restored': True, 'backend_unchanged': True},
                'codes': ['CHATBOT_NEW_SOURCE_FAILED_OLD_SERVICE_VERIFIED']}


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    payload = Path(__file__).resolve().parent
    sys.path[:0] = [str(payload), '/opt/jjikmuk-cd/bin']
    try:
        report = execute(payload, os.environ['JJIKMUK_OPERATION_ID'])
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{0,79}', str(error)) else type(error).__name__.upper()
        report = {'status': 'MANUAL_RECOVERY_REQUIRED' if (payload / 'switch-intent.json').exists() else 'PREFLIGHT_FAILED', 'codes': [code]}
    from host import atomic_json
    atomic_json(payload / 'transition-result.json', report)
