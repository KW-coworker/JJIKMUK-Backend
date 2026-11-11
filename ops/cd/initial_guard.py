"""Bounded maintenance lease read from the existing host role's S3 scope."""
from datetime import datetime, timezone
import json
import os
import time
from manifest import require

BUCKET = 'jjikmuk-operations-076767081522-apne2'
ACCOUNT = '076767081522'
REGION = 'ap-northeast-2'
MINIMUM_RESERVE = 5 * 1024**3


def validate_heartbeat(value, binding, now):
    require(set(value) == {'format', 'request_id', 'commit', 'archive_sha256', 'state',
                          'written_epoch', 'metric_epoch', 'minimum_bytes', 'required_bytes'}, 'MAINTENANCE_LEASE_FIELDS')
    require(value['format'] == 1 and all(value[k] == binding[k] for k in
            ('request_id', 'commit', 'archive_sha256')), 'MAINTENANCE_LEASE_BINDING')
    require(value['state'] == 'PROCEED', 'MAINTENANCE_MONITOR_STOPPED')
    for key in ('written_epoch', 'metric_epoch', 'minimum_bytes', 'required_bytes'):
        require(type(value[key]) is int and 0 <= value[key] < 2**63, 'MAINTENANCE_LEASE_NUMBER')
    require(-5 <= now - value['written_epoch'] <= 90 and 0 <= now - value['metric_epoch'] <= 240,
            'MAINTENANCE_MONITOR_STALE')
    require(value['required_bytes'] == binding['required_bytes'] and value['required_bytes'] >= MINIMUM_RESERVE
            and value['minimum_bytes'] >= value['required_bytes'],
            'MAINTENANCE_STORAGE_RESERVE')


class Guard:
    def __init__(self, client, binding, *, clock=time.time, monotonic=time.monotonic,
                 read_attempts=1, budget_check=lambda: None):
        require(type(read_attempts) is int and read_attempts in (1,2), 'MAINTENANCE_READ_ATTEMPTS')
        self.client, self.binding = client, binding
        self.clock, self.monotonic = clock, monotonic
        self.cached, self.read_at = None, None
        self.read_attempts,self.budget_check=read_attempts,budget_check
        self.key = ('operations/bootstrap/' + binding['archive_sha256'] + '/monitor-'
                    + binding['request_id'] + '.json')

    def __call__(self):
        self.budget_check()
        now = self.monotonic()
        if self.read_at is None or now - self.read_at >= 5:
            transport=()
            if self.read_attempts==2:
                from botocore.exceptions import ConnectionClosedError,ConnectTimeoutError,ReadTimeoutError,EndpointConnectionError
                transport=(ConnectionClosedError,ConnectTimeoutError,ReadTimeoutError,EndpointConnectionError)
            for attempt in range(self.read_attempts):
                self.budget_check()
                try:
                    response = self.client.get_object(Bucket=BUCKET, Key=self.key, ExpectedBucketOwner=ACCOUNT)
                    with response['Body'] as body:
                        require(response['ContentLength'] <= 2048, 'MAINTENANCE_LEASE_SIZE')
                        raw = body.read(2049)
                    require(len(raw) <= 2048, 'MAINTENANCE_LEASE_SIZE')
                    value=json.loads(raw)
                    self.budget_check()
                    validate_heartbeat(value,self.binding,self.clock())
                    self.cached=value;self.read_at=self.monotonic()
                    break
                except transport:
                    self.budget_check()
                    if attempt+1==self.read_attempts:raise
        validate_heartbeat(self.cached, self.binding, self.clock())
        self.budget_check()


