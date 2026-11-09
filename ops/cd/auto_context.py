"""Main-only automatic release identity and read-only backup selection."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import urllib.request
from manifest import require

REPOSITORY = 'KW-coworker/JJIKMUK-Backend'
ACCOUNT = '076767081522'
REGION = 'ap-northeast-2'
BUCKET = 'jjikmuk-operations-076767081522-apne2'
PREFIX = 'artifacts/backend'
INSTANCE = 'i-06350403fe0400e1b'
DOCUMENT = 'Jjikmuk-BackendDeploy-v1'
DATABASE = 'jjikmuk-dev-db'


def env(name, pattern):
    value = os.environ.get(name, '')
    require(re.fullmatch(pattern, value) is not None, 'INVALID_RELEASE_INPUT')
    return value


def identity():
    return (env('GITHUB_SHA', r'[0-9a-f]{40}'), env('GITHUB_RUN_ID', r'[1-9][0-9]{0,19}'),
            env('GITHUB_RUN_ATTEMPT', r'[1-9][0-9]{0,3}'))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('GITHUB_REDIRECT')


def main_head():
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'JJIKMUK-CD'}
    token = os.environ.get('GH_TOKEN')
    if token: headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/git/ref/heads/main', headers=headers)
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
        data = response.read(65537)
        require(len(data) <= 65536, 'GITHUB_RESPONSE_LIMIT')
        return json.loads(data)['object']['sha']


def guard(deployment=True):
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and
            os.environ.get('GITHUB_REPOSITORY_ID') == '1300060655' and
            os.environ.get('GITHUB_REF') == 'refs/heads/main' and
            os.environ.get('GITHUB_WORKFLOW_REF') == REPOSITORY + '/.github/workflows/backend-cd.yml@refs/heads/main',
            'MAIN_WORKFLOW_ONLY')
    sha, _, _ = identity()
    event = os.environ.get('GITHUB_EVENT_NAME')
    require(event in ('push', 'workflow_dispatch'), 'UNSUPPORTED_EVENT')
    if event == 'push':
        path = Path(os.environ.get('GITHUB_EVENT_PATH', ''))
        require(path.is_file() and path.stat().st_size <= 25*1024*1024, 'PUSH_EVENT_REQUIRED')
        payload = json.loads(path.read_text(encoding='utf-8'))
        require(payload.get('after') == sha and payload.get('ref') == 'refs/heads/main' and
                payload.get('deleted') is False and payload.get('forced') is False and
                payload.get('repository', {}).get('id') == 1300060655, 'PUSH_EVENT_MISMATCH')
    if deployment:
        require(event == 'push', 'AUTOMATIC_PUSH_ONLY')
        require(os.environ.get('CD_ENABLED') == 'true', 'CD_DISABLED')
    require(main_head() == sha, 'MAIN_MOVED')


def snapshot_time(snapshot):
    value = snapshot['SnapshotCreateTime']
    return value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))


def check_snapshot(snapshot, account, database, now):
    require(snapshot.get('Status') == 'available' and snapshot.get('Encrypted') is True, 'BACKUP_NOT_READY')
    require(snapshot.get('DBInstanceIdentifier') == database and
            snapshot.get('DBSnapshotArn', '').startswith(f'arn:aws:rds:{REGION}:{account}:snapshot:'), 'WRONG_BACKUP')
    require(snapshot.get('SnapshotType', 'manual') in ('manual', 'automated'), 'BACKUP_NOT_OWNED')
    age = (now - snapshot_time(snapshot)).total_seconds()
    require(0 <= age <= 86400, 'BACKUP_TOO_OLD')


def select_snapshot(rds, now=None):
    now = now or datetime.now(timezone.utc)
    candidates, marker, seen = [], None, set()
    for _ in range(100):
        args = {'DBInstanceIdentifier': DATABASE, 'IncludeShared': False, 'IncludePublic': False, 'MaxRecords': 100}
        if marker: args['Marker'] = marker
        result = rds.describe_db_snapshots(**args)
        for snapshot in result.get('DBSnapshots', []):
            try: check_snapshot(snapshot, ACCOUNT, DATABASE, now)
            except (ValueError, KeyError, TypeError): continue
            candidates.append(snapshot)
        marker = result.get('Marker')
        if not marker: break
        require(marker not in seen, 'BACKUP_PAGINATION_LOOP')
        seen.add(marker)
    else: raise ValueError('BACKUP_PAGE_LIMIT')
    require(bool(candidates), 'NO_FRESH_ENCRYPTED_BACKUP')
    selected = max(candidates, key=lambda s: (snapshot_time(s), s['DBSnapshotArn']))
    return {'arn': selected['DBSnapshotArn'], 'created_at': snapshot_time(selected).isoformat()}
