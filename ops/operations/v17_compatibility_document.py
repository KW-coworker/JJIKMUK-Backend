"""Fixed read-only V17 prerequisite observation. Reuses the existing pinned wheel."""
import base64
import json
from pathlib import Path
import sys
import zlib
from connection import canonical, sha


def plan(repo):
    sources = {name: (repo / 'ops/operations' / (name + '.py')).read_text(encoding='utf-8')
               for name in ('readiness_paths', 'readiness_probe', 'v17_compatibility')}
    raw = canonical(sources)
    packed = base64.b64encode(zlib.compress(raw, 9)).decode()
    loader = 'PACKED=' + repr(packed) + '\nEXPECTED=' + repr(sha(raw)) + '''
import base64,hashlib,json,os,sys,types,zlib
from pathlib import Path
assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
raw=zlib.decompress(base64.b64decode(PACKED,validate=True))
assert len(raw)<100000 and hashlib.sha256(raw).hexdigest()==EXPECTED
sources=json.loads(raw)
for name in ('readiness_paths','readiness_probe','v17_compatibility'):
 module=types.ModuleType(name);sys.modules[name]=module
 exec(compile(sources[name],'<reviewed-'+name+'>','exec'),module.__dict__)
probe=sys.modules['readiness_probe']
'''
    child = loader + '''
import pwd
assert os.geteuid()==pwd.getpwnam('ubuntu').pw_uid!=0
inputs=probe.database_inputs()
probe.trusted_ca();probe.load_pinned_vendor(Path('/opt/jjikmuk-readiness-15c9d87c15808f1935637382'))
import pymysql
report=sys.modules['v17_compatibility'].query(pymysql.connect,inputs[4])
probe.unchanged(inputs)
print(json.dumps(report))
'''
    parent = loader + '\nCHILD=' + repr(child) + '''
import subprocess
try:
 assert os.geteuid()==0 and probe.jar_digest()==probe.JAR_SHA
 inputs=probe.database_inputs()
 result=subprocess.run(['/usr/sbin/runuser','-u','ubuntu','--','/usr/bin/python3.12','-I','-S','-B','-'],
  input=CHILD.encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=60,cwd='/',env={'PATH':'/usr/bin:/bin','LANG':'C'})
 assert result.returncode==0 and len(result.stdout)<12000
 report=json.loads(result.stdout)
 probe.unchanged(inputs);assert probe.jar_digest()==probe.JAR_SHA
 report['checks']['old_application_unchanged']=True
 print(json.dumps(report))
except Exception:
 print('{"status":"PREFLIGHT_FAILED","codes":["V17_COMPATIBILITY_READ_FAILED"]}')
'''
    document = {'schemaVersion': '2.2', 'parameters': {}, 'description': 'Read-only V17 engine/index prerequisites; no DDL, application data or service changes',
        'mainSteps': [{'action': 'aws:runShellScript', 'name': 'report', 'inputs': {'timeoutSeconds': '120',
        'runCommand': ["/usr/bin/python3.12 -I -S -B - <<'V17_COMPATIBILITY'\n" + parent + '\nV17_COMPATIBILITY']}}]}
    return {'format': 1, 'component': 'db', 'operation': 'inspect', 'approved': True,
            'approval_id': 'USER_SCHEMA_AND_CD_COMPLETION_20261110', 'document': document}


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[2]
    raw = canonical(plan(root)) + b'\n'
    target = root / 'ops/operations/plans/v17-instant-compatibility.json'
    if sys.argv[1:] == ['--write']:
        with target.open('xb') as f: f.write(raw)
    elif sys.argv[1:] == ['--check']:
        if target.read_bytes() != raw: raise ValueError('V17_COMPATIBILITY_PLAN_CHANGED')
    else: raise SystemExit('Use --write or --check')
    print('V17_COMPATIBILITY_PLAN_VERIFIED')
