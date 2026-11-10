"""Run pinned approved work, verify it, and retain a hold until latest-main CD succeeds."""
import json
import os
from pathlib import Path
import re
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cd'))
from maintenance_gate import Gate
from maintenance_probe import plan as probe_plan, drained, rehearsal
from connection import REPO, REPO_ID, HOSTS, canonical, sha
from bootstrap import need, github
from run import clients, execute, load_plan, save_local


def context():
    e = os.environ
    need(e.get('GITHUB_ACTIONS') == 'true' and e.get('GITHUB_REPOSITORY') == REPO and e.get('GITHUB_REPOSITORY_ID') == str(REPO_ID)
         and e.get('GITHUB_REF') == 'refs/heads/main' and e.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
         and e.get('GITHUB_WORKFLOW_REF') == REPO + '/.github/workflows/server-maintenance.yml@refs/heads/main'
         and e.get('GITHUB_RUN_ATTEMPT') == '1' and e.get('OPERATIONS_CONFIRM') == 'true', 'MAINTENANCE_CONTEXT')
    commit = e.get('EXPECTED_SHA', '')
    request = e.get('OPERATIONS_REQUEST_ID', '')
    need(re.fullmatch('[a-f0-9]{40}', commit) and commit == e.get('GITHUB_SHA')
         and re.fullmatch('[a-f0-9]{32}', request)
         and re.fullmatch('[a-f0-9]{32}', e.get('OPERATIONS_DISPATCH_ID', '')), 'MAINTENANCE_EXACT_PLAN')
    # The approved plan stays pinned while other PRs may advance main during the wait.
    return {'commit': commit, 'run_id': e['GITHUB_RUN_ID'], 'attempt': '1', 'request_id': request}


def checked_execute(api, ctx, plan, digest, target, prefix):
    result = execute(api, ctx, plan, digest, target, output_prefix=prefix)
    need(result['success'], 'MAINTENANCE_STEP_FAILED_KEEP_HOLD')
    report = json.loads((Path('operation-results') / (prefix + 'result.json')).read_bytes())['report']
    need(report.get('checks') and all(x is True for x in report['checks'].values()), 'MAINTENANCE_CHECKS_FAILED')
    return report


def perform(api, ctx, work, verification, work_sha, verify_sha, sleep=time.sleep):
    need(work[0]['component'] in ('db', 'ocr') and verification[0]['component'] == work[0]['component']
         and work[0]['operation'] in ('deploy', 'install', 'verify')
         and verification[0]['operation'] == 'verify'
         and work[0]['approval_id'] == verification[0]['approval_id'], 'MAINTENANCE_PLAN_SCOPE')
    gate = Gate(api['s3'])
    gate.start(ctx['request_id'], ctx['commit'], ctx['run_id'], work_sha, verify_sha)
    for _ in range(90):
        if drained(api['ssm'], list(HOSTS.values())):
            break
        sleep(10)
    else:
        raise ValueError('SSM_DRAIN_TIMEOUT_KEEP_HOLD')
    for phase, prefix in [('before', 'maintenance-before-'), ('after', 'maintenance-after-')]:
        probe = probe_plan(ctx['request_id'], phase)
        report = checked_execute(api, ctx, probe, sha(canonical(probe)), HOSTS['backend'], prefix)
        if phase == 'before':
            checked_execute(api, ctx, work[0], work_sha, work[1], 'maintenance-work-')
            checked_execute(api, ctx, verification[0], verify_sha, verification[1], 'maintenance-verify-')
    files = sorted(Path('operation-results').glob('maintenance-*.json'))
    evidence = sha(canonical({p.name: sha(p.read_bytes()) for p in files}))
    gate.verified(ctx['request_id'], report['hashes']['backend_commit_sha256'], evidence)
    result = {'status': 'VERIFIED_AWAITING_LATEST_MAIN', 'request_id': ctx['request_id'],
              'commit': ctx['commit'], 'run_id': ctx['run_id'], 'work_sha256': work_sha,
              'verify_sha256': verify_sha, 'backend_commit_sha256': report['hashes']['backend_commit_sha256']}
    save_local('maintenance-result.json', result)
    return result


def finish(api, ctx):
    need(os.environ.get('CD_ENABLED') == 'true', 'OPERATOR_DISABLED_CD_KEEP_HOLD')
    gate = Gate(api['s3'])
    state = gate.admission(ctx['request_id'])
    if github('git/ref/heads/main')['object']['sha'] != ctx['commit']:
        return {'status': 'LATEST_MAIN_MOVED', 'request_id': ctx['request_id'], 'commit': ctx['commit']}
    need(state['backend_commit_sha256'] == sha(ctx['commit'].encode()), 'LATEST_MAIN_NOT_DEPLOYED')
    probe = probe_plan(ctx['request_id'], 'finish-' + ctx['run_id'])
    report = checked_execute(api, ctx, probe, sha(canonical(probe)), HOSTS['backend'], 'maintenance-after-')
    need(report['hashes']['backend_commit_sha256'] == sha(ctx['commit'].encode()), 'CURRENT_BACKEND_NOT_LATEST')
    if github('git/ref/heads/main')['object']['sha'] != ctx['commit']:
        return {'status': 'LATEST_MAIN_MOVED', 'request_id': ctx['request_id'], 'commit': ctx['commit']}
    evidence = sha(canonical({p.name: sha(p.read_bytes()) for p in
                             sorted(Path('operation-results').glob('maintenance-after-*.json'))}))
    gate.finish(ctx['request_id'], report['hashes']['backend_commit_sha256'], evidence)
    return {'status': 'RESUMED_LATEST_MAIN_VERIFIED', 'request_id': ctx['request_id'],
            'commit': ctx['commit'], 'run_id': ctx['run_id']}


def collect_state(api, ctx):
    value, _ = Gate(api['s3']).read()
    need(value is not None and value['request_id'] == ctx['request_id'], 'MAINTENANCE_COLLECTION_OWNER_CHANGED')
    current = github('git/ref/heads/main')['object']['sha']
    return {'status': 'MAINTENANCE_STATE_COLLECTED', 'request_id': ctx['request_id'],
            'gate': value, 'current_main': current,
            'current_main_verified': value['state'] == 'OPEN' and value['backend_commit_sha256'] == sha(current.encode())}


if __name__ == '__main__':
    try:
        ctx = context()
        if os.environ.get('MAINTENANCE_MODE') in ('finish', 'collect'):
            action = finish if os.environ['MAINTENANCE_MODE'] == 'finish' else collect_state
            result = action(clients(True), ctx)
            save_local('maintenance-result.json', result)
        else:
            need(os.environ.get('MAINTENANCE_MODE') in ('apply', 'rehearse'), 'MAINTENANCE_MODE')
            if os.environ['MAINTENANCE_MODE'] == 'rehearse':
                (work, work_sha), (verification, verify_sha) = rehearsal(ctx['request_id'])
            else:
                work_sha, verify_sha = os.environ['WORK_SHA256'], os.environ['VERIFY_SHA256']
                work = load_plan(os.environ['WORK_PLAN'], work_sha)
                verification = load_plan(os.environ['VERIFY_PLAN'], verify_sha)
            result = perform(clients(True), ctx, work, verification, work_sha, verify_sha)
        print(json.dumps(result))
    except Exception:
        print('MAINTENANCE_STOPPED_COLLECT_STATE_AND_RECORDS_NO_REPLAY')
        raise SystemExit(1)
