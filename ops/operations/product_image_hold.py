"""One approved image patch under the existing hold; never resume CD or deploy JARs."""
from connection import HOSTS
from bootstrap import need
from maintenance_gate import Gate
from run import load_plan, execute

REQUEST = 'a5291163ee0a456b85366e6075d8fce6'


def perform(api, ctx, path, digest):
    gate, _ = Gate(api['s3']).read()
    need(gate is not None and gate['state'] == 'WORKING' and gate['request_id'] == REQUEST
         and ctx['request_id'] == REQUEST and gate['run_id'] == '43041472793', 'IMAGE_PATCH_HOLD_CHANGED')
    plan, target = load_plan(path, digest)
    need(plan['component'] == 'db' and plan['operation'] == 'deploy'
         and plan['approval_id'] == 'USER_SINGLE_PRODUCT_IMAGE_20261112'
         and target == HOSTS['backend'], 'IMAGE_PATCH_APPROVAL')
    result = execute(api, ctx, plan, digest, target)
    need(result['success'], 'IMAGE_PATCH_EXECUTION_FAILED')
    after, _ = Gate(api['s3']).read()
    need(after == gate, 'IMAGE_PATCH_HOLD_MODIFIED')
    return result
