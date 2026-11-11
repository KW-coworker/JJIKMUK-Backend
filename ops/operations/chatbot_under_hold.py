"""Run the user's pinned chatbot transition without reopening image maintenance."""
from bootstrap import need
from connection import HOSTS
from maintenance_gate import Gate
from maintenance_probe import drained
from paused_images_closeout import REQUEST
from run import load_plan, execute


def perform(api, ctx, path, digest):
    gate = Gate(api['s3'])
    before, _ = gate.read()
    need(ctx['request_id'] == REQUEST and before is not None and before['request_id'] == REQUEST
         and before['state'] in ('WORKING', 'VERIFIED') and before['run_id'] == '43041472793',
         'CHATBOT_TRANSITION_HOLD_CHANGED')
    plan, target = load_plan(path, digest)
    need(plan['component'] == 'chatbot' and plan['operation'] in ('inspect', 'install', 'deploy', 'verify')
         and plan['approval_id'] == 'USER_RESUME_BACKEND_AND_CHATBOT_20261112'
         and target == HOSTS['backend'], 'CHATBOT_TRANSITION_APPROVAL')
    need(drained(api['ssm'], list(HOSTS.values())), 'CHATBOT_TRANSITION_SSM_BUSY')
    result = execute(api, ctx, plan, digest, target)
    need(result['success'], 'CHATBOT_TRANSITION_FAILED_COLLECT_ONLY')
    need(gate.read()[0] == before, 'CHATBOT_TRANSITION_MODIFIED_HOLD')
    return dict(result, image_work_remains_paused=True)
