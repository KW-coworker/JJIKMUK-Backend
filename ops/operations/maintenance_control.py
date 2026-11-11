"""One local command manages approved maintenance through verified latest-main resume.

Uses the existing GitHub login. No AWS keys, CloudShell, unconditional retries,
or work-package replay. A stopped controller leaves the remote hold in place.
"""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
import zipfile
from connection import REPO, canonical, sha
from bootstrap import need
from control import GitHub

PREFIX = '/repos/' + REPO


def save(folder, name, value):
    with (folder / name).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush(); os.fsync(stream.fileno())


def read_plan(api, path, digest, commit):
    need(re.fullmatch(r'ops/operations/plans/[a-z0-9-]{1,80}\.json', path)
         and re.fullmatch('[a-f0-9]{64}', digest), 'MAINTENANCE_PLAN_PATH')
    value = api.call(PREFIX + '/contents/' + path + '?ref=' + commit)
    need(value['type'] == 'file' and value['encoding'] == 'base64' and value['size'] <= 60000,
         'MAINTENANCE_PLAN_CONTENT')
    raw = base64.b64decode(value['content'])
    need(sha(raw) == digest, 'MAINTENANCE_PLAN_HASH')
    plan = json.loads(raw)
    need(plan.get('approved') is True and not plan.get('approval_id', 'PENDING_').startswith('PENDING_'),
         'MAINTENANCE_PLAN_NOT_APPROVED')
    return plan


def artifact(api, run, prefix, member):
    rows = api.call(PREFIX + f'/actions/runs/{run["id"]}/artifacts')['artifacts']
    matches = [a for a in rows if a['name'] == f'{prefix}-{run["id"]}-{run["run_attempt"]}' and not a['expired']]
    need(len(matches) == 1, 'MAINTENANCE_RESULT_MISSING')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cd'))
    from notify import GitHub as ArtifactReader
    raw = ArtifactReader(REPO, api.token).artifact(matches[0]['id'])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        need(len(archive.namelist()) <= 32 and archive.namelist().count(member) == 1
             and archive.getinfo(member).file_size < 65536, 'MAINTENANCE_RESULT_ARCHIVE')
        return json.loads(archive.read(member))


def start_and_wait(api, workflow, inputs, folder, *, approve=False, sleep=time.sleep):
    folder.mkdir(exist_ok=False)
    need(workflow in ('server-maintenance.yml', 'backend-cd.yml'), 'MAINTENANCE_WORKFLOW')
    sha_requested = inputs['expected_sha']
    maintenance = workflow == 'server-maintenance.yml'
    if maintenance:
        inputs = dict(inputs, dispatch_id=uuid.uuid4().hex)
    title = ('Maintenance ' + inputs['mode'] + ' at ' + sha_requested + ' [' + inputs['request_id'] + '] [' + inputs['dispatch_id'] + ']'
             if maintenance else 'Backend CD ' + sha_requested + ' [resume:' + inputs['maintenance_id'] + ']')
    need(api.call(PREFIX + '/git/ref/heads/main')['object']['sha'] == sha_requested, 'MAIN_CHANGED_BEFORE_DISPATCH')
    save(folder, 'dispatch-intent.json', {'workflow': workflow, 'inputs': inputs})
    api.call(PREFIX + '/actions/workflows/' + workflow + '/dispatches', 'POST', {'ref': 'main', 'inputs': inputs})
    # No POST is repeated after a timeout. Inspect this title/request if the response is lost.
    approved = False
    # Catalog phases refresh OIDC within one approved environment job.
    for _ in range(4800 if inputs.get('mode')=='catalog-reapply' else 1920 if inputs.get('mode') in ('catalog','catalog-continue','catalog-reapply') else 1080):
        rows = api.call(PREFIX + '/actions/workflows/' + workflow + '/runs?event=workflow_dispatch&per_page=100')['workflow_runs']
        matches = [r for r in rows if r.get('display_title') == title]
        need(len(matches) <= 1, 'MAINTENANCE_RUN_AMBIGUOUS')
        if matches:
            run = matches[0]
            need(run['head_branch'] == 'main' and (not maintenance or run['head_sha'] == sha_requested) and run['run_attempt'] == 1
                 and run['path'] == '.github/workflows/' + workflow, 'MAINTENANCE_RUN_CHANGED')
            if approve and not approved:
                pending = api.call(PREFIX + f'/actions/runs/{run["id"]}/pending_deployments')
                if pending:
                    need(len(pending) == 1 and pending[0]['environment']['name'] == 'production'
                         and pending[0]['current_user_can_approve'] is True, 'MAINTENANCE_REVIEWER_UNAVAILABLE')
                    save(folder, 'environment-approval-intent.json', {'run_id': run['id'], 'inputs': inputs})
                    api.call(PREFIX + f'/actions/runs/{run["id"]}/pending_deployments', 'POST', {
                        'environment_ids': [pending[0]['environment']['id']], 'state': 'approved',
                        'comment': '사용자가 승인한 고정 작업과 검증·CD 중단/재개 범위의 자동 승인 제출입니다.'})
                    approved = True
            if run['status'] == 'completed':
                save(folder, 'run.json', {k: run[k] for k in ('id', 'head_sha', 'status', 'conclusion', 'run_attempt')})
                need(not approve or approved, 'MAINTENANCE_APPROVAL_NOT_RECORDED')
                return run
        sleep(5)
    raise ValueError('MAINTENANCE_WAIT_LIMIT_KEEP_HOLD_NO_REPLAY')


