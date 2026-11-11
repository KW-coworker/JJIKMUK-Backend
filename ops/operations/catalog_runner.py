"""Fixed phases share one approved job; each phase obtains a fresh OIDC session."""
import json,os,re,time
from pathlib import Path
from connection import ACCOUNT,BUCKET,HOSTS,canonical,sha
from bootstrap import need
from run import clients,execute,save_local,put_once,read_object
from maintenance import context,checked_execute
from maintenance_probe import plan as probe_plan,drained
from maintenance_gate import Gate
from initial_db_runner import aws_client,check_database,snapshot
from initial_monitor import Monitor
from catalog_package import build,source_plan,SOURCE_SHA,SOURCE_BYTES
from catalog_document import document
from manifest import digest


def key(ctx):return 'receipts/catalog/'+ctx['run_id']+'/binding.json'


def time_budget(phase):
    raw=os.environ.get('CATALOG_ROLE_REQUEST_EPOCH','')
    need(re.fullmatch('[1-9][0-9]{9}',raw),'CATALOG_ROLE_TIME_REQUIRED')
    elapsed=time.time()-int(raw)
    need(elapsed>=0 and 3600-elapsed>={'freeze':2700,'snapshot':900,'apply':3300}[phase],
         'CATALOG_ROLE_TIME_INSUFFICIENT_KEEP_HOLD')


def call_phase(api,ctx,binding,envelope,phase,backup=None):
    plan={'format':1,'component':'db','operation':'deploy','approved':True,
          'approval_id':'USER_SOURCE_COMPATIBILITY_AND_DB_APPLY_20261111',
          'document':document(binding,envelope,phase,backup)}
    result=execute(api,ctx,plan,sha(canonical(plan)),HOSTS['backend'],output_prefix=phase+'-',
                   max_polls=600 if phase=='apply' else 360)
    result['report']=json.loads(Path('operation-results/'+phase+'-result.json').read_bytes()).get('report',{})
    return result


def freeze():
    ctx=context();api=clients(True)
    plan=source_plan(os.environ['WORK_PLAN'],os.environ['WORK_SHA256'])
    backup_api=aws_client('rds');save_local('rds-preflight.json',check_database(backup_api))
    src=api['s3'].head_object(Bucket=BUCKET,Key=plan['source_key'],VersionId=plan['source_version'],ExpectedBucketOwner=ACCOUNT,ChecksumMode='ENABLED')
    import base64
    need(src['ContentLength']==plan['source_archive_bytes'] and src['ServerSideEncryption']=='AES256' and
         src.get('ChecksumSHA256')==base64.b64encode(bytes.fromhex(plan['source_archive_sha256'])).decode(),'CATALOG_PRIVATE_SOURCE_HEAD')
    archive,envelope,manifest=build(Path.cwd(),ctx)
    archive_sha=digest(archive);archive_key='operations/bootstrap/'+archive_sha+'/payload.zip'
    with archive.open('rb') as body:
        response=api['s3'].put_object(Bucket=BUCKET,Key=archive_key,Body=body,ServerSideEncryption='AES256',
                                    ExpectedBucketOwner=ACCOUNT,IfNoneMatch='*',ContentType='application/zip')
    binding={'commit':ctx['commit'],'run_id':ctx['run_id'],'request_id':ctx['request_id'],'jar_sha256':manifest['jar_sha256'],
             'sql_sha256':next(r['sha256'] for r in manifest['migrations'] if r['version']=='21'),
             'archive_sha256':archive_sha,'archive_key':archive_key,'archive_version':response['VersionId'],'archive_bytes':archive.stat().st_size,
             'source_key':plan['source_key'],'source_version':plan['source_version'],'source_archive_sha256':plan['source_archive_sha256'],
             'source_archive_bytes':plan['source_archive_bytes'],'source_sha256':SOURCE_SHA,'source_bytes':SOURCE_BYTES,
             'previous_commit':plan['previous_commit'],'required_bytes':plan['required_bytes']}
    saved={'context':ctx,'binding':binding,'envelope':envelope}
    put_once(api['s3'],key(ctx),saved);save_local('catalog-binding.json',saved)
    gate=Gate(api['s3']);work_sha=os.environ['WORK_SHA256'];verify_sha=sha(canonical({'catalog_verify':work_sha}))
    gate.start(ctx['request_id'],ctx['commit'],ctx['run_id'],work_sha,verify_sha)
    for _ in range(90):
        if drained(api['ssm'],list(HOSTS.values())):break
        time.sleep(10)
    else:raise ValueError('CATALOG_DRAIN_TIMEOUT_KEEP_HOLD')
    probe=probe_plan(ctx['request_id'],'before')
    checked_execute(api,ctx,probe,sha(canonical(probe)),HOSTS['backend'],'maintenance-before-')
    with Monitor(api['s3'],aws_client('cloudwatch'),binding,binding['required_bytes']) as monitor:
        time_budget('freeze')
        frozen=call_phase(api,ctx,binding,envelope,'freeze');need(frozen['success'],'CATALOG_FREEZE_FAILED')
        frozen_epoch=frozen['report']['counts']['frozen_epoch']
        time_budget('snapshot')
        backup=snapshot(backup_api,api,ctx,frozen_epoch=frozen_epoch,guard=monitor.check)
        put_once(api['s3'],'receipts/catalog/'+ctx['run_id']+'/frozen.json',{'binding':binding,'snapshot':backup})
    save_local('catalog-freeze-result.json',{'status':'FROZEN_AND_BACKUP_READY','request_id':ctx['request_id']})


