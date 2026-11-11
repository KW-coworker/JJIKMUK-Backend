"""New bounded run after verified restoration; no old command or journal replay."""
import base64,json,os,time
from datetime import datetime,timezone
from pathlib import Path
from botocore.config import Config
from connection import ACCOUNT,BUCKET,HOSTS,canonical,sha
from bootstrap import need,github
from run import clients,execute,put_once,read_object,save_local
from maintenance import context,checked_execute
from maintenance_gate import Gate
from maintenance_probe import drained,plan as probe_plan
from catalog_credentials import session
from catalog_reapply_contract import (REQUEST,OLD_RUN,SERVICE_RUN,OLD_ARCHIVE,OLD_STATE,OLD_JOURNAL,PREVIOUS,
    SERVICE_OPERATION,SERVICE_RESULT,SOURCE_SHA,SOURCE_BYTES,PHASE_SECONDS,RUNNER_SECONDS,RDS_START_BYTES,
    validate_binding,lease_binding,dataset,RDS_RESERVE_BYTES,RESERVE_APPROVAL,LAST_RUN,LAST_COMMIT,
    LAST_RECOVERY_OPERATION,LAST_RECOVERY_RESULT,SNAPSHOT_POLLS,SNAPSHOT_BUDGET)
from catalog_package import build,source_plan
from catalog_document import document
from catalog_runner import key
from initial_monitor import Monitor
from initial_db_runner import DB,check_database,snapshot
from storage_metrics import observe
from manifest import digest
from catalog_progress import safe_error


class Runtime:
    def __init__(self,ctx,phase):
        need(os.environ.get('MAINTENANCE_MODE')=='catalog-reapply' and phase in RUNNER_SECONDS,'REAPPLY_WORKFLOW')
        dataset(ctx['request_id'],ctx['run_id'])
        shared,self.budget=session(os.environ,seconds=RUNNER_SECONDS[phase])
        self.api=clients(True,session=shared)
        config=Config(connect_timeout=10,read_timeout=30,retries={'total_max_attempts':1})
        self.rds=shared.client('rds',config=config);self.cloudwatch=shared.client('cloudwatch',config=config)
        self.ctx,self.phase=ctx,phase
        self.reporter=None

    def progress(self,stage,done=0,total=None,**kwargs):
        if self.reporter is not None:self.reporter.emit(stage,done=done,total=total,**kwargs)

    def monitor(self,binding):
        bound=lease_binding(binding,self.phase)
        return Monitor(self.api['s3'],self.cloudwatch,bound,bound['required_bytes'],budget_check=self.budget.check,
                       minimum_reserve=RDS_RESERVE_BYTES)

    def drain(self):
        for _ in range(90):
            self.budget.check()
            if drained(self.api['ssm'],list(HOSTS.values())):return
            time.sleep(10)
        raise ValueError('REAPPLY_PRIOR_COMMAND_STILL_RUNNING')

    def command(self,binding,envelope,backup=None):
        # Check AFTER preparation/drain: credentials never extend this deadline.
        seconds=1770 if self.phase=='freeze' else PHASE_SECONDS[self.phase]+150
        self.budget.admit(seconds+{'freeze':SNAPSHOT_BUDGET+120,'apply':660,'recover':180}[self.phase])
        self.drain()
        self.budget.admit(seconds+{'freeze':SNAPSHOT_BUDGET+120,'apply':660,'recover':180}[self.phase])
        plan={'format':1,'component':'db','operation':'deploy','approved':True,
              'approval_id':'USER_SOURCE_COMPATIBILITY_AND_DB_APPLY_20261111',
              'document':document(binding,envelope,self.phase,backup)}
        observer=None
        reporter=getattr(self,'reporter',None)
        if reporter is not None:
            try:
                from catalog_progress_reader import Reader
                observer=Reader(self.api['ssm'],binding,self.phase,reporter)
            except Exception as error:reporter.unavailable(error)
        try:
            result=execute(self.api,self.ctx,plan,sha(canonical(plan)),HOSTS['backend'],
                           output_prefix=self.phase+'-',max_polls=1500 if self.phase!='freeze' else 450,observer=observer)
        finally:
            if observer is not None:observer.close()
        self.budget.check()
        result['report']=json.loads(Path('operation-results/'+self.phase+'-result.json').read_bytes()).get('report',{})
        return result


def previous_gate(api,ctx,work_sha,verify_sha):
    value,etag=Gate(api['s3']).read()
    need(value is not None and value['state']=='WORKING' and value['request_id']==REQUEST and
         value['run_id']==LAST_RUN and value['commit']==LAST_COMMIT and value['work_sha256']==work_sha and
         value['verify_sha256']==verify_sha,'REAPPLY_PREVIOUS_GATE_CHANGED')
    proof=read_object(api['s3'],'receipts/'+SERVICE_OPERATION+'/result.json')
    need(sha(canonical(proof))==SERVICE_RESULT,'REAPPLY_SERVICE_PROOF_CHANGED')
    recovery=read_object(api['s3'],'receipts/'+LAST_RECOVERY_OPERATION+'/result.json')
    need(sha(canonical(recovery))==LAST_RECOVERY_RESULT,'REAPPLY_LAST_RECOVERY_PROOF_CHANGED')
    return value,etag