def execute(api, request, folder, sleep=time.sleep):
    need(set(request) == {'inputs', 'approval'}, 'MAINTENANCE_REQUEST_SCHEMA')
    inputs, approval = request['inputs'], request['approval']
    fields = {'mode', 'expected_sha', 'request_id', 'confirm'}
    if inputs.get('mode') == 'apply': fields |= {'work_plan', 'work_sha256', 'verify_plan', 'verify_sha256'}
    if inputs.get('mode') in ('catalog','catalog-continue','catalog-reapply'): fields |= {'work_plan','work_sha256'}
    need(set(inputs) == fields and inputs['mode'] in ('apply', 'rehearse','catalog','catalog-continue','catalog-reapply')
         and inputs['confirm'] is True and re.fullmatch('[a-f0-9]{32}', inputs['request_id'])
         and re.fullmatch('[a-f0-9]{40}', inputs['expected_sha']), 'MAINTENANCE_INPUTS')
    need(approval.get('status') == 'APPROVED' and approval.get('input_sha256') == sha(canonical(inputs)),
         'MAINTENANCE_EXACT_APPROVAL_REQUIRED')
    need(api.call(PREFIX + '/actions/variables/BACKEND_CD_ENABLED')['value'] == 'true', 'CD_NOT_ENABLED')
    work_sha, verify_sha = plan_hashes(inputs)
    if inputs['mode'] in ('catalog','catalog-continue','catalog-reapply'):
        from catalog_package import validate_source_plan
        validate_source_plan(read_plan(api,inputs['work_plan'],work_sha,inputs['expected_sha']))
    elif inputs['mode'] == 'rehearse':
        from maintenance_probe import rehearsal
        (work_pair, _), (verify_pair, _) = rehearsal(inputs['request_id'])
        work, verify = work_pair[0], verify_pair[0]
    else:
        work = read_plan(api, inputs['work_plan'], work_sha, inputs['expected_sha'])
        verify = read_plan(api, inputs['verify_plan'], verify_sha, inputs['expected_sha'])
    if inputs['mode'] not in ('catalog','catalog-continue','catalog-reapply'):
        need(work['component'] in ('db', 'ocr') and verify['component'] == work['component']
             and work['operation'] in ('deploy', 'install', 'verify') and verify['operation'] == 'verify'
             and work['approval_id'] == verify['approval_id'], 'MAINTENANCE_PLAN_SCOPE')
    folder.mkdir(exist_ok=False)
    save(folder, 'approved-request.json', request)
    run = start_and_wait(api, 'server-maintenance.yml', inputs, folder / 'apply', approve=True, sleep=sleep)
    need(run['conclusion'] == 'success', 'MAINTENANCE_FAILED_COLLECT_BEFORE_RETRY')
    result = artifact(api, run, 'maintenance', 'maintenance-result.json')
    need(result.get('status') == 'VERIFIED_AWAITING_LATEST_MAIN' and result['request_id'] == inputs['request_id']
         and result['commit'] == inputs['expected_sha'] and result['run_id'] == str(run['id'])
         and result['work_sha256'] == work_sha and result['verify_sha256'] == verify_sha,
         'MAINTENANCE_RESULT_IDENTITY')
    save(folder, 'verified-work.json', result)
    current_hash = result['backend_commit_sha256']
    for attempt in range(10):
        main = api.call(PREFIX + '/git/ref/heads/main')['object']['sha']
        if current_hash != sha(main.encode()):
            resume = {'expected_sha': main, 'maintenance_id': inputs['request_id']}
            try:
                run = start_and_wait(api, 'backend-cd.yml', resume, folder / f'resume-{attempt}', sleep=sleep)
            except ValueError as error:
                if str(error) == 'MAIN_CHANGED_BEFORE_DISPATCH': continue
                raise
            if run['conclusion'] != 'success':
                # Only supersession without a server deployment can advance to a new commit.
                latest = api.call(PREFIX + '/git/ref/heads/main')['object']['sha']
                jobs = api.call(PREFIX + f'/actions/runs/{run["id"]}/jobs')['jobs']
                if latest != main and any(j['name'] == 'deploy' and j['conclusion'] == 'skipped' for j in jobs):
                    continue
                if latest != main:
                    outcome = artifact(api, run, 'deployment-result', 'result.json')
                    if outcome.get('status') == 'MAIN_MOVED' and outcome.get('commit') == main:
                        continue
                raise ValueError('MAINTENANCE_RESUME_FAILED_KEEP_HOLD')
            deployed = artifact(api, run, 'deployment-result', 'result.json')
            need(deployed.get('status') == 'SUCCEEDED' and deployed['commit'] == main
                 and deployed['run_id'] == str(run['id']) and deployed['attempt'] == '1', 'MAINTENANCE_DEPLOYMENT_UNCONFIRMED')
            save(folder, f'deployed-{attempt}.json', deployed)
            current_hash = sha(main.encode())
        if api.call(PREFIX + '/git/ref/heads/main')['object']['sha'] != main:
            continue
        need(api.call(PREFIX + '/actions/variables/BACKEND_CD_ENABLED')['value'] == 'true', 'OPERATOR_DISABLED_CD_KEEP_HOLD')
        finish_inputs = {'mode': 'finish', 'expected_sha': main, 'request_id': inputs['request_id'], 'confirm': True}
        try:
            run = start_and_wait(api, 'server-maintenance.yml', finish_inputs, folder / f'finish-{attempt}', approve=True, sleep=sleep)
        except ValueError as error:
            if str(error) == 'MAIN_CHANGED_BEFORE_DISPATCH': continue
            raise
        try:
            need(run['conclusion'] == 'success', 'MAINTENANCE_FINISH_REQUIRES_COLLECTION')
            result = artifact(api, run, 'maintenance', 'maintenance-result.json')
        except Exception:
            observed = collect(api, folder, sleep=sleep)
            if observed['current_main_verified']:
                need(api.call(PREFIX + '/actions/variables/BACKEND_CD_ENABLED')['value'] == 'true', 'OPERATOR_DISABLED_CD')
                result = {'status': 'RESUMED_LATEST_MAIN_VERIFIED', 'request_id': inputs['request_id'],
                          'commit': observed['current_main'], 'collected_after_lost_completion': True}
                save(folder, 'completion.json', result)
                return result
            raise ValueError('MAINTENANCE_FINAL_STATE_COLLECTED_REVIEW_REQUIRED') from None
        need(result.get('request_id') == inputs['request_id'] and result.get('commit') == main, 'MAINTENANCE_FINISH_IDENTITY')
        if result['status'] == 'LATEST_MAIN_MOVED':
            continue
        need(result['status'] == 'RESUMED_LATEST_MAIN_VERIFIED', 'MAINTENANCE_NOT_RESUMED')
        save(folder, 'completion.json', result)
        return result
    raise ValueError('MAIN_CONTINUOUSLY_MOVING_KEEP_HOLD')


