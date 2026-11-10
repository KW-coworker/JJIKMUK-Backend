"""Build one fixed initial-runtime observation, with no raw configuration output."""
import base64
import json
from pathlib import Path
import sys
import zlib

from connection import canonical, sha


def plan(repo):
    sources = {}
    for directory, names in [('cd', ('manifest', 'database_probe', 'runtime_contract', 'host', 'initial_contract')),
                             ('operations', ('readiness_paths', 'readiness_probe', 'backend_initial_observe'))]:
        for name in names:
            sources[name] = (repo / 'ops' / directory / (name + '.py')).read_text(encoding='utf-8')
    # The candidate's source configuration is compared without building or installing it.
    sys.path.insert(0, str(repo / 'ops/cd'))
    from manifest import checksum
    migrations = []
    for path in sorted((repo / 'src/main/resources/db/migration').glob('V*__*.sql')):
        raw = path.read_bytes()
        migrations.append({'version': path.name.split('__')[0][1:], 'script': path.name,
                           'sha256': sha(raw), 'checksum': checksum(raw)})
    configuration = {}
    # Same normalization as manifest.content_profile, verified by a fixture test.
    for path in sorted((repo / 'src/main/resources').rglob('*')):
        if path.suffix not in ('.properties', '.yaml', '.yml'):
            continue
        raw = path.read_bytes()
        if path.name == 'application.properties':
            raw = b'\n'.join(line for line in raw.splitlines()
                if line.strip() and not line.lstrip().startswith(b'#') and
                line != b'chatbot.developer-test-auto-consent=${CHATBOT_DEVELOPER_TEST_AUTO_CONSENT:false}')
        configuration['BOOT-INF/classes/' + path.relative_to(repo / 'src/main/resources').as_posix()] = sha(raw)
    data = canonical({'sources': sources, 'expected': {'migrations': migrations, 'configuration': configuration}})
    packed = base64.b64encode(zlib.compress(data, 9)).decode()
    code = '''import base64,hashlib,json,os,sys,types,zlib
try:
 assert os.geteuid()==0 and sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
 raw=zlib.decompress(base64.b64decode(PACKED,validate=True))
 assert len(raw)<200000 and hashlib.sha256(raw).hexdigest()==EXPECTED
 data=json.loads(raw)
 for name in ('manifest','database_probe','runtime_contract','host','initial_contract','readiness_paths','readiness_probe','backend_initial_observe'):
  module=types.ModuleType(name);module.__file__='<reviewed-'+name+'>';sys.modules[name]=module
  exec(compile(data['sources'][name],module.__file__,'exec'),module.__dict__)
 print(json.dumps(sys.modules['backend_initial_observe'].observe(data['expected'])))
except Exception as error:
 code=str(error) if type(error).__name__ in ('ValueError','ProbeStop') else type(error).__name__.upper()
 import re
 if not re.fullmatch('[A-Z][A-Z0-9_]{0,79}',code):code='INITIAL_OBSERVATION_FAILED'
 print(json.dumps({'status':'PREFLIGHT_FAILED','codes':[code]}))
'''
    script = 'PACKED=' + repr(packed) + '\nEXPECTED=' + repr(sha(data)) + '\n' + code
    doc = {'schemaVersion': '2.2', 'parameters': {}, 'description': 'Fixed initial backend runtime and free health observation; no SQL or application mutation',
           'mainSteps': [{'name': 'report', 'action': 'aws:runShellScript', 'inputs': {
               'timeoutSeconds': '120', 'runCommand': ["/usr/bin/python3.12 -I -S -B - <<'INITIAL_OBSERVATION'\n" + script + '\nINITIAL_OBSERVATION']}}]}
    return {'format': 1, 'component': 'backend', 'operation': 'inspect',
            'approved': True, 'approval_id': 'USER_SCHEMA_AND_CD_COMPLETION_20261110', 'document': doc}


if __name__ == '__main__':
    repo = Path(__file__).resolve().parents[2]
    raw = canonical(plan(repo)) + b'\n'
    target = repo / 'ops/operations/plans/backend-initial-observation.json'
    if sys.argv[1:] == ['--write']:
        with target.open('xb') as out:
            out.write(raw)
    elif sys.argv[1:] == ['--check']:
        if target.read_bytes() != raw:
            raise ValueError('INITIAL_OBSERVATION_CHANGED')
    else:
        raise SystemExit('Use --write or --check')
    print('INITIAL_OBSERVATION_PLAN_VERIFIED')
