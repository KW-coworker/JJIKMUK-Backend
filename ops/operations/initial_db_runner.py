"""Exact-main, initial-schema-only workflow. Backup before one fixed host command."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cd'))
from connection import ACCOUNT, REGION, REPO, HOSTS, BUCKET, canonical, sha
from run import context, clients, execute, save_local, put_once
from bootstrap import need
from package_install import WHEEL_NAME, WHEEL_SHA
from manifest import make_manifest, digest
from initial_schema import validate_source
from initial_contract import DB_HOST

DB = 'jjikmuk-dev-db'
WORKFLOW = REPO + '/.github/workflows/backend-initial-db.yml@refs/heads/main'
WHEEL_URL = 'https://files.pythonhosted.org/packages/a9/4b/0a906d8184f011ff8dbd4722743783867589b33269d2c5fff238d636fdcb/pymysql-1.2.3-py3-none-any.whl'


def validate_context():
    ctx = context(os.environ['EXPECTED_SHA'], True)
    need(os.environ.get('GITHUB_WORKFLOW_REF') == WORKFLOW and os.environ.get('CD_ENABLED') == 'false',
         'INITIAL_DB_WORKFLOW_ONLY_CD_DISABLED')
    return ctx


def build_payload(repo, commit):
    jars = [p for p in (repo / 'build/libs').glob('*.jar') if not p.name.endswith('-plain.jar')]
    need(len(jars) == 1, 'ONE_BOOT_JAR_REQUIRED')
    manifest = make_manifest(jars[0], commit, '1', '1')
    validate_source(manifest)
    folder = repo / 'build/initial-db'
    folder.mkdir()
    compiler = folder / 'compile'
    compiler.mkdir()
    with zipfile.ZipFile(jars[0]) as z:
        name = 'BOOT-INF/lib/flyway-core-11.14.1.jar'
        (compiler / 'flyway-core.jar').write_bytes(z.read(name))
    subprocess.run(['javac', '-cp', str(compiler / 'flyway-core.jar'), '-d', str(compiler),
                    str(repo / 'ops/cd/java/InitialSchema.java')], check=True, timeout=60)
    with urllib.request.urlopen(WHEEL_URL, timeout=30) as response:
        need(response.url == WHEEL_URL, 'WHEEL_REDIRECT_REJECTED')
        wheel = response.read(46741)
    need(len(wheel) == 46740 and sha(wheel) == WHEEL_SHA, 'PINNED_WHEEL_CHANGED')
    files = {'backend.jar': jars[0].read_bytes(), 'vendor/' + WHEEL_NAME: wheel,
             'bin/java/InitialSchema.class': (compiler / 'InitialSchema.class').read_bytes()}
    for name in ('manifest', 'host', 'database_probe', 'runtime_contract', 'initial_contract',
                 'initial_schema', 'initial_schema_contract', 'initial_db_host', 'package_install'):
        files['bin/' + name + '.py'] = (repo / 'ops/cd' / (name + '.py')).read_bytes()
    for name in ('readiness_paths', 'readiness_probe'):
        files['bin/' + name + '.py'] = (repo / 'ops/operations' / (name + '.py')).read_bytes()
    envelope = {'format': 1, 'commit': commit, 'jar_sha256': manifest['jar_sha256'],
                'files': {name: {'sha256': sha(raw), 'bytes': len(raw)} for name, raw in files.items()}}
    archive = folder / 'payload.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for name, raw in files.items(): z.writestr(name, raw)
        z.writestr('payload-manifest.json', canonical(envelope))
    need(archive.stat().st_size < 256 * 1024**2, 'INITIAL_ARCHIVE_SIZE')
    return archive, envelope


def rds_client():
    import boto3
    from botocore.config import Config
    return boto3.client('rds', region_name=REGION, aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'], aws_session_token=os.environ['AWS_SESSION_TOKEN'],
        config=Config(connect_timeout=10, read_timeout=30, retries={'total_max_attempts': 1}))


def check_database(rds):
    rows = rds.describe_db_instances(DBInstanceIdentifier=DB)['DBInstances']
    need(len(rows) == 1, 'FIXED_RDS_REQUIRED')
    db = rows[0]
    need(db['DBInstanceIdentifier'] == DB and db['DBInstanceArn'] == f'arn:aws:rds:{REGION}:{ACCOUNT}:db:{DB}'
         and db['Engine'] == 'mysql' and db['EngineVersion'].startswith('8.')
         and db['DBInstanceStatus'] == 'available' and db['StorageEncrypted'] is True
         and db['Endpoint']['Address'] == DB_HOST and db['Endpoint']['Port'] == 3306,
         'INITIAL_RDS_STATE_CHANGED')
    need(db['BackupRetentionPeriod'] >= 1 and db.get('LatestRestorableTime') is not None,
         'AUTOMATED_BACKUP_REQUIRED')
    age = (datetime.now(timezone.utc) - db['LatestRestorableTime']).total_seconds()
    need(0 <= age <= 7200, 'RDS_RECOVERY_POINT_STALE')
    return {'checks': {'automated_backups_enabled': True, 'encrypted': True, 'available': True},
            'counts': {'backup_retention_days': db['BackupRetentionPeriod']},
            'hashes': {'rds_configuration': sha(canonical({k: db[k] for k in
                ('DBInstanceIdentifier', 'Engine', 'EngineVersion', 'BackupRetentionPeriod', 'PreferredBackupWindow')}))}}


def snapshot(rds, api, ctx, sleep=time.sleep):
    name = 'jjikmuk-ops-initial-db-' + ctx['run_id']
    key = 'receipts/initial-db/' + ctx['run_id'] + '/snapshot-intent.json'
    put_once(api['s3'], key, {'snapshot': name, 'commit': ctx['commit'], 'request_id': ctx['request_id']})
    rds.create_db_snapshot(DBSnapshotIdentifier=name, DBInstanceIdentifier=DB)
    for _ in range(120):
        rows = rds.describe_db_snapshots(DBSnapshotIdentifier=name)['DBSnapshots']
        need(len(rows) == 1, 'INITIAL_SNAPSHOT_MISSING')
        row = rows[0]
        need(row['DBSnapshotIdentifier'] == name and row['DBInstanceIdentifier'] == DB
             and row['Encrypted'] is True and row['SnapshotType'] == 'manual', 'INITIAL_SNAPSHOT_CHANGED')
        if row['Status'] == 'available':
            from auto_context import check_snapshot
            check_snapshot(row, ACCOUNT, DB, datetime.now(timezone.utc))
            result = {'id': name, 'arn': row['DBSnapshotArn'], 'created_at': row['SnapshotCreateTime'].isoformat()}
            save_local('snapshot-ready.json', result)
            put_once(api['s3'], 'receipts/initial-db/' + ctx['run_id'] + '/snapshot-ready.json', result)
            return result
        need(row['Status'] == 'creating', 'INITIAL_SNAPSHOT_NOT_AVAILABLE')
        sleep(10)
    raise ValueError('SNAPSHOT_WAIT_LIMIT_NO_RECREATE')


def document(key, archive_sha, envelope, binding):
    need(key == 'operations/bootstrap/' + archive_sha + '/payload.zip', 'INITIAL_PAYLOAD_KEY')
    stage = '/opt/jjikmuk-initial-' + archive_sha[:16]
    download = '/var/lib/amazon/ssm/jjikmuk-initial-' + archive_sha[:16]
    setup = f'''from pathlib import Path
import os
p=Path({download!r})
for parent in p.parents:
 s=parent.lstat();assert not parent.is_symlink() and s.st_uid==0 and not s.st_mode&0o022
p.mkdir(mode=0o700);os.chmod(p,0o700)
'''
    apply = f'''import hashlib,json,os,subprocess,zipfile
from pathlib import Path,PurePosixPath
try:
 archive=Path({download!r})/'payload.zip'
 assert not archive.is_symlink() and archive.stat().st_size<268435456
 assert hashlib.sha256(archive.read_bytes()).hexdigest()=={archive_sha!r}
 stage=Path({stage!r});assert not stage.exists() and not stage.is_symlink()
 with zipfile.ZipFile(archive) as z:
  expected={envelope!r}
  assert json.loads(z.read('payload-manifest.json'))==expected
  names=z.namelist();assert len(names)==len(set(names)) and set(names)==set(expected['files'])|{{'payload-manifest.json'}}
  assert sum(i.file_size for i in z.infolist())<400*1024**2
  for name,meta in expected['files'].items():
   p=PurePosixPath(name);assert not p.is_absolute() and '..' not in p.parts and str(p)==name
   assert z.getinfo(name).file_size==meta['bytes'] and hashlib.sha256(z.read(name)).hexdigest()==meta['sha256']
  stage.mkdir(mode=0o755);os.chmod(stage,0o755)
  for name in expected['files']:
   path=stage/name
   for parent in reversed(path.parents):
    if stage in parent.parents and not parent.exists():parent.mkdir(mode=0o755);os.chmod(parent,0o755)
   with path.open('xb') as f:f.write(z.read(name));f.flush();os.fsync(f.fileno())
   os.chmod(path,0o644)
 r=subprocess.run(['/usr/bin/systemd-run','--quiet','--wait','--pipe','--collect','--service-type=exec',
  '--unit=jjikmuk-initial-db-{archive_sha[:16]}','--property=RuntimeMaxSec=420',
  '--property=TimeoutStartSec=30','--property=TimeoutStopSec=5','--property=KillMode=control-group',
  '--property=UMask=0077','--property=Restart=no',
  '/usr/bin/python3.12','-I','-S','-B',str(stage/'bin/initial_db_host.py')],
  input={canonical(binding)!r},capture_output=True,timeout=480,cwd='/',env={{'PATH':'/usr/bin:/bin','LANG':'C'}})
 assert r.returncode==0 and not r.stderr and len(r.stdout)<12000
 value=json.loads(r.stdout);assert isinstance(value,dict)
 print(json.dumps(value))
except Exception:
 print('{{"status":"STOPPED","codes":["INITIAL_DB_STAGE_FAILED_KEEP_RECORDS"]}}')
'''
    def shell(code): return ["/usr/bin/python3.12 -I -S -B - <<'INITIAL_SCHEMA_FIXED'\n" + code + '\nINITIAL_SCHEMA_FIXED']
    return {'schemaVersion': '2.2', 'parameters': {}, 'description': 'Approved original V17-V20 only after verified encrypted snapshot; no app restart',
            'mainSteps': [
                {'name': 'prepareStage', 'action': 'aws:runShellScript', 'inputs': {'timeoutSeconds': '30', 'runCommand': shell(setup)}},
                {'name': 'downloadOriginal', 'action': 'aws:downloadContent', 'inputs': {'sourceType': 'S3',
                 'sourceInfo': json.dumps({'path': 'https://s3.ap-northeast-2.amazonaws.com/' + BUCKET + '/' + key}), 'destinationPath': download}},
                {'name': 'report', 'action': 'aws:runShellScript', 'inputs': {'timeoutSeconds': '540', 'runCommand': shell(apply)}}]}


def main():
    ctx = validate_context()
    api = clients(True)
    rds = rds_client()
    save_local('rds-preflight.json', check_database(rds))
    archive, envelope = build_payload(Path.cwd(), ctx['commit'])
    archive_sha = digest(archive)
    key = 'operations/bootstrap/' + archive_sha + '/payload.zip'
    api['s3'].put_object(Bucket=BUCKET, Key=key, Body=archive.read_bytes(), ServerSideEncryption='AES256',
        ExpectedBucketOwner=ACCOUNT, IfNoneMatch='*', ContentType='application/zip')
    backup = snapshot(rds, api, ctx)
    need(validate_context() == ctx, 'CONTEXT_CHANGED_AFTER_SNAPSHOT')
    binding = {'commit': ctx['commit'], 'jar_sha256': envelope['jar_sha256'], 'snapshot': backup,
               'archive_sha256': archive_sha, 'request_id': ctx['request_id']}
    doc = document(key, archive_sha, envelope, binding)
    plan = {'format': 1, 'component': 'db', 'operation': 'deploy', 'approved': True,
            'approval_id': 'USER_SCHEMA_AND_CD_COMPLETION_20261110', 'document': doc}
    need(len(canonical(plan)) <= 60000, 'INITIAL_DOCUMENT_SIZE')
    save_local('initial-schema-plan.json', plan)
    result = execute(api, ctx, plan, sha(canonical(plan)), HOSTS['backend'])
    print(json.dumps(result))
    raise SystemExit(0 if result.get('success') else 1)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{0,100}', str(error)) else type(error).__name__
        print(json.dumps({'status': 'STOPPED_KEEP_RECORDS_NO_RETRY', 'code': code}))
        raise SystemExit(1)
