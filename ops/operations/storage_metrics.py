"""Fixed RDS FreeStorageSpace observation. No instance, IAM or database writes."""
from datetime import datetime, timedelta, timezone
import json
import math
import os
from connection import ACCOUNT, REGION, REPO, WRITE_ROLE
from bootstrap import need

DB = 'jjikmuk-dev-db'


def observe(client, now):
    need(now.tzinfo is not None, 'METRIC_CLOCK_REQUIRED')
    start = (now - timedelta(minutes=5)).replace(second=0, microsecond=0)
    response = client.get_metric_statistics(Namespace='AWS/RDS', MetricName='FreeStorageSpace',
        Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': DB}],
        StartTime=start, EndTime=now, Period=60,
        Statistics=['Minimum'], Unit='Bytes')
    rows = response.get('Datapoints', [])
    need(response.get('Label') == 'FreeStorageSpace' and 2 <= len(rows) <= 6,
         'STORAGE_METRICS_MISSING')
    points = []
    for row in rows:
        stamp, minimum = row.get('Timestamp'), row.get('Minimum')
        need(isinstance(stamp, datetime) and stamp.tzinfo is not None
             and row.get('Unit') == 'Bytes' and type(minimum) in (int, float)
             and math.isfinite(minimum) and 0 <= minimum < 2**63, 'STORAGE_METRIC_INVALID')
        age = (now - stamp).total_seconds()
        need(0 <= age and stamp >= start, 'STORAGE_METRIC_OUTSIDE_WINDOW')
        points.append((stamp, int(minimum)))
    points.sort()
    need(len({x[0] for x in points}) == len(points), 'STORAGE_METRIC_DUPLICATE')
    need((now - points[-1][0]).total_seconds() <= 180, 'STORAGE_METRIC_STALE')
    need((points[-1][0] - points[-2][0]).total_seconds() <= 120, 'STORAGE_METRIC_GAP')
    return {'status': 'OK', 'checks': {'fresh_metric': True}, 'counts': {
        'latest_bytes': points[-1][1], 'window_minimum_bytes': min(v for _, v in points),
        'sample_epoch': int(points[-1][0].timestamp()),
        'sample_age_seconds': int((now - points[-1][0]).total_seconds()), 'samples': len(points)},
        'codes': ['FIXED_RDS_STORAGE_READ_ONLY', 'CAPACITY_GATE_REQUIRES_TABLE_SIZE_AND_LIVE_MONITOR']}


def main():
    from run import context, save_local
    import boto3
    from botocore.config import Config
    context(os.environ['EXPECTED_SHA'], True)
    need(os.environ.get('GITHUB_WORKFLOW_REF') == REPO + '/.github/workflows/server-operations.yml@refs/heads/main'
         and os.environ.get('OPERATION_MODE') == 'storage', 'STORAGE_WORKFLOW_REQUIRED')
    session = boto3.Session(region_name=REGION, aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'], aws_session_token=os.environ['AWS_SESSION_TOKEN'])
    config = Config(connect_timeout=10, read_timeout=20, retries={'total_max_attempts': 1})
    identity = session.client('sts', config=config).get_caller_identity()
    need(identity['Account'] == ACCOUNT and identity['Arn'].startswith(
        f'arn:aws:sts::{ACCOUNT}:assumed-role/{WRITE_ROLE}/'), 'STORAGE_IDENTITY_MISMATCH')
    result = observe(session.client('cloudwatch', config=config), datetime.now(timezone.utc))
    save_local('storage.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        from run import save_local
        code = getattr(error, 'response', {}).get('Error', {}).get('Code')
        report = {'status': 'STOPPED', 'codes': [
            'CLOUDWATCH_READ_PERMISSION_REQUIRED' if code in ('AccessDenied', 'AccessDeniedException')
            else 'STORAGE_READ_FAILED_NO_CHANGES']}
        save_local('storage-failure.json', report)
        print(json.dumps(report))
        raise SystemExit(1)
