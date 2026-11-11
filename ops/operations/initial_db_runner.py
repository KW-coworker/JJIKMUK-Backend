"""Exact-main maintenance: quiesce, encrypted snapshot, original schema, restore."""
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
    files = {'backend.jar': jars[0].read_bytes(), 'vendor/' + WHEEL_NAME: wheel}
    for item in compiler.glob('InitialSchema*.class'):
        files['bin/java/' + item.name] = item.read_bytes()
    sdk_folder = folder / 'sdk-wheels'
    subprocess.run([sys.executable, '-m', 'pip', 'download', '--require-hashes', '--only-binary=:all:',
                    '--dest', str(sdk_folder), '-r', str(repo / 'ops/operations/requirements.lock')],
                   check=True, timeout=180, stdout=subprocess.DEVNULL)
    pins = re.findall(r'^([a-z0-9-]+)==([^ ]+) --hash=sha256:([a-f0-9]{64})$',
                      (repo / 'ops/operations/requirements.lock').read_text(), flags=re.M)
    need(len(pins) == 7 and len(list(sdk_folder.iterdir())) == 7, 'INITIAL_SDK_LOCK_COUNT')
    sdk_lock = {}
    for package, version, expected in pins:
        found = list(sdk_folder.glob(package.replace('-', '_') + '-' + version + '-*.whl'))
        need(len(found) == 1 and digest(found[0]) == expected, 'INITIAL_SDK_LOCK_HASH')
        sdk_lock[found[0].name] = expected
        files['vendor/' + found[0].name] = found[0].read_bytes()
    files['vendor/sdk-lock.json'] = canonical(sdk_lock)
    for name in ('manifest', 'host', 'database_probe', 'runtime_contract', 'initial_contract',
                 'initial_schema', 'initial_schema_contract', 'initial_db_host', 'package_install',
                 'initial_guard', 'initial_preservation', 'initial_ddl', 'initial_flyway', 'initial_service_state',
                 'initial_db_facts', 'initial_maintenance_host'):
        files['bin/' + name + '.py'] = (repo / 'ops/cd' / (name + '.py')).read_bytes()
    for name in ('readiness_paths', 'readiness_probe', 'fulltext_definition'):
        files['bin/' + name + '.py'] = (repo / 'ops/operations' / (name + '.py')).read_bytes()
    envelope = {'format': 1, 'commit': commit, 'jar_sha256': manifest['jar_sha256'],
                'files': {name: {'sha256': sha(raw), 'bytes': len(raw)} for name, raw in files.items()}}
    archive = folder / 'payload.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for name, raw in files.items(): z.writestr(name, raw)
        z.writestr('payload-manifest.json', canonical(envelope))
    need(archive.stat().st_size < 256 * 1024**2, 'INITIAL_ARCHIVE_SIZE')
    return archive, envelope