def collect(api, folder, sleep=time.sleep):
    request = json.loads((folder / 'approved-request.json').read_bytes())
    inputs = request['inputs']
    need(request['approval'].get('status') == 'APPROVED'
         and request['approval']['input_sha256'] == sha(canonical(inputs)), 'MAINTENANCE_COLLECTION_APPROVAL')
    selected = {'mode': 'collect', 'expected_sha': api.call(PREFIX + '/git/ref/heads/main')['object']['sha'],
                'request_id': inputs['request_id'], 'confirm': True}
    target = folder / ('collect-' + uuid.uuid4().hex)
    run = start_and_wait(api, 'server-maintenance.yml', selected, target, approve=True, sleep=sleep)
    need(run['conclusion'] == 'success', 'MAINTENANCE_FINAL_STATE_UNKNOWN_NO_REPLAY')
    result = artifact(api, run, 'maintenance', 'maintenance-result.json')
    need(result.get('status') == 'MAINTENANCE_STATE_COLLECTED' and result['request_id'] == inputs['request_id'],
         'MAINTENANCE_COLLECTION_IDENTITY')
    from maintenance_gate import validate
    value = validate(result['gate'])
    work_sha, verify_sha = plan_hashes(inputs)
    need(value['request_id'] == inputs['request_id'] and value['commit'] == inputs['expected_sha']
         and value['work_sha256'] == work_sha and value['verify_sha256'] == verify_sha
         and re.fullmatch('[a-f0-9]{40}', result['current_main'])
         and result['current_main_verified'] is (value['state'] == 'OPEN' and
             value['backend_commit_sha256'] == sha(result['current_main'].encode())), 'MAINTENANCE_COLLECTION_PROOF')
    save(target, 'collected-state.json', result)
    return result


def plan_hashes(inputs):
    if inputs['mode'] in ('catalog','catalog-continue','catalog-reapply'):
        return inputs['work_sha256'],sha(canonical({'catalog_verify':inputs['work_sha256']}))
    if inputs['mode'] == 'rehearse':
        from maintenance_probe import rehearsal
        rows = rehearsal(inputs['request_id'])
        return rows[0][1], rows[1][1]
    return inputs['work_sha256'], inputs['verify_sha256']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--request')
    parser.add_argument('--journal', required=True)
    parser.add_argument('--collect', action='store_true', help='Read state only; never replay the approved work')
    args = parser.parse_args(); api = None
    try:
        api = GitHub()
        if args.collect:
            print(json.dumps(collect(api, Path(args.journal))))
        else:
            need(bool(args.request), 'MAINTENANCE_REQUEST_REQUIRED')
            print(json.dumps(execute(api, json.loads(Path(args.request).read_bytes()), Path(args.journal))))
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch('[A-Z_]+', str(error)) else type(error).__name__
        print(json.dumps({'status': 'STOPPED_KEEP_RECORDS_NO_REPLAY', 'code': code}))
        raise SystemExit(1)
    finally:
        if api: api.close()