def capacity(runtime):
    save_local('rds-preflight.json',check_database(runtime.rds))
    rows=runtime.rds.describe_db_instances(DBInstanceIdentifier=DB)['DBInstances']
    need(len(rows)==1 and 20<=rows[0]['AllocatedStorage']<=40 and rows[0]['StorageType']=='gp3' and
         rows[0]['DBInstanceStatus']=='available' and not rows[0].get('PendingModifiedValues'),
         'REAPPLY_STORAGE_CONFIGURATION_OR_PENDING_CHANGE')
    value=observe(runtime.cloudwatch,datetime.now(timezone.utc))
    need(value['counts']['window_minimum_bytes']>=RDS_START_BYTES,'REAPPLY_STARTING_SPACE')
    save_local('reapply-starting-space.json',value)


def freeze(runtime):
    ctx,api=runtime.ctx,runtime.api
    need(runtime.reporter is not None and runtime.reporter.ready,'PROGRESS_CHANNEL_UNAVAILABLE_BEFORE_WORK')
    runtime.progress('PREPARING',force=True)
    work_sha=os.environ['WORK_SHA256'];verify_sha=sha(canonical({'catalog_verify':work_sha}))
    previous_gate(api,ctx,work_sha,verify_sha)
    plan=source_plan(os.environ['WORK_PLAN'],work_sha);capacity(runtime)
    source=api['s3'].head_object(Bucket=BUCKET,Key=plan['source_key'],VersionId=plan['source_version'],
                               ExpectedBucketOwner=ACCOUNT,ChecksumMode='ENABLED')
    need(source['ContentLength']==plan['source_archive_bytes'] and source['ServerSideEncryption']=='AES256' and
         source.get('ChecksumSHA256')==base64.b64encode(bytes.fromhex(plan['source_archive_sha256'])).decode(),'REAPPLY_SOURCE_HEAD')
    archive,envelope,manifest=build(Path.cwd(),ctx,reapply=True)
    archive_sha=digest(archive);archive_key='operations/bootstrap/'+archive_sha+'/payload.zip'
    with archive.open('rb') as body:
        uploaded=api['s3'].put_object(Bucket=BUCKET,Key=archive_key,Body=body,ServerSideEncryption='AES256',
                                    ExpectedBucketOwner=ACCOUNT,IfNoneMatch='*',ContentType='application/zip')
    binding={'commit':ctx['commit'],'run_id':ctx['run_id'],'request_id':ctx['request_id'],'jar_sha256':manifest['jar_sha256'],
        'sql_sha256':next(r['sha256'] for r in manifest['migrations'] if r['version']=='21'),
        'archive_sha256':archive_sha,'archive_key':archive_key,'archive_version':uploaded['VersionId'],'archive_bytes':archive.stat().st_size,
        'source_key':plan['source_key'],'source_version':plan['source_version'],'source_archive_sha256':plan['source_archive_sha256'],
        'source_archive_bytes':plan['source_archive_bytes'],'source_sha256':SOURCE_SHA,'source_bytes':SOURCE_BYTES,
        'previous_commit':PREVIOUS,'required_bytes':RDS_RESERVE_BYTES,'source_plan_required_bytes':plan['required_bytes'],
        'reserve_approval':RESERVE_APPROVAL,
        'reapply':{'previous_run':OLD_RUN,'service_run':SERVICE_RUN,'previous_archive':OLD_ARCHIVE,
                   'previous_state_sha256':OLD_STATE,'previous_journal_sha256':OLD_JOURNAL,
                   'last_recovered_run':LAST_RUN,'last_recovery_sha256':LAST_RECOVERY_RESULT}}
    validate_binding(binding)
    saved={'context':ctx,'binding':binding,'envelope':envelope}
    put_once(api['s3'],key(ctx),saved);save_local('catalog-binding.json',saved)
    previous,etag=previous_gate(api,ctx,work_sha,verify_sha)
    put_once(api['s3'],'receipts/catalog/'+ctx['run_id']+'/reapply-intent.json',
             {'previous_gate':previous,'context':ctx,'service_operation':SERVICE_OPERATION,'service_result':SERVICE_RESULT,
              'last_recovery_operation':LAST_RECOVERY_OPERATION,'last_recovery_result':LAST_RECOVERY_RESULT})
    Gate(api['s3']).write(dict(previous,commit=ctx['commit'],run_id=ctx['run_id']),etag)
    runtime.drain()
    with runtime.monitor(binding) as monitor:
        frozen=runtime.command(binding,envelope);need(frozen['success'],'REAPPLY_FREEZE_FAILED')
        runtime.budget.admit(SNAPSHOT_BUDGET)
        runtime.progress('SNAPSHOT_WAIT',force=True)
        backup=snapshot(runtime.rds,api,ctx,frozen_epoch=frozen['report']['counts']['frozen_epoch'],guard=monitor.check,
                        progress=runtime.progress,max_polls=SNAPSHOT_POLLS)
        put_once(api['s3'],'receipts/catalog/'+ctx['run_id']+'/frozen.json',{'binding':binding,'snapshot':backup})
    save_local('catalog-freeze-result.json',{'status':'FROZEN_AND_BACKUP_READY','request_id':ctx['request_id']})


