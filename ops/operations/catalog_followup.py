"""Continue the inspected failure with a new run and versioned gate transition."""
from connection import canonical,sha
from bootstrap import need
from run import read_object,put_once
from catalog_followup_host import FOLLOWUP

GATE_SHA='9b79f5789efd6179eef4fe903f2a9cfb738ab4cfd8f3d647f4787cb85e64ba0a'
INSPECTION_OPERATION='5a04a101689b73343a917528708f9115ecfe7c9d8b669d361544fc8f24ce7674'
INSPECTION_SHA='3b68198c97ec5ebaaa819b8419750e31a5cf1d83b4414b63b882f9b0e7338cb7'


def check(api,ctx,gate):
    need(ctx['request_id']==FOLLOWUP['request_id'] and ctx['run_id']!=FOLLOWUP['old_run'],'CATALOG_FOLLOWUP_REQUEST')
    previous,etag=gate.read()
    need(sha(canonical(previous))==GATE_SHA,'CATALOG_FOLLOWUP_HOLD_CHANGED')
    observed=read_object(api['s3'],'receipts/'+INSPECTION_OPERATION+'/result.json')
    need(sha(canonical(observed))==INSPECTION_SHA,'CATALOG_FOLLOWUP_INSPECTION_CHANGED')
    return previous,etag


def bind(api,ctx,gate,work_sha,verify_sha):
    previous,etag=check(api,ctx,gate)
    need(previous['work_sha256']==work_sha and previous['verify_sha256']==verify_sha,'CATALOG_FOLLOWUP_PLAN_CHANGED')
    put_once(api['s3'],'receipts/catalog/'+ctx['run_id']+'/followup-intent.json',{
        'previous_gate':previous,'context':ctx,'inspection_operation':INSPECTION_OPERATION,'inspection_sha256':INSPECTION_SHA})
    # Old versions and the original request receipt remain. The hold is never opened here.
    gate.write(dict(previous,commit=ctx['commit'],run_id=ctx['run_id']),etag)
