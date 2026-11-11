"""One image list, bounded SSM slices, unchanged maintenance hold and renewable OIDC."""
import base64
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
from bootstrap import need
from connection import HOSTS,canonical,sha
from maintenance_gate import Gate
from product_image_hold import REQUEST
from run import clients,execute,save_local
from storage_metrics import observe

APPROVAL='USER_PRODUCT_IMAGE_URL_LIST_20261112'
ROWS=1098863


def load(path,digest):
    need(re.fullmatch(r'ops/operations/plans/[a-z0-9-]{1,80}\.json',path),'IMAGES_PLAN_PATH')
    p=Path(path);need(p.is_file() and not p.is_symlink() and p.stat().st_size<=60000,'IMAGES_PLAN_FILE')
    raw=p.read_bytes();need(sha(raw)==digest,'IMAGES_PLAN_HASH')
    value=json.loads(raw)
    need(set(value)=={'format','envelope','input_sha256','slices','rows'} and value['format']==1 and value['rows']==ROWS,'IMAGES_PLAN_SCHEMA')
    from private_plan import validate
    envelope=validate(value['envelope'])
    need(envelope['component']=='db' and envelope['operation']=='deploy' and envelope['approval_id']==APPROVAL,'IMAGES_APPROVAL')
    need(re.fullmatch('[a-f0-9]{64}',value['input_sha256']) and 1<=len(value['slices'])<100,'IMAGES_PLAN_INPUT')
    previous=0;total=0
    for i,s in enumerate(value['slices']):
        need(set(s)=={'index','after_id','last_id','count'} and all(type(v) is int for v in s.values()) and
             s['index']==i and s['after_id']==previous and s['last_id']>previous and 0<s['count']<=20000,'IMAGES_PLAN_SLICES')
        previous=s['last_id'];total+=s['count']
    need(total==ROWS,'IMAGES_PLAN_TOTAL')
    return value


def slice_plan(request):
    source=Path(__file__).with_name('product_images_remote.py').read_bytes()
    code="import base64,json,sys\nexec(compile(base64.b64decode('"+base64.b64encode(source).decode()+"'),'<fixed-image-loader>','exec'))\n"
    code+="try:\n print(json.dumps(execute(json.loads(base64.b64decode('"+base64.b64encode(canonical(request)).decode()+"')))))\n"
    code+="except Exception as e:\n print(json.dumps({'status':'STOPPED','codes':['IMAGES_SLICE_STOPPED_KEEP_COMPLETED',type(e).__name__.upper()]}));sys.exit(1)\n"
    return {'format':1,'component':'db','operation':'deploy','approval_id':APPROVAL,'approved':True,
        'document':{'schemaVersion':'2.2','description':'Apply one fixed slice of the approved product image list',
        'parameters':{},'mainSteps':[{'action':'aws:runShellScript','name':'report','inputs':{
            'timeoutSeconds':'1400','runCommand':["/usr/bin/python3 -I -S -B <<'JJIKMUK_IMAGES'\n"+code+"\nJJIKMUK_IMAGES"]}}]}}


def held(api,ctx,expected=None):
    state,_=Gate(api['s3']).read()
    need(state is not None and state['state']=='WORKING' and state['request_id']==ctx['request_id']==REQUEST and
         state['run_id']=='43041472793' and (expected is None or expected==state),'IMAGES_EXISTING_HOLD_CHANGED')
    return state


def perform(ctx,path,digest):
    from catalog_progress_github import Reporter
    from catalog_progress import safe_error
    progress=Reporter(ctx,'image-urls');need(progress.ready,'IMAGES_PROGRESS_UNAVAILABLE_BEFORE_START')
    totals={'checked':0,'changed':0,'slices':0}
    try:
        result=apply_list(ctx,path,digest,progress,totals)
        progress.emit('DONE',done=totals['checked'],total=ROWS,force=True,terminal='success')
        return result
    except Exception as error:
        progress.emit('FAILED',done=totals['checked'],total=ROWS,error_code=safe_error(error),force=True,terminal='failure')
        raise


def apply_list(ctx,path,digest,progress,totals):
    from catalog_credentials import session
    from private_plan import plan as seed_plan
    value=load(path,digest)
    aws,renewal=session(os.environ,seconds=9000);api=clients(True,session=aws)
    from botocore.config import Config
    cloudwatch=aws.client('cloudwatch',config=Config(connect_timeout=5,read_timeout=15,retries={'total_max_attempts':1}))
    gate=held(api,ctx)
    def space(index,remaining):
        metric=observe(cloudwatch,datetime.now(timezone.utc));save_local(f'images-{index:03d}-space.json',metric)
        # Four times the measured local table growth plus the user-selected 2 GiB reserve.
        need(metric['counts']['window_minimum_bytes']>2*1024**3+remaining*8000,'IMAGES_RDS_SPACE_KEEP_COMPLETED')
    def step(plan,index):
        renewal.admit(1800);held(api,ctx,gate)
        prefix=f'images-{index:03d}-'
        result=execute(api,ctx,plan,sha(canonical(plan)),HOSTS['backend'],output_prefix=prefix)
        need(result['success'],'IMAGES_EXECUTION_STOP_KEEP_COMPLETED')
        report=json.loads((Path('operation-results')/(prefix+'result.json')).read_bytes())['report']
        need(report['status']=='VERIFIED' and report['checks'] and all(x is True for x in report['checks'].values()),'IMAGES_UNVERIFIED')
        return report
    space(0,ROWS);step(seed_plan(value['envelope']),0)
    seed=sha(canonical(value['envelope']))
    for s in value['slices']:
        index=s['index']+1;space(index,ROWS-totals['checked'])
        request={'seed_operation':seed,'package_sha256':value['envelope']['sha256'],'index':s['index'],'input_sha256':value['input_sha256']}
        report=step(slice_plan(request),index);counts=report['counts']
        need(counts['checked']==s['count'] and counts['last_id']==s['last_id'] and counts['changed']<=counts['checked'],'IMAGES_RESULT_COUNT')
        totals['checked']+=counts['checked'];totals['changed']+=counts['changed'];totals['slices']+=1
        print(json.dumps({'phase':'IMAGE_URLS','total':ROWS,**totals}),flush=True)
        save_local(f'images-{index:03d}-progress.json',dict(totals))
        progress.emit('PRODUCT_APPLY',done=totals['checked'],total=ROWS,force=True)
    held(api,ctx,gate);need(totals['checked']==ROWS,'IMAGES_TOTAL_INCOMPLETE')
    return {'status':'VERIFIED_CD_HOLD_PRESERVED','counts':totals,'request_id':ctx['request_id'],
            'checks':{'all_input_rows_checked':True,'service_not_restarted':True,'existing_cd_hold_preserved':True}}