def load(runtime):
    saved=read_object(runtime.api['s3'],key(runtime.ctx))
    need(saved['context']==runtime.ctx,'REAPPLY_CONTEXT_CHANGED')
    validate_binding(saved['binding'])
    gate,_=Gate(runtime.api['s3']).read()
    need(gate is not None and gate['state']=='WORKING' and gate['request_id']==runtime.ctx['request_id'] and
         gate['run_id']==runtime.ctx['run_id'] and gate['commit']==runtime.ctx['commit'],'REAPPLY_GATE_OWNER_CHANGED')
    return saved['binding'],saved['envelope']


def apply(runtime):
    ctx,api=runtime.ctx,runtime.api;binding,envelope=load(runtime)
    require_job_recovery_budget(ctx)
    frozen=read_object(api['s3'],'receipts/catalog/'+ctx['run_id']+'/frozen.json')
    need(frozen['binding']==binding,'REAPPLY_FROZEN_BINDING')
    with runtime.monitor(binding) as monitor:
        monitor.check();result=runtime.command(binding,envelope,frozen['snapshot'])
        need(result['success'],'REAPPLY_APPLY_FAILED')
    runtime.budget.admit(480)
    probe=probe_plan(ctx['request_id'],'after-'+ctx['run_id'])
    report=checked_execute(api,ctx,probe,sha(canonical(probe)),HOSTS['backend'],'maintenance-after-')
    need(report['hashes']['backend_commit_sha256']==sha(ctx['commit'].encode()),'REAPPLY_RELEASE_NOT_CURRENT')
    evidence=sha(canonical({p.name:sha(p.read_bytes()) for p in sorted(Path('operation-results').glob('*.json'))}))
    Gate(api['s3']).verified(ctx['request_id'],sha(ctx['commit'].encode()),evidence)
    work_sha=os.environ['WORK_SHA256'];verify_sha=sha(canonical({'catalog_verify':work_sha}))
    save_local('maintenance-result.json',{'status':'VERIFIED_AWAITING_LATEST_MAIN','request_id':ctx['request_id'],
        'commit':ctx['commit'],'run_id':ctx['run_id'],'work_sha256':work_sha,'verify_sha256':verify_sha,
        'backend_commit_sha256':sha(ctx['commit'].encode())})


def require_job_recovery_budget(ctx):
    # GitHub's 360-minute job limit includes all phases. A longer backup wait must
    # never use the time needed for the complete apply deadline plus recovery.
    from connection import REPO_ID
    run=github('actions/runs/'+ctx['run_id'])
    need(str(run['id'])==ctx['run_id'] and run['head_sha']==ctx['commit'] and run['run_attempt']==1 and
         run['repository']['id']==REPO_ID and run['path']=='.github/workflows/server-maintenance.yml',
         'REAPPLY_JOB_TIME_IDENTITY')
    started=datetime.fromisoformat(run['run_started_at'].replace('Z','+00:00'))
    need(started.tzinfo is not None,'REAPPLY_JOB_START_TIME')
    elapsed=time.time()-started.timestamp()
    required=RUNNER_SECONDS['apply']+RUNNER_SECONDS['recover']+600
    need(0<=elapsed and 360*60-elapsed>required,'REAPPLY_JOB_RECOVERY_TIME_RESERVED')


def recover(runtime):
    from contextlib import ExitStack
    binding,envelope=load(runtime);runtime.drain()
    with ExitStack() as stack:
        monitored=False
        try:stack.enter_context(runtime.monitor(binding));monitored=True
        except Exception:pass  # Host permits no product writes without a live recovery lease.
        result=runtime.command(binding,envelope,{'monitor_ready':monitored})
        save_local('catalog-recovery-result.json',result)
        need(result['success'],'REAPPLY_RECOVERY_REQUIRES_REVIEW')


if __name__=='__main__':
    reporter=None
    try:
        from catalog_progress_github import Reporter
        phase=os.environ.get('CATALOG_PHASE');ctx=context();reporter=Reporter(ctx,phase)
        runtime=Runtime(ctx,phase);runtime.reporter=reporter
        {'freeze':freeze,'apply':apply,'recover':recover}[phase](runtime)
        reporter.emit('DONE',force=True,terminal='success' if phase=='apply' else 'neutral' if phase=='recover' else None)
        print('REAPPLY_PHASE_VERIFIED_SEE_RECORDED_RESULT')
    except Exception as error:
        code=safe_error(error)
        save_local('catalog-'+str(os.environ.get('CATALOG_PHASE'))+'-failure.json',{'code':code})
        if reporter is not None:reporter.emit('FAILED',error_code=code,force=True,terminal='failure')
        print('REAPPLY_STOPPED_KEEP_HOLD_AND_RECORDS '+code);raise SystemExit(1)
