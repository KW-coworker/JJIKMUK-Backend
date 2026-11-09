"""Human CloudShell repair for the exact failed initial connection; never deploys.

Does not recreate the stack, change permissions, retry a failed write, or delete journals.
Only an UPDATE change set limited to the two absent failed SSM documents is executable.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.request

ACCOUNT = '076767081522'
REGION = 'ap-northeast-2'
STACK = ('arn:aws:cloudformation:ap-northeast-2:076767081522:stack/'
         'Jjikmuk-ServerOperations/9d32c4f0-dc5f-11f1-850a-02e7e30b774b')
BUCKET = 'jjikmuk-operations-076767081522-apne2'
OLD_SHA = '46a055ae5f680819bf59704a43690a7c3ad3ead988701f873dcef957edecc044'
NEW_SHA = '61fb267d7b184b2e34777eac4dc0f2274ae8971958add2dd537a0b33e0374dc8'
FIXED_HELPER_SHA = '76953ad787d48ddb45db7eb8072d688e53d85d3358ab12f4d1c3a180e3567be5'
FIELDS = {'BackendDeployDocument': ('JarVersion', 'ManifestVersion'),
          'ChatbotDeployDocument': ('ArchiveVersion', 'ManifestVersion')}
OLD_PATTERN = '[A-Za-z0-9._~+/-]{1,1024}'
NEW_PATTERN = '[A-Za-z0-9._~+/-]{1,1000}[A-Za-z0-9._~+/-]{0,24}'


def need(condition, code):
    if not condition:
        raise ValueError(code)


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':')).encode()


def digest(data):
    return hashlib.sha256(canonical(data)).hexdigest()


def corrected_template(original):
    need(digest(original) == OLD_SHA, 'ORIGINAL_TEMPLATE_CHANGED')
    result = copy.deepcopy(original)
    for logical, fields in FIELDS.items():
        params = result['Resources'][logical]['Properties']['Content']['parameters']
        for name in fields:
            old = params[name]['allowedPattern']
            need(old in (OLD_PATTERN, '^' + OLD_PATTERN + '$'), 'PATTERN_CHANGED')
            params[name]['allowedPattern'] = old.replace(OLD_PATTERN, NEW_PATTERN)
    need(digest(result) == NEW_SHA, 'CORRECTED_TEMPLATE_CHANGED')
    return result


def read_json(path):
    need(not path.is_symlink() and path.is_file() and path.stat().st_size <= 65536,
         'JOURNAL_NOT_REGULAR')
    return json.loads(path.read_bytes())


def verify_github(main):
    need(isinstance(main, str) and re.fullmatch('[0-9a-f]{40}', main), 'EXACT_MAIN_REQUIRED')
    url = 'https://api.github.com/repos/KW-coworker/JJIKMUK-Backend/git/ref/heads/main'
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'jjikmuk-regex-repair'}), timeout=20) as r:
        raw = r.read(65537); need(len(raw) <= 65536, 'GITHUB_RESPONSE_LIMIT')
        need(json.loads(raw)['object']['sha'] == main, 'MAIN_CHANGED')
    url = ('https://raw.githubusercontent.com/KW-coworker/JJIKMUK-Backend/' + main
           + '/ops/operations/connect_once.py')
    with urllib.request.urlopen(url, timeout=20) as r:
        raw = r.read(131073)
    need(len(raw) <= 131072 and hashlib.sha256(raw).hexdigest() == FIXED_HELPER_SHA,
         'CORRECTED_HELPER_NOT_IN_MAIN')


def pages(call, key, **kwargs):
    result = []
    for _ in range(20):
        response = call(**kwargs)
        result.extend(response[key])
        if not response.get('NextToken'):
            return result
        kwargs['NextToken'] = response['NextToken']
    raise ValueError('PAGINATION_LIMIT')


def stack_resources(cf):
    rows = pages(cf.list_stack_resources, 'StackResourceSummaries', StackName=STACK)
    need(len({r['LogicalResourceId'] for r in rows}) == len(rows), 'DUPLICATE_RESOURCES')
    return {r['LogicalResourceId']: r for r in rows}


def absent_documents(ssm, template):
    for logical in FIELDS:
        name = template['Resources'][logical]['Properties']['Name']
        try:
            ssm.describe_document(Name=name)
        except Exception as error:
            if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'InvalidDocument':
                continue
            raise
        raise ValueError('FAILED_DOCUMENT_ALREADY_EXISTS')


def verify_change_set(response):
    need(response.get('StackId') == STACK and response.get('Status') == 'CREATE_COMPLETE'
         and response.get('ExecutionStatus') == 'AVAILABLE', 'CHANGE_SET_NOT_READY')
    changes = response.get('Changes', [])
    need(len(changes) == 2, 'UNEXPECTED_CHANGE_COUNT')
    need({x.get('ResourceChange', {}).get('LogicalResourceId') for x in changes} == set(FIELDS),
         'UNEXPECTED_CHANGE_TARGET')
    for item in changes:
        change = item['ResourceChange']
        need(item.get('Type') == 'Resource' and change.get('ResourceType') == 'AWS::SSM::Document'
             and change.get('Action') in ('Add', 'Modify')
             and change.get('Replacement') in (None, 'False', 'True')
             and set(change.get('Scope', [])) <= {'Properties'}, 'UNEXPECTED_CHANGE_KIND')
        # Replacement is allowed only because both failed names are independently
        # verified absent immediately before execution. Existing resources are never replaced.


def preflight(clients, old_journal):
    cf = clients['cloudformation']
    need(clients['sts'].get_caller_identity()['Account'] == ACCOUNT, 'WRONG_ACCOUNT')
    need(old_journal.get('status') == 'STOPPED_KEEP_RECORDS_NO_RETRY'
         and old_journal.get('template_sha256') == OLD_SHA
         and old_journal.get('stack_id') == STACK, 'ORIGINAL_JOURNAL_MISMATCH')
    stack = cf.describe_stacks(StackName=STACK)['Stacks'][0]
    need(stack['StackId'] == STACK and stack['StackStatus'] == 'CREATE_FAILED'
         and stack.get('DisableRollback') is True and not stack.get('RoleARN'),
         'STACK_STATE_CHANGED')
    params = stack.get('Parameters', [])
    need(len(params) == 1 and params[0]['ParameterKey'] == 'ExistingGitHubProvider'
         and params[0]['ParameterValue'] in ('true', 'false'), 'STACK_PARAMETERS_CHANGED')
    original = cf.get_template(StackName=STACK, TemplateStage='Original')['TemplateBody']
    if isinstance(original, str):
        original = json.loads(original)
    new = corrected_template(original)
    rows = stack_resources(cf)
    expected = set(original['Resources'])
    if params[0]['ParameterValue'] == 'true':
        expected.remove('GitHubProvider')
    need(set(rows) == expected, 'RESOURCE_SET_CHANGED')
    for name, row in rows.items():
        need(row['ResourceType'] == original['Resources'][name]['Type'], 'RESOURCE_TYPE_CHANGED')
        if name in FIELDS:
            need(row['ResourceStatus'] == 'CREATE_FAILED', 'FAILED_RESOURCE_STATE_CHANGED')
        else:
            need(row['ResourceStatus'] == 'CREATE_COMPLETE' and row.get('PhysicalResourceId'),
                 'OTHER_RESOURCE_NOT_COMPLETE')
    absent_documents(clients['ssm'], original)
    return new, {k: v['PhysicalResourceId'] for k, v in rows.items() if k not in FIELDS}


def verify_complete(clients, new, preserved):
    cf = clients['cloudformation']
    need(cf.describe_stacks(StackName=STACK)['Stacks'][0]['StackStatus'] == 'UPDATE_COMPLETE',
         'UPDATE_NOT_COMPLETE')
    actual = cf.get_template(StackName=STACK, TemplateStage='Original')['TemplateBody']
    if isinstance(actual, str):
        actual = json.loads(actual)
    need(digest(actual) == NEW_SHA, 'FINAL_TEMPLATE_CHANGED')
    rows = stack_resources(cf)
    need(set(rows) == set(preserved) | set(FIELDS), 'FINAL_RESOURCE_SET_CHANGED')
    for key, physical in preserved.items():
        need(rows[key].get('PhysicalResourceId') == physical
             and rows[key]['ResourceStatus'] in ('CREATE_COMPLETE', 'UPDATE_COMPLETE'),
             'EXISTING_RESOURCE_CHANGED')
    for key in FIELDS:
        need(rows[key]['ResourceStatus'] in ('CREATE_COMPLETE', 'UPDATE_COMPLETE'),
             'DOCUMENT_NOT_COMPLETE')
        name = new['Resources'][key]['Properties']['Name']
        doc = clients['ssm'].get_document(Name=name, DocumentVersion='1', DocumentFormat='JSON')
        need(json.loads(doc['Content']) == new['Resources'][key]['Properties']['Content'],
             'DOCUMENT_CONTENT_CHANGED')


def repair(clients, old_journal, journal, main, confirm=input, sleep=time.sleep):
    need(not journal.exists() and not journal.is_symlink(), 'KEEP_RECOVERY_JOURNAL_NO_RETRY')
    new, preserved = preflight(clients, old_journal)
    need(confirm('Type REPAIR JJIKMUK SSM REGEX ONLY: ') == 'REPAIR JJIKMUK SSM REGEX ONLY',
         'NOT_CONFIRMED')
    state = {'status': 'CHANGE_SET_INTENT', 'stack_id': STACK, 'old_sha256': OLD_SHA,
             'new_sha256': NEW_SHA, 'main': main, 'preserved': preserved}
    with journal.open('x', encoding='utf-8') as log:
        os.chmod(journal, 0o600)
        def save():
            log.seek(0); json.dump(state, log); log.truncate(); log.flush(); os.fsync(log.fileno())
        save()
        try:
            cf = clients['cloudformation']
            created = cf.create_change_set(StackName=STACK,
                ChangeSetName='ssm-regex-repair-' + NEW_SHA[:20], ChangeSetType='UPDATE',
                ClientToken='preview-' + NEW_SHA, TemplateBody=canonical(new).decode(),
                Parameters=[{'ParameterKey': 'ExistingGitHubProvider', 'UsePreviousValue': True}],
                Capabilities=['CAPABILITY_NAMED_IAM'])
            need(created.get('StackId') == STACK, 'CHANGE_SET_STACK_MISMATCH')
            state.update(status='CHANGE_SET_CREATED', change_set_id=created['Id']); save()
            for _ in range(90):
                preview = cf.describe_change_set(ChangeSetName=created['Id'], StackName=STACK)
                if preview['Status'] == 'CREATE_COMPLETE':
                    break
                need(preview['Status'] in ('CREATE_PENDING', 'CREATE_IN_PROGRESS'), 'CHANGE_SET_FAILED')
                sleep(2)
            else:
                raise ValueError('CHANGE_SET_WAIT_LIMIT_NO_RETRY')
            all_changes = pages(cf.describe_change_set, 'Changes', ChangeSetName=created['Id'], StackName=STACK)
            preview['Changes'] = all_changes
            verify_change_set(preview)
            # Recheck all original resource state and document absence just before the write.
            again, current_preserved = preflight(clients, old_journal)
            need(again == new and current_preserved == preserved, 'PREFLIGHT_CHANGED')
            state['status'] = 'EXECUTE_INTENT'; save()
            cf.execute_change_set(ChangeSetName=created['Id'], StackName=STACK,
                ClientRequestToken='repair-' + NEW_SHA, DisableRollback=True)
            state['status'] = 'UPDATE_REQUESTED'; save()
            for _ in range(180):
                status = cf.describe_stacks(StackName=STACK)['Stacks'][0]['StackStatus']
                if status == 'UPDATE_COMPLETE':
                    break
                need(status in ('CREATE_FAILED', 'UPDATE_IN_PROGRESS', 'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS'),
                     'UPDATE_STOPPED_KEEP_RECORDS')
                sleep(5)
            else:
                raise ValueError('UPDATE_WAIT_LIMIT_OBSERVE_ONLY')
            verify_complete(clients, new, preserved)
            state['status'] = 'UPDATE_VERIFIED'; save()
            report = {'status': 'CONNECTION_CREATED', 'account': ACCOUNT, 'region': REGION,
                      'stack_id': STACK, 'main': main, 'template_sha256': NEW_SHA,
                      'recovered_from_template_sha256': OLD_SHA,
                      'hosts': {'backend': 'i-06350403fe0400e1b', 'ocr': 'i-0feac4ca32779b098'},
                      'utc': datetime.now(timezone.utc).isoformat(),
                      'application_installations': 0, 'deployments': 0, 'credential_export': False}
            state['status'] = 'RECEIPT_INTENT'; save()
            clients['s3'].put_object(Bucket=BUCKET, Key='connection/setup.json', Body=canonical(report),
                ContentType='application/json', ServerSideEncryption='AES256', IfNoneMatch='*',
                ExpectedBucketOwner=ACCOUNT)
            state['status'] = 'RECOVERED_VERIFIED'; save()
            return report
        except Exception:
            state['last_stage'] = state['status']; state['status'] = 'STOPPED_KEEP_RECORDS_NO_RETRY'; save()
            raise


def observe(clients, journal):
    """Reconcile uncertain writes without replay, receipt upload, or journal mutation."""
    state = read_json(journal)
    need(state.get('stack_id') == STACK and state.get('old_sha256') == OLD_SHA
         and state.get('new_sha256') == NEW_SHA and isinstance(state.get('preserved'), dict),
         'RECOVERY_JOURNAL_MISMATCH')
    need(clients['sts'].get_caller_identity()['Account'] == ACCOUNT, 'WRONG_ACCOUNT')
    cf = clients['cloudformation']
    stack = cf.describe_stacks(StackName=STACK)['Stacks'][0]
    rows = stack_resources(cf)
    status = stack['StackStatus']
    report = {'status': status, 'last_recorded_stage': state.get('last_stage', state['status']),
              'resources': {k: v['ResourceStatus'] for k, v in rows.items()}, 'writes': 0}
    if status != 'UPDATE_COMPLETE':
        return report
    body = cf.get_template(StackName=STACK, TemplateStage='Original')['TemplateBody']
    if isinstance(body, str): body = json.loads(body)
    need(digest(body) == NEW_SHA, 'FINAL_TEMPLATE_CHANGED')
    verify_complete(clients, body, state['preserved'])
    try:
        response = clients['s3'].get_object(Bucket=BUCKET, Key='connection/setup.json', ExpectedBucketOwner=ACCOUNT)
        need(response['ContentLength'] <= 65536, 'RECEIPT_LIMIT')
        raw = response['Body'].read(65537); need(len(raw) <= 65536, 'RECEIPT_LIMIT')
        receipt = json.loads(raw)
        need(receipt.get('stack_id') == STACK and receipt.get('template_sha256') == NEW_SHA
             and receipt.get('status') == 'CONNECTION_CREATED'
             and receipt.get('main') == state['main'] and receipt.get('account') == ACCOUNT
             and receipt.get('region') == REGION and receipt.get('recovered_from_template_sha256') == OLD_SHA,
             'RECEIPT_MISMATCH')
        report['receipt'] = 'VERIFIED'
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') != 'NoSuchKey': raise
        report['receipt'] = 'MISSING_NO_UPLOAD_PERFORMED'
    report['connection_resources_verified'] = True
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--human-cloudshell', required=True, action='store_true')
    parser.add_argument('--main', help='Required for repair; observation uses the preserved journal')
    parser.add_argument('--observe', action='store_true', help='Read-only reconciliation; no retries or writes')
    args = parser.parse_args()
    need('CLOUDSHELL' in os.environ.get('AWS_EXECUTION_ENV', '').upper(), 'HUMAN_CLOUDSHELL_REQUIRED')
    if not args.observe: verify_github(args.main)
    import boto3
    from botocore.config import Config
    config = Config(connect_timeout=10, read_timeout=30, retries={'total_max_attempts': 1})
    session = boto3.Session(region_name=REGION)
    clients = {s: session.client(s, config=config) for s in ('sts', 'cloudformation', 'ssm', 's3')}
    journal = Path('/home/cloudshell-user/jjikmuk-ssm-regex-recovery.json')
    if args.observe:
        print(json.dumps(observe(clients, journal)))
        return
    old = read_json(Path('/home/cloudshell-user/jjikmuk-operations-setup.json'))
    repair(clients, old, journal, args.main)
    print('CONNECTION_RECOVERED_NO_DOWNLOAD_NO_OPERATOR_SWITCH')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{0,90}', str(error)) else type(error).__name__
        aws_code = getattr(error, 'response', {}).get('Error', {}).get('Code')
        if aws_code in {'ValidationError', 'AccessDenied', 'AccessDeniedException', 'InvalidRequest',
                        'InvalidDocument', 'NoSuchKey', 'PreconditionFailed', 'Throttling', 'ExpiredToken'}:
            print('AWS_CODE: ' + aws_code)
        print('STOP: ' + code + '. Preserve both journals; do not repeat recovery.')
        raise SystemExit(1)
