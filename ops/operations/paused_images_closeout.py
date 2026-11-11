"""Accept the user-paused, verified image boundary before normal latest-main CD."""
import json
from pathlib import Path

from bootstrap import github, need
from connection import HOSTS, canonical, sha
from maintenance_gate import Gate
from maintenance_probe import drained
from run import execute, save_local

REQUEST = 'a5291163ee0a456b85366e6075d8fce6'
IMAGE_RUN = '43069183840'
SEED = '47fe6ee1d5896dfadfc6eedc02629845b4b690c724aaa0f646dcec885e85b051'


def document(operation):
    source = Path(__file__).with_name('paused_images_host.py').read_text(encoding='utf-8')
    # This reviewed source is embedded in the fixed, parameter-free SSM document.
    script = 'OPERATION=' + repr(operation) + '\nSEED=' + repr(SEED) + '\n' + source
    need(len(script.encode()) < 58000, 'PAUSED_CLOSEOUT_DOCUMENT_SIZE')
    return {'schemaVersion': '2.2', 'parameters': {},
            'description': 'Verify accepted partial images and current services; observe chatbot installation inputs',
            'mainSteps': [{'action': 'aws:runShellScript', 'name': 'report', 'inputs': {
                'timeoutSeconds': '420', 'runCommand': [
                    "/usr/bin/python3.12 -I -S -B - <<'JJIKMUK_PAUSED_IMAGES'\n" + script + '\nJJIKMUK_PAUSED_IMAGES']}}]}


def perform(api, ctx):
    gate = Gate(api['s3'])
    before, _ = gate.read()
    need(ctx['request_id'] == REQUEST and before is not None and before['request_id'] == REQUEST
         and before['state'] == 'WORKING' and before['run_id'] == '43041472793', 'PAUSED_CLOSEOUT_HOLD')
    run = github('actions/runs/' + IMAGE_RUN)
    need(str(run['id']) == IMAGE_RUN and run['status'] == 'completed' and run['conclusion'] == 'cancelled',
         'IMAGE_RUN_NOT_CANCELLED')
    need(drained(api['ssm'], list(HOSTS.values())), 'PAUSED_CLOSEOUT_SSM_BUSY')
    operation = sha((REQUEST + ':paused-images-closeout:' + ctx['run_id']).encode())
    plan = {'format': 1, 'component': 'backend', 'operation': 'verify', 'approved': True,
            'approval_id': 'USER_RESUME_BACKEND_AND_CHATBOT_20261112', 'document': document(operation)}
    result = execute(api, ctx, plan, sha(canonical(plan)), HOSTS['backend'])
    need(result['success'], 'PAUSED_CLOSEOUT_HOST_FAILED')
    report = json.loads(Path('operation-results/result.json').read_bytes())['report']
    need(report['status'] == 'VERIFIED' and report['checks'] and all(v is True for v in report['checks'].values())
         and report['counts']['checked_rows'] == 241000 and report['counts']['changed_rows'] == 236207,
         'PAUSED_CLOSEOUT_PROOF')
    need(gate.read()[0] == before, 'PAUSED_CLOSEOUT_HOLD_CHANGED')
    evidence = {'accepted_partial_images': True, 'image_run_cancelled': IMAGE_RUN,
                'report': report, 'request_id': REQUEST, 'commit': ctx['commit'], 'run_id': ctx['run_id']}
    save_local('paused-closeout-proof.json', evidence)
    gate.verified(REQUEST, report['hashes']['backend_commit_sha256'], sha(canonical(evidence)))
    return {'status': 'VERIFIED_AWAITING_LATEST_MAIN', 'request_id': REQUEST,
            'image_work_remains_paused': True, 'remaining_rows': 857863,
            'commit': ctx['commit'], 'run_id': ctx['run_id']}
