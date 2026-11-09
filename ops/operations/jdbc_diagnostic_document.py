"""Prepare a new pending, parameter-free, in-memory JDBC diagnostic. Never calls AWS."""
import base64
import json
from pathlib import Path
import sys

from readiness_document import canonical, sha, verify_record

PLAN_NAME = 'commissioning-jdbc-option-names.json'


def plan(repo):
    files = {name: (repo / 'ops/operations' / (name + '.py')).read_text(encoding='utf-8').encode()
             for name in ('readiness_paths', 'readiness_probe', 'jdbc_diagnostic')}
    encoded = {name: base64.b64encode(raw).decode() for name, raw in files.items()}
    hashes = {name: sha(raw) for name, raw in files.items()}
    source = 'SOURCES=' + repr(encoded) + '\nHASHES=' + repr(hashes) + '''
import base64,hashlib,json,sys,types
try:
 assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
 for name in ('readiness_paths','readiness_probe','jdbc_diagnostic'):
  raw=base64.b64decode(SOURCES[name],validate=True)
  assert hashlib.sha256(raw).hexdigest()==HASHES[name]
  module=types.ModuleType(name)
  sys.modules[name]=module
  exec(compile(raw,'<reviewed-'+name+'>','exec'),module.__dict__)
 sys.modules['jdbc_diagnostic'].main()
except Exception:
 print('{"status":"PREFLIGHT_FAILED","codes":["DIAGNOSTIC_LOADER_FAILED"]}')
'''
    doc = {'schemaVersion': '2.2', 'description': 'JDBC option names and duplicate counts only; no DB connection or staged files',
           'parameters': {}, 'mainSteps': [{'action': 'aws:runShellScript', 'name': 'report', 'inputs': {
               'timeoutSeconds': '90', 'runCommand': ["/usr/bin/python3.12 -I -S -B - <<'JJIKMUK_JDBC_NAMES'\n" + source + '\nJJIKMUK_JDBC_NAMES']}}]}
    if len(canonical(doc)) > 60000:
        raise ValueError('DOCUMENT_LIMIT')
    return {'format': 1, 'component': 'backend', 'operation': 'inspect',
            'approval_id': 'PENDING_JDBC_OPTION_NAMES', 'approved': False, 'document': doc}


if __name__ == '__main__':
    repo = Path(__file__).resolve().parents[2]
    target = repo / 'ops/operations/plans' / PLAN_NAME
    expected = plan(repo)
    if sys.argv[1:] == ['--check']:
        verify_record(json.loads(target.read_bytes()), expected)
        print('JDBC_DIAGNOSTIC_CONTENT_VERIFIED')
    elif sys.argv[1:] == ['--write-pending']:
        with target.open('xb') as out:
            out.write(canonical(expected) + b'\n')
        print('PENDING_JDBC_DIAGNOSTIC_WRITTEN_NO_AWS')
    else:
        raise SystemExit('Use --check or --write-pending; no approval or dispatch is implemented here.')