def load_sdk(stage):
    """Load reviewed pure wheels in this process; do not install into the host env."""
    import sys
    from host import secure
    from manifest import digest
    lock = stage / 'vendor/sdk-lock.json'
    secure(lock)
    files = json.loads(lock.read_bytes())
    require(len(files) == 7, 'INITIAL_SDK_COUNT')
    wheels = []
    for name, expected in files.items():
        require('/' not in name and '\\' not in name and name.endswith('.whl'), 'INITIAL_SDK_NAME')
        path = stage / 'vendor' / name
        secure(path)
        require(digest(path) == expected, 'INITIAL_SDK_HASH')
        wheels.append(path)
    # Botocore loads service JSON by filesystem path and cannot be zip-imported.
    # Expand verified wheels into this isolated stage, never site-packages.
    import zipfile
    import stat
    from pathlib import PurePosixPath
    from host import atomic_json
    sdk = stage / 'sdk'
    manifest_path = stage / 'sdk-files.json'
    if not sdk.exists():
        require(not sdk.is_symlink() and not manifest_path.exists(), 'INITIAL_SDK_STAGE_EXISTS')
        entries, total = {}, 0
        for wheel in wheels:
            with zipfile.ZipFile(wheel) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    path = PurePosixPath(info.filename)
                    require(not path.is_absolute() and '..' not in path.parts and '\\' not in info.filename
                            and str(path) == info.filename and info.filename not in entries
                            and not stat.S_ISLNK(info.external_attr >> 16), 'INITIAL_SDK_MEMBER')
                    total += info.file_size
                    require(len(entries) < 10000 and total < 128*1024**2, 'INITIAL_SDK_EXPANSION_LIMIT')
                    entries[info.filename] = (wheel, info.filename)
        sdk.mkdir(mode=0o755)
        os.chmod(sdk, 0o755)
        hashes = {}
        for name, (wheel, member) in entries.items():
            target = sdk / name
            for parent in reversed(target.parents):
                if sdk in parent.parents and not parent.exists():
                    parent.mkdir(mode=0o755); os.chmod(parent, 0o755)
            with zipfile.ZipFile(wheel) as archive, target.open('xb') as out:
                out.write(archive.read(member))
            os.chmod(target, 0o644)
            hashes[name] = digest(target)
        atomic_json(manifest_path, hashes)
    secure(sdk); secure(manifest_path)
    hashes = json.loads(manifest_path.read_bytes())
    require(0 < len(hashes) <= 10000, 'INITIAL_SDK_MANIFEST_LIMIT')
    for name, expected in hashes.items():
        path = PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and str(path) == name, 'INITIAL_SDK_MANIFEST_PATH')
        target = sdk / name
        secure(target)
        require(digest(target) == expected, 'INITIAL_SDK_EXPANSION_CHANGED')
    sys.path.insert(0, str(sdk))


def host_s3(stage):
    load_sdk(stage)
    # Explicitly exclude root's profiles/configuration. Only the existing EC2 role is used.
    for name in tuple(os.environ):
        if name.startswith('AWS_'):
            del os.environ[name]
    os.environ.update(AWS_SHARED_CREDENTIALS_FILE='/dev/null', AWS_CONFIG_FILE='/dev/null', BOTO_CONFIG='/dev/null',
                      AWS_EC2_METADATA_V1_DISABLED='true', AWS_DEFAULT_REGION=REGION)
    import boto3
    from botocore.config import Config
    session = boto3.Session(region_name=REGION)
    credentials = session.get_credentials()
    require(credentials is not None and credentials.method == 'iam-role', 'ONLY_INSTANCE_ROLE_ALLOWED')
    identity = session.client('sts', config=Config(connect_timeout=3, read_timeout=5,
                              retries={'total_max_attempts': 1})).get_caller_identity()
    require(identity['Account'] == ACCOUNT and identity['Arn'] ==
            'arn:aws:sts::076767081522:assumed-role/JjikmukMigrationHost/i-06350403fe0400e1b',
            'INITIAL_HOST_ROLE_MISMATCH')
    config = Config(connect_timeout=3, read_timeout=5, retries={'total_max_attempts': 1},
                    signature_version='s3v4', s3={'addressing_style': 'virtual'})
    return session.client('s3', endpoint_url='https://s3.ap-northeast-2.amazonaws.com', config=config)
