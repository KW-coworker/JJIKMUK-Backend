"""Exact-main build and automatic, duplicate-resistant fixed SSM deployment."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import time
from auto_context import (ACCOUNT, REGION, BUCKET, PREFIX, INSTANCE, DOCUMENT,
                          identity, guard, select_snapshot, check_snapshot)
from manifest import make_manifest, read_json, require


def clients():
    import boto3
    from botocore.config import Config
    keys = [os.environ.get(k) for k in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN')]
    require(all(keys), 'OIDC_CREDENTIALS_REQUIRED')
    sdk = boto3.Session(aws_access_key_id=keys[0], aws_secret_access_key=keys[1], aws_session_token=keys[2], region_name=REGION)
    cfg = Config(connect_timeout=10, read_timeout=30, retries={'total_max_attempts': 1})
    return {s: sdk.client(s, config=cfg) for s in ('sts', 'rds', 's3', 'ssm')}


def package():
    guard(deployment=False)
    jars = [p for p in Path('build/libs').glob('*.jar') if not p.name.endswith('-plain.jar')]
    require(len(jars) == 1, 'EXPECTED_ONE_BOOT_JAR')
    folder = Path('build/cd-release'); folder.mkdir(exist_ok=False)
    m = make_manifest(jars[0], *identity())
    shutil.copyfile(jars[0], folder / 'backend.jar')
    (folder / 'manifest.json').write_text(json.dumps(m, sort_keys=True, indent=2), encoding='utf-8')
    report({'status': 'PACKAGED', 'commit': m['commit'], 'jar_sha256': m['jar_sha256']})


def error_code(error):
    return getattr(error, 'response', {}).get('Error', {}).get('Code')


def get_receipt(s3, key):
    # With prefix-limited ListBucket, a direct missing GetObject may return 403.
    # Strongly consistent listing distinguishes absent keys without treating 403 as absent.
    listed = s3.list_objects_v2(Bucket=BUCKET, Prefix=key, MaxKeys=2, ExpectedBucketOwner=ACCOUNT)
    if not any(item['Key'] == key for item in listed.get('Contents', [])): return None
    try: response = s3.get_object(Bucket=BUCKET, Key=key, ExpectedBucketOwner=ACCOUNT)
    except Exception as error:
        if error_code(error) in ('NoSuchKey', '404'): return None
        raise
    with response['Body'] as stream: data = stream.read(65537)
    require(len(data) <= 65536, 'RECEIPT_SIZE')
    return json.loads(data)


def put_receipt(s3, key, value):
    return s3.put_object(Bucket=BUCKET, Key=key, Body=json.dumps(value, sort_keys=True).encode(),
                         ContentType='application/json', ServerSideEncryption='AES256',
                         ExpectedBucketOwner=ACCOUNT, IfNoneMatch='*')


def report(value):
    folder = Path('deployment-results'); folder.mkdir(exist_ok=True)
    (folder / 'result.json').write_text(json.dumps(value, sort_keys=True, indent=2), encoding='utf-8')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write('Backend CD: **' + value['status'] + '**\n\n')
            for name in ('commit', 'command_id', 'run_id', 'attempt'):
                if name in value: f.write('- ' + name + ': `' + str(value[name]) + '`\n')
    print(json.dumps(value), flush=True)


def find_command(ssm, intent, command_id=None):
    # SendCommand has no client idempotency token: collect a lost response, never resend.
    found, token = [], None
    for _ in range(100):
        args = {'InstanceId': INSTANCE, 'MaxResults': 50}
        if command_id: args['CommandId'] = command_id
        if token: args['NextToken'] = token
        response = ssm.list_commands(**args)
        for command in response.get('Commands', []):
            if command.get('Comment') != intent['comment']: continue
            require(command.get('DocumentName') == DOCUMENT and command.get('DocumentVersion') == '1'
                    and command.get('InstanceIds') == [INSTANCE] and not command.get('Targets'), 'COMMAND_TARGET_MISMATCH')
            parameters = command.get('Parameters', {})
            expected = {'ReleaseCommit': [intent['commit']], 'RunId': [intent['run_id']],
                        'RunAttempt': [intent['attempt']], 'JarSha256': [intent['jar_sha256']]}
            require(all(parameters.get(k) == v for k, v in expected.items()) and
                    set(parameters) == set(expected) | {'JarVersion','ManifestVersion'}, 'COMMAND_PARAMETERS_MISMATCH')
            for key in ('JarVersion','ManifestVersion'):
                values = parameters[key]
                require(isinstance(values,list) and len(values)==1 and isinstance(values[0],str) and
                        re.fullmatch(r'[A-Za-z0-9._~+/-]{1,1024}', values[0]) and values[0]!='null', 'COMMAND_VERSION_MISMATCH')
            found.append(command['CommandId'])
        token = response.get('NextToken')
        if not token: break
    else: raise ValueError('COMMAND_HISTORY_LIMIT')
    require(len(found) <= 1, 'AMBIGUOUS_COMMAND_HISTORY')
    return found[0] if found else None


def wait_result(ssm, command_id, intent):
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        try: result = ssm.get_command_invocation(CommandId=command_id, InstanceId=INSTANCE, PluginName='deployBackend')
        except Exception as error:
            if error_code(error) != 'InvocationDoesNotExist': raise
            result = None
        if result and result['Status'] not in {'Pending', 'InProgress', 'Delayed'}:
            try: status = json.loads(result.get('StandardOutputContent', ''))['status']
            except (ValueError, KeyError, TypeError): status = 'UNRECOGNIZED_HOST_RESULT'
            allowed = {'SUCCEEDED', 'ROLLED_BACK', 'MANUAL_RECOVERY_REQUIRED', 'STOP_REVIEW_REQUIRED'}
            if status not in allowed: status = 'UNRECOGNIZED_HOST_RESULT'
            if status == 'SUCCEEDED' and (result['Status'] != 'Success' or result.get('ResponseCode') != 0):
                status = 'UNRECOGNIZED_HOST_RESULT'
            return {k: intent[k] for k in ('commit', 'run_id', 'attempt')} | {'status': status, 'command_id': command_id}
        time.sleep(5)
    raise ValueError('STATUS_UNKNOWN_DO_NOT_REDISPATCH')


def collect(c, intent, root):
    require(intent.get('commit') == identity()[0] and intent.get('instance') == INSTANCE and
            intent.get('document') == DOCUMENT and intent.get('document_version') == '1', 'RECEIPT_TARGET_MISMATCH')
    for name, pattern in [('run_id',r'[1-9][0-9]{0,19}'),('attempt',r'[1-9][0-9]{0,3}'),('jar_sha256',r'[0-9a-f]{64}')]:
        require(isinstance(intent.get(name),str) and re.fullmatch(pattern,intent[name]), 'RECEIPT_IDENTITY_MISMATCH')
    require(intent.get('comment') == 'backend-auto:'+intent['commit']+':'+intent['run_id']+'-'+intent['attempt'], 'RECEIPT_COMMENT_MISMATCH')
    cached = get_receipt(c['s3'], root + '/result.json')
    sent = get_receipt(c['s3'], root + '/sent.json')
    if sent:
        require(isinstance(sent,dict) and set(sent)=={'command_id'} and isinstance(sent['command_id'],str) and
                re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}',sent['command_id']), 'COMMAND_ID_MISMATCH')
    if cached:
        require(isinstance(cached,dict) and set(cached)=={'commit','run_id','attempt','command_id','status'} and
                all(cached.get(k)==intent[k] for k in ('commit','run_id','attempt')), 'CACHED_RESULT_MISMATCH')
    command_id = None
    for _ in range(12):
        command_id = find_command(c['ssm'], intent, sent['command_id'] if sent else None)
        if command_id: break
        time.sleep(5)  # SSM is eventually consistent; retry reads, never SendCommand.
    require(bool(command_id), 'SEND_OUTCOME_UNKNOWN_NO_REDISPATCH')
    require(not sent or command_id==sent['command_id'], 'COMMAND_ID_MISMATCH')
    result = wait_result(c['ssm'], command_id, intent)
    if cached: require(cached == result, 'CACHED_RESULT_MISMATCH')
    else: put_receipt(c['s3'], root + '/result.json', result)
    return result


def dispatch():
    guard()
    sha, run, attempt = identity()
    m = read_json('release/manifest.json')
    require(m == make_manifest('release/backend.jar', sha, run, attempt), 'DOWNLOADED_ARTIFACT_MISMATCH')
    c = clients()
    caller = c['sts'].get_caller_identity()
    require(caller['Account'] == ACCOUNT and caller['Arn'].startswith(
        f'arn:aws:sts::{ACCOUNT}:assumed-role/JjikmukBackendAutoDeploy/'), 'WRONG_AWS_IDENTITY')
    s3 = c['s3']; root = 'receipts/backend-cd/' + sha
    intent = get_receipt(s3, root + '/intent.json')
    if intent:
        result = collect(c, intent, root)
    else:
        backup = select_snapshot(c['rds'])
        require(s3.get_bucket_versioning(Bucket=BUCKET, ExpectedBucketOwner=ACCOUNT).get('Status') == 'Enabled', 'S3_VERSIONING_REQUIRED')
        intent = {'commit': sha, 'run_id': run, 'attempt': attempt, 'jar_sha256': m['jar_sha256'],
                  'instance': INSTANCE, 'document': DOCUMENT, 'document_version': '1', 'backup': backup,
                  'comment': 'backend-auto:' + sha + ':' + run + '-' + attempt}
        put_receipt(s3, root + '/intent.json', intent)
        versions = {}
        for name in ('backend.jar', 'manifest.json'):
            with open('release/' + name, 'rb') as body:
                uploaded = s3.put_object(Bucket=BUCKET, Key=f'{PREFIX}/{sha}/{run}-{attempt}/{name}', Body=body,
                    ExpectedBucketOwner=ACCOUNT, ServerSideEncryption='AES256', ChecksumAlgorithm='SHA256', IfNoneMatch='*')
            version = uploaded.get('VersionId', '')
            require(isinstance(version, str) and version not in ('', 'null'), 'S3_VERSION_MISSING')
            versions[name] = version
        guard()
        params = {'ReleaseCommit': [sha], 'RunId': [run], 'RunAttempt': [attempt], 'JarSha256': [m['jar_sha256']],
                  'JarVersion': [versions['backend.jar']], 'ManifestVersion': [versions['manifest.json']]}
        try:
            response = c['ssm'].send_command(InstanceIds=[INSTANCE], DocumentName=DOCUMENT,
                DocumentVersion='1', Parameters=params, TimeoutSeconds=60, Comment=intent['comment'])
        except Exception:
            result = collect(c, intent, root)
        else:
            command_id = response['Command']['CommandId']
            put_receipt(s3, root + '/sent.json', {'command_id': command_id})
            result = collect(c, intent, root)
    report(result)
    require(result['status'] == 'SUCCEEDED', 'DEPLOYMENT_NOT_SUCCESSFUL')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('mode', choices=['package', 'dispatch'])
    args = parser.parse_args()
    try: {'package': package, 'dispatch': dispatch}[args.mode]()
    except Exception as error:
        code = str(error) if type(error) is ValueError and re.fullmatch('[A-Z_]+', str(error)) else 'RELEASE_FAILED'
        if not Path('deployment-results/result.json').exists(): report({'status': code})
        print(json.dumps({'status': code})); raise SystemExit(1)
