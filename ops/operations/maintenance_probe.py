"""Fixed installed-backend verification before/after an approved manual operation."""
import re
from bootstrap import need


def plan(request_id, phase):
    need(re.fullmatch('[a-f0-9]{32}', request_id) and
         (phase in ('before', 'after', 'rehearse-work', 'rehearse-verify') or
          re.fullmatch('finish-[1-9][0-9]{0,19}', phase)), 'MAINTENANCE_PROBE_ID')
    script = '''import hashlib,json,os,re,stat,sys
from pathlib import Path
root=Path('/opt/jjikmuk-cd/bin')
for p in [root,*root.parents]:
    s=p.lstat()
    assert not p.is_symlink() and s.st_uid==0 and not s.st_mode & 0o022 and stat.S_ISDIR(s.st_mode)
sys.dont_write_bytecode=True
sys.path.insert(0,str(root))
from deploy import load_config
from host import Host,deployment_lock
with deployment_lock('/opt/jjikmuk-cd',OPERATION_ID) as guard:
    host=Host(load_config())
    host.verify(host.baseline,'')
    commit=host.baseline['manifest']['commit']
    assert re.fullmatch('[a-f0-9]{40}',commit)
    guard.record('VERIFIED')
    print(json.dumps({'status':'VERIFIED','checks':{'backend_current_verified':True,
        'database_verified':True,'health_verified':True,'stable_process_60_seconds':True},
        'hashes':{'backend_commit_sha256':hashlib.sha256(commit.encode()).hexdigest()}}))
'''
    from connection import sha
    script = 'OPERATION_ID=' + repr(sha((request_id + ':' + phase).encode())) + '\n' + script
    return {'format': 1, 'component': 'backend', 'operation': 'verify', 'approved': True,
            'approval_id': 'MAINTENANCE_BOUNDARY_' + request_id.upper(),
            'document': {'schemaVersion': '2.2', 'parameters': {},
                'description': 'Maintenance boundary ' + request_id + ' ' + phase,
                'mainSteps': [{'action': 'aws:runShellScript', 'name': 'report', 'inputs': {
                    'timeoutSeconds': '300', 'runCommand': [
                        "/usr/bin/python3 -I -S -B - <<'JJIKMUK_MAINTENANCE_PROBE'\n" + script +
                        '\nJJIKMUK_MAINTENANCE_PROBE']}}]}}


def drained(ssm, instances):
    """SSM can outlive a cancelled GitHub runner. No new work until it is terminal."""
    busy = False
    for instance in instances:
        token = None
        for _ in range(100):
            args = {'InstanceId': instance, 'MaxResults': 50}
            if token:
                args['NextToken'] = token
            page = ssm.list_commands(**args)
            for row in page.get('Commands', []):
                status = row['Status']
                need(status in {'Pending', 'InProgress', 'Delayed', 'Cancelling', 'Success',
                                'Cancelled', 'Failed', 'TimedOut'}, 'SSM_STATUS_UNKNOWN')
                busy = busy or status in {'Pending', 'InProgress', 'Delayed', 'Cancelling'}
            token = page.get('NextToken')
            if not token:
                break
        else:
            raise ValueError('SSM_HISTORY_LIMIT')
    return not busy


def rehearsal(request_id):
    """Only installed runtime/DB/health reads, no SQL mutation, model change or restart."""
    from connection import canonical, sha, HOSTS
    rows = []
    for phase in ('rehearse-work', 'rehearse-verify'):
        value = plan(request_id, phase)
        value.update(component='db', approval_id='MAINTENANCE_REHEARSAL_' + request_id.upper())
        rows.append(((value, HOSTS['backend']), sha(canonical(value))))
    return rows
