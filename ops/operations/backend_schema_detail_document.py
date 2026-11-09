"""New fixed read-only document, reusing only the verified existing probe stage."""
import base64
import json
from pathlib import Path
import sys

from readiness_document import canonical, sha, contract

PLAN_NAME = 'backend-schema-detail.json'
STAGE = '/opt/jjikmuk-readiness-15c9d87c15808f1935637382'


def plan(repo):
    root = repo / 'ops/operations'
    sources = {name: (root / (name + '.py')).read_bytes() for name in
               ('readiness_paths', 'readiness_probe', 'backend_schema_detail')}
    hashes = {name: sha(raw) for name, raw in sources.items()}
    # Only the wheel is reused from the prior successful observation. Helpers
    # execute from hash-checked memory, not mutable application import paths.
    encoded = {name: base64.b64encode(raw).decode() for name, raw in sources.items()}
    loader = 'SOURCES=' + repr(encoded) + '\nHASHES=' + repr(hashes) + '''
import base64,hashlib,json,sys,types,os
from pathlib import Path
assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
for name in ('readiness_paths','readiness_probe','backend_schema_detail'):
 raw=base64.b64decode(SOURCES[name],validate=True)
 assert hashlib.sha256(raw).hexdigest()==HASHES[name]
 module=types.ModuleType(name);sys.modules[name]=module
 exec(compile(raw,'<reviewed-'+name+'>','exec'),module.__dict__)
probe=sys.modules['readiness_probe']
detail=sys.modules['backend_schema_detail']
'''
    child_tail = '\nCONTRACT=' + repr(contract(repo)) + '\nSTAGE=' + repr(STAGE) + '''
import pwd
assert os.geteuid()==pwd.getpwnam('ubuntu').pw_uid!=0
inputs=probe.database_inputs()
probe.trusted_ca();probe.load_pinned_vendor(Path(STAGE))
import pymysql
report=detail.query(pymysql.connect,inputs[4],CONTRACT)
probe.unchanged(inputs)
print(json.dumps(report))
'''
    parent = 'LOADER=' + repr(loader) + '\nexec(LOADER)\nCHILD=LOADER+' + repr(child_tail) + '''
import subprocess
try:
 assert os.geteuid()==0 and probe.jar_digest()==probe.JAR_SHA
 inputs=probe.database_inputs()
 result=subprocess.run(['/usr/sbin/runuser','-u','ubuntu','--','/usr/bin/python3.12','-I','-S','-B','-'],
  input=CHILD.encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=65,cwd='/',
  env={'PATH':'/usr/bin:/bin','LANG':'C'})
 assert result.returncode==0 and len(result.stdout)<=12000
 report=json.loads(result.stdout)
 probe.unchanged(inputs)
 assert probe.jar_digest()==probe.JAR_SHA
 report['checks']['observation_stable']=True
 print(json.dumps(report))
except Exception:
 print('{"status":"PREFLIGHT_FAILED","codes":["SCHEMA_DETAIL_FAILED_NO_RETRY"]}')
'''
    doc = {'schemaVersion': '2.2', 'description': 'Backend migration metadata only; one TLS read-only DB connection; no application or DB mutation',
           'parameters': {}, 'mainSteps': [{'action': 'aws:runShellScript', 'name': 'report', 'inputs': {
               'timeoutSeconds': '120', 'runCommand': ["/usr/bin/python3.12 -I -S -B - <<'JJIKMUK_SCHEMA_DETAIL'\n" + parent + '\nJJIKMUK_SCHEMA_DETAIL']}}]}
    if len(canonical(doc)) > 60000:
        raise ValueError('DOCUMENT_LIMIT')
    return {'format': 1, 'component': 'backend', 'operation': 'inspect',
            'approval_id': 'USER_BACKEND_CD_COMPLETION_20261110', 'approved': True, 'document': doc}


if __name__ == '__main__':
    repo = Path(__file__).resolve().parents[2]
    raw = canonical(plan(repo)) + b'\n'
    target = repo / 'ops/operations/plans' / PLAN_NAME
    if sys.argv[1:] == ['--write-approved']:
        with target.open('xb') as out: out.write(raw)
        print('APPROVED_SCHEMA_METADATA_PLAN_WRITTEN_NO_AWS')
    elif sys.argv[1:] == ['--check']:
        if target.read_bytes() != raw: raise ValueError('SCHEMA_PLAN_CHANGED')
        print('SCHEMA_DETAIL_PLAN_VERIFIED')
    else:
        raise SystemExit('Use --check or --write-approved; no dispatch here.')
