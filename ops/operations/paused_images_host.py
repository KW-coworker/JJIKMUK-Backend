"""Fixed closeout observation: no image writes, service restart or paid AI calls."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys


def require(ok, code):
    if not ok:
        raise ValueError(code)


def paused_boundary(payload):
    """Read only terminal receipts; an incomplete next slice blocks CD release."""
    counts = {'checked_rows': 0, 'changed_rows': 0}
    proofs = []
    folders = sorted((payload / 'slices').iterdir())
    require([p.name for p in folders] == [f'{n:03d}' for n in range(13)], 'PAUSED_SLICE_BOUNDARY_CHANGED')
    spec = json.loads(read(payload / 'input.json', 65536))
    require(spec['input_sha256'] == 'c702663c6375447b0847334dc9d1707cf5383165622ca3a8cdb350838c322cdd'
            and spec['rows'] == 1098863, 'PAUSED_INPUT_CHANGED')
    for index, folder in enumerate(folders):
        result = json.loads(read(folder / 'result.json', 4096))
        request = {'seed_operation': SEED,
                   'package_sha256': '9e41ee6fcdacf6d95ef92d6d4c71ab0a696ecc8fa9776e8b9663fb4712f3a034',
                   'index': index, 'input_sha256': spec['input_sha256']}
        expected = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        require(result['status'] == 'VERIFIED' and result['operation_id'] == expected
                and result['checks'] and all(v is True for v in result['checks'].values()), 'PAUSED_SLICE_UNVERIFIED')
        c = result['counts']; s = spec['slices'][index]
        require(c['checked'] == s['count'] and c['last_id'] == s['last_id']
                and 0 <= c['changed'] <= c['checked'], 'PAUSED_SLICE_COUNTS')
        counts['checked_rows'] += c['checked']; counts['changed_rows'] += c['changed']
        proofs.append(result)
    require(counts == {'checked_rows': 241000, 'changed_rows': 236207}
            and proofs[-1]['counts']['last_id'] == 328344, 'PAUSED_TOTAL_CHANGED')
    return counts, hashlib.sha256(json.dumps(proofs, sort_keys=True).encode()).hexdigest()


def read(path, limit):
    from host import secure
    secure(path)
    require(path.is_file() and path.stat().st_size <= limit, 'CLOSEOUT_FILE_LIMIT')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'CLOSEOUT_READ_LIMIT')
    return raw


def chatbot_observation(report, host):
    def unit(field):
        result = subprocess.run(['/usr/bin/systemctl', 'show', 'food-chatbot-team.service',
                                 '--property=' + field, '--value'], capture_output=True, timeout=5)
        require(result.returncode == 0 and len(result.stdout) < 16384, 'CHATBOT_UNIT_QUERY')
        return result.stdout.decode().strip()
    pid = unit('MainPID'); require(re.fullmatch('[1-9][0-9]{0,8}', pid), 'CHATBOT_PID')
    identity = unit('InvocationID')
    work = Path(unit('WorkingDirectory'))
    require(str(work).startswith(('/opt/jjikmuk-github/releases/', '/opt/food-chatbot/releases/',
                                 '/opt/jjikmuk-chatbot/releases/')), 'CHATBOT_SOURCE_ROOT')
    paths = report['paths']
    paths['chatbot.working_directory'] = str(work)
    paths['chatbot.fragment'] = unit('FragmentPath')
    refs = unit('EnvironmentFiles')
    pattern = r'(/[^\s]+) \(ignore_errors=(?:yes|no)\)'
    require(not re.sub(pattern, '', refs).strip(), 'CHATBOT_ENV_REFERENCE')
    for kind, values in [('env', re.findall(pattern, refs)), ('dropin', unit('DropInPaths').split())]:
        require(len(values) <= 20, 'CHATBOT_REFERENCE_LIMIT')
        for i, value in enumerate(values):
            paths['chatbot.' + kind + '_' + str(i)] = value
    raw_args = Path('/proc/' + pid + '/cmdline').read_bytes()
    require(len(raw_args) < 16384, 'CHATBOT_ARGV_LIMIT')
    executable = raw_args.split(b'\0')[0].decode()
    paths['chatbot.executable'] = executable
    paths['chatbot.executable_resolved'] = str(Path(executable).resolve(strict=True))
    report['hashes']['chatbot_argv'] = hashlib.sha256(raw_args).hexdigest()
    report['hashes']['chatbot_requirements'] = hashlib.sha256(read(work / 'requirements.txt', 65536)).hexdigest()
    sources = []
    for path in sorted((work / 'app').rglob('*.py')):
        require(len(sources) < 2000, 'CHATBOT_SOURCE_LIMIT')
        sources.append([path.relative_to(work).as_posix(), hashlib.sha256(read(path, 2*1024**2)).hexdigest()])
    report['hashes']['chatbot_python_sources'] = hashlib.sha256(json.dumps(sources, separators=(',', ':')).encode()).hexdigest()
    report['counts']['chatbot_python_files'] = len(sources)
    raw_env = Path('/proc/' + pid + '/environ').read_bytes()
    require(len(raw_env) < 131072, 'CHATBOT_ENV_LIMIT')
    env = dict(part.decode().split('=', 1) for part in raw_env.split(b'\0') if part)
    dotenv = work / '.env'
    report['counts']['chatbot_dotenv_present'] = int(dotenv.exists())
    # Read only two path keys; never execute dotenv or output any other value.
    unresolved = False
    if dotenv.exists():
        paths['chatbot.dotenv'] = str(dotenv)
        for line in read(dotenv, 65536).decode().splitlines():
            match = re.fullmatch(r'\s*(?:export\s+)?(CHROMA_DB_DIR|RAG_DOCS_DIR)\s*=\s*(.*?)\s*', line)
            if not match or match[1] in env:
                continue
            value = match[2]
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '\"\'':
                value = value[1:-1]
            if not re.fullmatch(r'/[A-Za-z0-9_.@+/-]{1,239}', value):
                unresolved = True
            else:
                env[match[1]] = value
    for key, name, default in [('CHROMA_DB_DIR', 'rag_index', work / 'app/chroma_db'),
                                ('RAG_DOCS_DIR', 'rag_docs', work / 'app/knowledge')]:
        value = Path(env.get(key, str(default)))
        if not re.fullmatch(r'/[A-Za-z0-9_.@+/-]{1,239}', str(value)):
            unresolved = True; continue
        paths['chatbot.' + name] = str(value)
        report['counts']['chatbot_' + name + '_present'] = int(value.is_dir())
        report['counts']['backend_protects_' + name] = int(str(value) in host.config['protected_paths'])
    report['counts']['chatbot_rag_paths_resolved'] = int(not unresolved)
    report['counts']['chatbot_cd_config_present'] = int(Path('/etc/jjikmuk-chatbot-cd/config.json').exists())
    report['counts']['chatbot_cd_baseline_present'] = int(Path('/opt/jjikmuk-chatbot/baseline.json').exists())
    report['counts']['host_free_bytes'] = shutil.disk_usage('/').free
    require(unit('ActiveState') == 'active' and unit('User') == 'ubuntu'
            and unit('InvocationID') == identity and unit('MainPID') == pid, 'CHATBOT_CHANGED_DURING_READ')


def main():
    signal.alarm(390)
    require(os.geteuid() == 0 and sys.flags.isolated and sys.flags.no_site, 'CLOSEOUT_RUNTIME')
    sys.dont_write_bytecode = True
    sys.path.insert(0, '/opt/jjikmuk-cd/bin')
    from host import secure, Host
    from deploy import load_config
    from coordination import ROOT, locked
    secure(Path('/opt/jjikmuk-cd/bin'))
    with locked('backend', OPERATION) as guard:
        counts, proof = paused_boundary(ROOT / ('private-' + SEED) / 'payload')
        host = Host(load_config())
        host.verify(host.baseline, '')
        report = {'status': 'VERIFIED', 'checks': {'image_work_paused': True,
                  'completed_slices_verified': True, 'backend_database_and_health_verified': True,
                  'no_service_change': True}, 'counts': counts, 'paths': {},
                  'hashes': {'paused_results_sha256': proof,
                    'backend_commit_sha256': hashlib.sha256(host.baseline['manifest']['commit'].encode()).hexdigest()}}
        chatbot_observation(report, host)
        guard.record('VERIFIED')
        print(json.dumps(report))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{0,79}', str(error)) else type(error).__name__.upper()
        print(json.dumps({'status': 'STOPPED', 'codes': [code]}))
        raise SystemExit(1)