def aws_client(service):
    import boto3
    from botocore.config import Config
    need(service in ('rds','cloudwatch'),'INITIAL_AWS_SERVICE')
    return boto3.client(service, region_name=REGION, aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
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


def snapshot(rds, api, ctx, sleep=time.sleep,*,frozen_epoch=None,guard=lambda:None,progress=lambda *args:None,max_polls=60):
    need(type(max_polls) is int and max_polls in (60,180),'INITIAL_SNAPSHOT_WAIT_BOUND')
    need(type(frozen_epoch) is int and 0<frozen_epoch<=int(time.time()),'FROZEN_DATABASE_REQUIRED')
    guard()
    name = 'jjikmuk-ops-initial-db-' + ctx['run_id']
    key = 'receipts/initial-db/' + ctx['run_id'] + '/snapshot-intent.json'
    put_once(api['s3'], key, {'snapshot': name, 'commit': ctx['commit'], 'request_id': ctx['request_id']})
    rds.create_db_snapshot(DBSnapshotIdentifier=name, DBInstanceIdentifier=DB)
    for _ in range(max_polls):
        guard()
        rows = rds.describe_db_snapshots(DBSnapshotIdentifier=name)['DBSnapshots']
        need(len(rows) == 1, 'INITIAL_SNAPSHOT_MISSING')
        row = rows[0]
        need(row['DBSnapshotIdentifier'] == name and row['DBInstanceIdentifier'] == DB
             and row['Encrypted'] is True and row['SnapshotType'] == 'manual', 'INITIAL_SNAPSHOT_CHANGED')
        percent=row.get('PercentProgress')
        known=type(percent) is int and 0<=percent<=100
        progress('SNAPSHOT_READY' if row['Status']=='available' else 'SNAPSHOT_WAIT',percent if known else 0,100 if known else None)
        if row['Status'] == 'available':
            from auto_context import check_snapshot
            check_snapshot(row, ACCOUNT, DB, datetime.now(timezone.utc))
            need(row['SnapshotCreateTime'].timestamp()>=frozen_epoch,'SNAPSHOT_PREDATES_FREEZE')
            result = {'id': name, 'arn': row['DBSnapshotArn'], 'created_at': row['SnapshotCreateTime'].isoformat()}
            save_local('snapshot-ready.json', result)
            put_once(api['s3'], 'receipts/initial-db/' + ctx['run_id'] + '/snapshot-ready.json', result)
            return result
        need(row['Status'] == 'creating', 'INITIAL_SNAPSHOT_NOT_AVAILABLE')
        sleep(10)
    raise ValueError('SNAPSHOT_WAIT_LIMIT_NO_RECREATE')


from initial_document import document


def require_time_budget(phase):
    # The marker precedes the fixed 3600-second OIDC request, so this is a
    # conservative lower bound, not a guessed expiration from a local profile.
    raw=os.environ.get('INITIAL_ROLE_REQUEST_EPOCH','')
    need(re.fullmatch('[1-9][0-9]{9}',raw),'ROLE_TIME_MARKER_REQUIRED')
    started=int(raw);now=time.time()
    need(0<=now-started,'ROLE_TIME_MARKER_INVALID')
    reserve={'freeze':1600,'snapshot':1000,'apply':2700,'recover':330}[phase]
    need(started+3600-now>=reserve,'ROLE_TIME_BUDGET_INSUFFICIENT_NO_NEW_DDL')


def maintain(api,ctx,rds,monitor,phase):
    try:
        frozen=phase('freeze')
        need(frozen.get('success'),'FREEZE_FAILED_NO_SCHEMA_APPLY')
        require_time_budget('snapshot')
        backup=snapshot(rds,api,ctx,frozen_epoch=frozen['report']['counts']['frozen_epoch'],guard=monitor.check)
        need(validate_context()==ctx,'CONTEXT_CHANGED_AFTER_SNAPSHOT')
        monitor.check()
        result=phase('apply',backup)
        need(result.get('success'),'MAINTENANCE_APPLY_FAILED_KEEP_RECORDS')
        return result
    except BaseException:
        # Recovery verifies the host journal and refuses partial/uncertain DDL.
        try:save_local('recovery-summary.json',phase('recover'))
        except Exception:save_local('recovery-unconfirmed.json',{'status':'KEEP_RECORDS_INSPECT_NO_REPLAY'})
        raise


def main():
    from initial_monitor import Monitor
    ctx = validate_context()
    api = clients(True)
    rds = aws_client('rds')
    save_local('rds-preflight.json', check_database(rds))
    archive, envelope = build_payload(Path.cwd(), ctx['commit'])
    archive_sha = digest(archive)
    key = 'operations/bootstrap/' + archive_sha + '/payload.zip'
    api['s3'].put_object(Bucket=BUCKET, Key=key, Body=archive.read_bytes(), ServerSideEncryption='AES256',
        ExpectedBucketOwner=ACCOUNT, IfNoneMatch='*', ContentType='application/zip')
    binding = {'commit': ctx['commit'], 'jar_sha256': envelope['jar_sha256'],
               'archive_sha256': archive_sha, 'request_id': ctx['request_id'],'required_bytes':5*1024**3}
    def phase(name,backup=None):
        require_time_budget(name)
        doc=document(key,archive_sha,envelope,binding,name,backup)
        plan={'format':1,'component':'db','operation':'deploy','approved':True,
              'approval_id':'USER_FULLTEXT_MAINTENANCE_AND_CD_20261110','document':doc}
        need(len(canonical(plan))<=60000,'INITIAL_DOCUMENT_SIZE')
        save_local(name+'-plan.json',plan)
        result=execute(api,ctx,plan,sha(canonical(plan)),HOSTS['backend'],output_prefix=name+'-')
        result['report']=json.loads(Path('operation-results/'+name+'-result.json').read_bytes()).get('report',{})
        return result
    with Monitor(api['s3'],aws_client('cloudwatch'),binding,binding['required_bytes']) as monitor:
        result=maintain(api,ctx,rds,monitor,phase)
    print(json.dumps(result))
    raise SystemExit(0)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{0,100}', str(error)) else type(error).__name__
        print(json.dumps({'status': 'STOPPED_KEEP_RECORDS_NO_RETRY', 'code': code}))
        raise SystemExit(1)
