"""Generate a pending, parameter-free readiness plan; never calls AWS.

After explicit approval only approved/approval_id may change. The document hash
must stay identical. This tool does not approve, merge, upload or dispatch it.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import sys
import zlib

WHEEL_URL = 'https://files.pythonhosted.org/packages/a9/4b/0a906d8184f011ff8dbd4722743783867589b33269d2c5fff238d636fdcb/pymysql-1.2.3-py3-none-any.whl'
WHEEL = 'pymysql-1.2.3-py3-none-any.whl'
WHEEL_SHA = '14f1c68e2ed859243ae5ca41ffbe677027fc46bc136a9f0be8a4e928e5e7415a'
PLAN_NAME = 'commissioning-readiness-observed.json'
ARCHIVED_PLANS = {
    'commissioning-readiness.json': '2847d9900e342c958e7e74d4909ccbb4961685a0a9092af60e23d3c01cecec8b',
    'commissioning-readiness-tls.json': '3cf2c3dae2202f1cdf3ff50ad7a0619351c252195def6724e57783c294739b30',
    'commissioning-jdbc-option-names.json': 'f890dfb37372e737d8969d3dc225fadf8c61c0809c08a78a6927b25e3dd65f4d',
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def contract(repo):
    migrations = []
    for p in sorted((repo / 'src/main/resources/db/migration').glob('*.sql')):
        match = re.fullmatch(r'V([1-9][0-9]*)__[A-Za-z0-9_]+\.sql', p.name)
        if not match:
            raise ValueError('UNSUPPORTED_MIGRATION')
        checksum = 0
        for line in re.split(r'\r\n|\r|\n', p.read_bytes().decode('utf-8-sig')):
            checksum = zlib.crc32(line.encode(), checksum)
        migrations.append({'version': match[1], 'script': p.name,
                           'checksum': checksum if checksum < 2**31 else checksum - 2**32})
    return {'format': 1, 'migrations': migrations, 'required_columns': {
        '18': [['chat_conversations', x] for x in ('id', 'owner_id', 'client_conversation_id', 'active_turn_id')]
              + [['chat_turns', x] for x in ('id', 'conversation_id', 'client_message_id', 'context_hash', 'response_body')],
        '19': [['users', 'profile_version']],
        '20': [['account_analysis_selections', x] for x in ('owner_id', 'include_self', 'version')]
              + [['account_analysis_selection_families', x] for x in ('owner_id', 'family_profile_id')]}}


def plan(repo):
    files = {name: (repo / 'ops/operations' / name).read_text(encoding='utf-8').encode()
             for name in ('readiness_probe.py', 'readiness_paths.py')}
    files['contract.json'] = canonical(contract(repo))
    bundle = sha(canonical({k: sha(v) for k, v in files.items()}))
    stage = '/opt/jjikmuk-readiness-' + bundle[:24]
    encoded = {k: base64.b64encode(v).decode() for k, v in files.items()}
    script = '''import base64,hashlib,json,os,stat,subprocess,sys,urllib.request
from pathlib import Path
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs): return None
try:
 assert os.geteuid()==0
 p=Path(STAGE)
 for parent in p.parents:
  s=parent.lstat()
  assert not parent.is_symlink() and s.st_uid==0 and not s.st_mode & 0o022
 assert not os.path.lexists(p)
 p.mkdir(mode=0o755)
 os.chmod(p,0o755)
 for name,encoded in FILES.items():
  raw=base64.b64decode(encoded,validate=True)
  with (p/name).open('xb') as stream: stream.write(raw);stream.flush();os.fsync(stream.fileno())
  os.chmod(p/name,0o644)
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
 with opener.open(WHEEL_URL,timeout=20) as response:
  assert response.status==200 and response.geturl()==WHEEL_URL
  raw=response.read(46741)
 assert len(raw)==46740 and hashlib.sha256(raw).hexdigest()==WHEEL_SHA
 with (p/WHEEL).open('xb') as stream: stream.write(raw);stream.flush();os.fsync(stream.fileno())
 os.chmod(p/WHEEL,0o644)
 launch="import sys,runpy;sys.path.insert(0,"+repr(str(p))+");sys.argv=["+repr(str(p/'readiness_probe.py'))+",'--observe',"+repr(CONTRACT_SHA)+"];runpy.run_path(sys.argv[0],run_name='__main__')"
 result=subprocess.run(['/usr/bin/python3.12','-I','-S','-B','-c',launch],cwd='/',stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=170,env={'PATH':'/usr/bin:/bin','LANG':'C'})
 assert len(result.stdout)<=16000
 report=json.loads(result.stdout)
 assert report.get('status') in ('OK','PREFLIGHT_FAILED')
 if result.returncode: assert report.get('status')=='PREFLIGHT_FAILED'
 print(json.dumps(report))
except Exception:
 print('{"status":"PREFLIGHT_FAILED","codes":["READINESS_STAGE_STOP_KEEP_FILES_NO_RETRY"]}')
'''
    constants = {'STAGE': stage, 'FILES': encoded, 'WHEEL_URL': WHEEL_URL, 'WHEEL': WHEEL,
                 'WHEEL_SHA': WHEEL_SHA, 'CONTRACT_SHA': sha(files['contract.json'])}
    source = '\n'.join(k + '=' + repr(v) for k, v in constants.items()) + '\n' + script
    document = {'schemaVersion': '2.2', 'description': 'One approved metadata/schema observation; no deployment or SQL mutation',
                'parameters': {}, 'mainSteps': [{'action': 'aws:runShellScript', 'name': 'report', 'inputs': {
                    'timeoutSeconds': '240', 'runCommand': ["/usr/bin/python3.12 -I -S -B - <<'JJIKMUK_READINESS'\n" + source + '\nJJIKMUK_READINESS']}}]}
    if len(canonical(document)) > 60000:
        raise ValueError('DOCUMENT_LIMIT')
    return {'format': 1, 'component': 'backend', 'operation': 'inspect',
            'approval_id': 'PENDING_COMMISSIONING_OBSERVED_OPTIONS', 'approved': False, 'document': document}


def verify_archive(repo):
    # Completed/consumed commands retain their exact approved bytes, even when
    # a helper evolves for a separately reviewed future command.
    for name, expected in ARCHIVED_PLANS.items():
        original = repo / 'ops/operations/plans' / name
        if sha(original.read_bytes()) != expected:
            raise ValueError('CONSUMED_READINESS_PLAN_CHANGED')


def verify_record(record, expected):
    if type(record.get('approved')) is not bool or not re.fullmatch('[A-Z0-9][A-Z0-9_-]{7,79}', record.get('approval_id', '')):
        raise ValueError('READINESS_APPROVAL_FORMAT')
    if record['approved'] and record['approval_id'].startswith('PENDING_'):
        raise ValueError('READINESS_APPROVAL_RECORD_REQUIRED')
    normalized = dict(record, approved=False, approval_id=expected['approval_id'])
    if normalized != expected:
        raise ValueError('READINESS_PLAN_STALE')


if __name__ == '__main__':
    repo = Path(__file__).resolve().parents[2]
    verify_archive(repo)
    target = repo / 'ops/operations/plans' / PLAN_NAME
    raw = canonical(plan(repo)) + b'\n'
    if sys.argv[1:] == ['--check']:
        verify_record(json.loads(target.read_bytes()), plan(repo))
        print('READINESS_PLAN_CONTENT_VERIFIED')
    elif sys.argv[1:] == ['--write-pending']:
        target.parent.mkdir(exist_ok=True)
        with target.open('xb') as f:
            f.write(raw)
        print('PENDING_READINESS_PLAN_WRITTEN_NO_AWS_CALLS')
    else:
        raise SystemExit('Use --check or --write-pending; approval is not implemented here.')
