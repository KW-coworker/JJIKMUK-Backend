"""Durable maintenance hold shared by manual operations and automatic backend CD.

S3 versions preserve history. Conditional writes prevent a second owner from
replacing an active hold; expiration never releases an uncertain operation.
"""
import hashlib
import json
import re
import uuid
from auto_context import ACCOUNT, BUCKET
from manifest import require

KEY = 'receipts/backend-cd/maintenance.json'
FIELDS = {'format', 'state', 'request_id', 'commit', 'run_id', 'work_sha256',
          'verify_sha256', 'backend_commit_sha256', 'verification_sha256',
          'transition_id', 'finish_verification_sha256'}


def validate(value):
    require(type(value) is dict and set(value) == FIELDS and value['format'] == 1,
            'MAINTENANCE_STATE_SCHEMA')
    require(value['state'] in {'WORKING', 'VERIFIED', 'OPEN'}, 'MAINTENANCE_STATE')
    for key, pattern in [('request_id', '[a-f0-9]{32}'), ('commit', '[a-f0-9]{40}'),
                         ('run_id', '[1-9][0-9]{0,19}'), ('work_sha256', '[a-f0-9]{64}'),
                         ('verify_sha256', '[a-f0-9]{64}'), ('transition_id', '[a-f0-9]{32}')]:
        require(isinstance(value[key], str) and re.fullmatch(pattern, value[key]), 'MAINTENANCE_IDENTITY')
    proof = value['backend_commit_sha256']
    require(proof is None if value['state'] == 'WORKING' else
            isinstance(proof, str) and re.fullmatch('[a-f0-9]{64}', proof), 'MAINTENANCE_BACKEND_PROOF')
    proof = value['verification_sha256']
    require(proof is None if value['state'] == 'WORKING' else
            isinstance(proof, str) and re.fullmatch('[a-f0-9]{64}', proof), 'MAINTENANCE_VERIFICATION_PROOF')
    proof = value['finish_verification_sha256']
    require(isinstance(proof, str) and re.fullmatch('[a-f0-9]{64}', proof) if value['state'] == 'OPEN'
            else proof is None, 'MAINTENANCE_FINISH_VERIFICATION')
    return value


class Gate:
    def __init__(self, s3):
        self.s3 = s3

    def read(self):
        listed = self.s3.list_objects_v2(Bucket=BUCKET, Prefix=KEY, MaxKeys=2, ExpectedBucketOwner=ACCOUNT)
        if not any(row['Key'] == KEY for row in listed.get('Contents', [])):
            return None, None
        response = self.s3.get_object(Bucket=BUCKET, Key=KEY, ExpectedBucketOwner=ACCOUNT)
        with response['Body'] as stream:
            raw = stream.read(4097)
        require(len(raw) <= 4096 and isinstance(response.get('ETag'), str), 'MAINTENANCE_STATE_LIMIT')
        return validate(json.loads(raw)), response['ETag']

    def write(self, value, etag):
        value = dict(value, transition_id=uuid.uuid4().hex)
        validate(value)
        condition = {'IfMatch': etag} if etag is not None else {'IfNoneMatch': '*'}
        # A lost response is collected by reading, never unconditionally written again.
        try:
            self.s3.put_object(Bucket=BUCKET, Key=KEY, ExpectedBucketOwner=ACCOUNT,
                               Body=json.dumps(value, sort_keys=True).encode(),
                               ContentType='application/json', ServerSideEncryption='AES256', **condition)
        except Exception:
            pass  # The write might have succeeded. Only read the exact nonce back.
        for _ in range(3):
            try:
                observed, _ = self.read()
                if observed == value:
                    return
            except Exception:
                pass
        raise ValueError('MAINTENANCE_STATE_WRITE_UNKNOWN_COLLECT_ONLY')

    def start(self, request_id, commit, run_id, work_sha256, verify_sha256):
        previous, etag = self.read()
        require(previous is None or previous['state'] == 'OPEN', 'MAINTENANCE_ALREADY_ACTIVE')
        require(previous is None or previous['request_id'] != request_id, 'MAINTENANCE_NO_REPLAY')
        value = dict(format=1, state='WORKING', request_id=request_id, commit=commit,
                        run_id=run_id, work_sha256=work_sha256, verify_sha256=verify_sha256,
                        backend_commit_sha256=None, verification_sha256=None,
                        transition_id=uuid.uuid4().hex, finish_verification_sha256=None)
        validate(value)
        self.s3.put_object(Bucket=BUCKET, Key='receipts/backend-cd/maintenance-requests/' + request_id + '.json',
                           ExpectedBucketOwner=ACCOUNT, Body=json.dumps(value, sort_keys=True).encode(),
                           ContentType='application/json', ServerSideEncryption='AES256', IfNoneMatch='*')
        self.write(value, etag)

    def verified(self, request_id, backend_commit_sha256, verification_sha256):
        value, etag = self.read()
        require(value is not None and value['state'] == 'WORKING' and value['request_id'] == request_id,
                'MAINTENANCE_OWNER_CHANGED')
        self.write(dict(value, state='VERIFIED', backend_commit_sha256=backend_commit_sha256,
                        verification_sha256=verification_sha256), etag)

    def admission(self, request_id=''):
        value, _ = self.read()
        if request_id:
            require(value is not None and value['state'] == 'VERIFIED' and value['request_id'] == request_id,
                    'MAINTENANCE_RESUME_NOT_VERIFIED')
        return value

    def deployed(self, request_id, commit):
        value, etag = self.read()
        require(value is not None and value['state'] == 'VERIFIED' and value['request_id'] == request_id,
                'MAINTENANCE_OWNER_CHANGED')
        self.write(dict(value,
                        backend_commit_sha256=hashlib.sha256(commit.encode()).hexdigest()), etag)

    def finish(self, request_id, backend_commit_sha256, verification_sha256):
        value, etag = self.read()
        require(value is not None and value['state'] == 'VERIFIED' and value['request_id'] == request_id
                and value['backend_commit_sha256'] == backend_commit_sha256, 'MAINTENANCE_FINISH_PROOF')
        self.write(dict(value, state='OPEN', finish_verification_sha256=verification_sha256), etag)

    def manual_admission(self, request_id, workflow):
        value, _ = self.read()
        if value is not None and value['state'] != 'OPEN':
            require(workflow.endswith('/.github/workflows/server-maintenance.yml@refs/heads/main')
                    and value['request_id'] == request_id, 'MAINTENANCE_BLOCKS_OTHER_OPERATION')
