"""GitHub runner packaging and approved S3/SSM dispatch. Never creates infrastructure."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request

from manifest import make_manifest, read_json, require


def env(name, pattern):
    value = os.environ.get(name, '')
    require(re.fullmatch(pattern, value) is not None, 'INVALID_RELEASE_INPUT')
    return value


def identity():
    return (env('GITHUB_SHA', r'[0-9a-f]{40}'), env('GITHUB_RUN_ID', r'[1-9][0-9]{0,19}'),
            env('GITHUB_RUN_ATTEMPT', r'[1-9][0-9]{0,3}'))


def aws(*args, missing_invocation=False):
    p = subprocess.run(['aws', *args, '--region', 'ap-northeast-2', '--output', 'json'],
                       capture_output=True, text=True, timeout=180,
                       env={**os.environ, 'AWS_MAX_ATTEMPTS': '1', 'AWS_PAGER': ''})
    if missing_invocation and p.returncode and 'InvocationDoesNotExist' in p.stderr: return None
    require(p.returncode == 0, 'AWS_REQUEST_FAILED_NO_RETRY')
    return json.loads(p.stdout)


def check_snapshot(snapshot, account, database, now):
    require(snapshot['Status'] == 'available' and snapshot['Encrypted'] is True, 'BACKUP_NOT_READY')
    require(snapshot['DBInstanceIdentifier'] == database and
            snapshot['DBSnapshotArn'].startswith(f'arn:aws:rds:ap-northeast-2:{account}:snapshot:'), 'WRONG_BACKUP')
    age = (now - datetime.fromisoformat(snapshot['SnapshotCreateTime'].replace('Z', '+00:00'))).total_seconds()
    require(0 <= age <= 86400, 'BACKUP_TOO_OLD')


def guard(deployment=True):
    require(os.environ.get('GITHUB_REPOSITORY') == 'KW-coworker/JJIKMUK-Backend' and
            os.environ.get('GITHUB_REF') == 'refs/heads/main' and
            os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch', 'MAIN_MANUAL_ONLY')
    sha, _, _ = identity()
    mode = os.environ.get('CD_MODE', 'verify')
    require(mode in {'verify', 'deploy'}, 'INVALID_CD_MODE')
    require(os.environ.get('EXPECTED_SHA') == sha, 'SHA_OR_APPROVAL_MISMATCH')
    if deployment or mode == 'deploy':
        require(mode == 'deploy' and os.environ.get('CONFIRM_DEPLOY') == 'true', 'DEPLOYMENT_NOT_APPROVED')
        require(os.environ.get('CD_ENABLED') == 'true', 'CD_DISABLED')
    # Recheck after environment approval: an old approval must not deploy a moved main.
    request = urllib.request.Request('https://api.github.com/repos/KW-coworker/JJIKMUK-Backend/git/ref/heads/main',
                                     headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'JJIKMUK-CD'})
    with urllib.request.urlopen(request, timeout=15) as response:
        require(json.load(response)['object']['sha'] == sha, 'MAIN_MOVED')


def package():
    guard(deployment=False)
    jars = list(Path('build/libs').glob('*.jar'))
    jars = [p for p in jars if not p.name.endswith('-plain.jar')]
    require(len(jars) == 1, 'EXPECTED_ONE_BOOT_JAR')
    folder = Path('build/cd-release'); folder.mkdir(exist_ok=False)
    m = make_manifest(jars[0], *identity())
    shutil.copyfile(jars[0], folder / 'backend.jar')
    (folder / 'manifest.json').write_text(json.dumps(m, sort_keys=True, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'PACKAGED', 'commit': m['commit'], 'jar_sha256': m['jar_sha256']}))


def dispatch():
    guard()
    sha, run, attempt = identity()
    m = read_json('release/manifest.json')
    require(m == make_manifest('release/backend.jar', sha, run, attempt), 'DOWNLOADED_ARTIFACT_MISMATCH')
    account = env('AWS_ACCOUNT_ID', r'[0-9]{12}')
    require(aws('sts', 'get-caller-identity')['Account'] == account, 'WRONG_AWS_ACCOUNT')
    bucket = env('CD_BUCKET', r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]')
    prefix = env('CD_PREFIX', r'[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*')
    iid = env('CD_INSTANCE_ID', r'i-[0-9a-f]{17}')
    document = env('CD_DOCUMENT', r'[A-Za-z][A-Za-z0-9_-]{2,127}')
    version = env('CD_DOCUMENT_VERSION', r'[1-9][0-9]*')
    snapshot_id = env('SNAPSHOT_ID', r'[a-zA-Z][a-zA-Z0-9-]{0,254}')
    database = env('CD_DATABASE_ID', r'[a-zA-Z][a-zA-Z0-9-]{0,62}')
    snapshots = aws('rds', 'describe-db-snapshots', '--db-snapshot-identifier', snapshot_id)['DBSnapshots']
    require(len(snapshots) == 1, 'BACKUP_COUNT')
    check_snapshot(snapshots[0], account, database, datetime.now(timezone.utc))
    require(aws('s3api', 'get-bucket-versioning', '--bucket', bucket).get('Status') == 'Enabled', 'S3_VERSIONING_REQUIRED')
    versions = {}
    for name in ['backend.jar', 'manifest.json']:
        result = aws('s3api', 'put-object', '--bucket', bucket, '--key', f'{prefix}/{sha}/{run}-{attempt}/{name}',
                     '--body', f'release/{name}', '--checksum-algorithm', 'SHA256')
        value = result.get('VersionId', '')
        require(value not in ['', 'null'], 'S3_VERSION_MISSING')
        versions[name] = value
    params = {'ReleaseCommit': [sha], 'RunId': [run], 'RunAttempt': [attempt], 'JarSha256': [m['jar_sha256']],
              'JarVersion': [versions['backend.jar']], 'ManifestVersion': [versions['manifest.json']]}
    response = aws('ssm', 'send-command', '--instance-ids', iid, '--document-name', document,
                   '--document-version', version, '--parameters', json.dumps(params), '--timeout-seconds', '60',
                   '--comment', f'Approved backend release {sha} run {run}-{attempt}')
    command_id = response['Command']['CommandId']
    print(json.dumps({'status': 'DISPATCHED', 'command_id': command_id, 'commit': sha}), flush=True)
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        result = aws('ssm', 'get-command-invocation', '--command-id', command_id, '--instance-id', iid, missing_invocation=True)
        if result and result['Status'] not in {'Pending', 'InProgress', 'Delayed'}:
            require(result['Status'] == 'Success' and result['ResponseCode'] == 0, 'DEPLOYMENT_FAILED_CHECK_SSM_RECEIPT')
            require(json.loads(result['StandardOutputContent']) == {'status': 'SUCCEEDED'}, 'UNEXPECTED_DEPLOYMENT_RESULT')
            print(json.dumps({'status': 'SUCCEEDED', 'commit': sha})); return
        time.sleep(5)
    raise ValueError('STATUS_UNKNOWN_DO_NOT_REDISPATCH')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['package', 'dispatch'])
    args = parser.parse_args()
    try:
        {'package': package, 'dispatch': dispatch}[args.mode]()
    except Exception as error:
        allowed = str(error) if type(error) is ValueError and re.fullmatch('[A-Z_]+', str(error)) else 'RELEASE_FAILED'
        print(json.dumps({'status': allowed}))
        raise SystemExit(1)