def apply():
    ctx=context();api=clients(True)
    saved=read_object(api['s3'],key(ctx));need(saved['context']==ctx,'CATALOG_APPLY_CONTEXT')
    binding,envelope=saved['binding'],saved['envelope']
    frozen=read_object(api['s3'],'receipts/catalog/'+ctx['run_id']+'/frozen.json')
    need(frozen['binding']==binding,'CATALOG_FROZEN_BINDING')
    with Monitor(api['s3'],aws_client('cloudwatch'),binding,binding['required_bytes']) as monitor:
        time_budget('apply');monitor.check()
        backup=frozen['snapshot']
        result=call_phase(api,ctx,binding,envelope,'apply',backup);need(result['success'],'CATALOG_APPLY_FAILED')
    probe=probe_plan(ctx['request_id'],'after')
    report=checked_execute(api,ctx,probe,sha(canonical(probe)),HOSTS['backend'],'maintenance-after-')
    need(report['hashes']['backend_commit_sha256']==sha(ctx['commit'].encode()),'CATALOG_RELEASE_NOT_CURRENT')
    evidence=sha(canonical({p.name:sha(p.read_bytes()) for p in sorted(Path('operation-results').glob('*.json'))}))
    Gate(api['s3']).verified(ctx['request_id'],sha(ctx['commit'].encode()),evidence)
    work_sha=os.environ['WORK_SHA256'];verify_sha=sha(canonical({'catalog_verify':work_sha}))
    save_local('maintenance-result.json',{'status':'VERIFIED_AWAITING_LATEST_MAIN','request_id':ctx['request_id'],
        'commit':ctx['commit'],'run_id':ctx['run_id'],'work_sha256':work_sha,'verify_sha256':verify_sha,
        'backend_commit_sha256':sha(ctx['commit'].encode())})


def recover():
    ctx=context();api=clients(True)
    original=read_object(api['s3'],key(ctx));need(original['context']==ctx,'CATALOG_RECOVERY_CONTEXT')
    binding,envelope=original['binding'],original['envelope']
    # A command that may still be executing must finish before a new fixed recovery.
    for _ in range(90):
        if drained(api['ssm'],list(HOSTS.values())):break
        time.sleep(10)
    else:raise ValueError('CATALOG_RECOVERY_COMMAND_STILL_RUNNING')
    from contextlib import ExitStack
    with ExitStack() as stack:
        monitored=False
        try:
            stack.enter_context(Monitor(api['s3'],aws_client('cloudwatch'),binding,binding['required_bytes']))
            monitored=True
        except Exception:
            # Only restoring services before DB writes is permitted without a lease.
            pass
        result=call_phase(api,ctx,binding,envelope,'recover',{'monitor_ready':monitored})
        save_local('catalog-recovery-result.json',result)
        need(result['success'],'CATALOG_RECOVERY_REQUIRES_REVIEW')
    # A failed work phase never reopens CD or claims the data was applied.


if __name__=='__main__':
    try:
        action=os.environ.get('CATALOG_PHASE')
        need(action in ('freeze','apply','recover'),'CATALOG_PHASE_REQUIRED')
        {'freeze':freeze,'apply':apply,'recover':recover}[action]()
        print('CATALOG_PHASE_VERIFIED_SEE_RECORDED_RESULT')
    except Exception:
        print('CATALOG_STOPPED_KEEP_HOLD_AND_RECORDS');raise SystemExit(1)
