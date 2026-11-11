"""GitHub-only fixed inspection and approved operations, with durable no-resend intent."""
import argparse
import json
import os
from pathlib import Path
import re
import time
from connection import ACCOUNT, REGION, REPO, REPO_ID, HOSTS, BUCKET, READ_ROLE, WRITE_ROLE, READ_DOCUMENT, DOCUMENT_PREFIX, canonical, sha
from bootstrap import github, need


def context(expected,write=False):
    e=os.environ
    need(e.get('GITHUB_ACTIONS')=='true' and e.get('GITHUB_REPOSITORY')==REPO
         and e.get('GITHUB_REPOSITORY_ID')==str(REPO_ID) and e.get('GITHUB_REF')=='refs/heads/main'
         and e.get('GITHUB_EVENT_NAME')=='workflow_dispatch','GITHUB_MAIN_DISPATCH_REQUIRED')
    need(re.fullmatch('[0-9a-f]{40}',expected) and e.get('GITHUB_SHA')==expected,'EXACT_MAIN_REQUIRED')
    need(re.fullmatch('[0-9a-f]{32}',e.get('OPERATIONS_REQUEST_ID','')),'REQUEST_ID_REQUIRED')
    need(github('git/ref/heads/main')['object']['sha']==expected,'MAIN_CHANGED')
    if write:
        need(e.get('OPERATIONS_CONFIRM')=='true' and e.get('GITHUB_RUN_ATTEMPT')=='1','WRITE_APPROVAL_OR_FRESH_RUN_REQUIRED')
    return {'commit':expected,'run_id':e['GITHUB_RUN_ID'],'attempt':e['GITHUB_RUN_ATTEMPT'],
            'request_id':e['OPERATIONS_REQUEST_ID']}


def regional_s3(session):
    from botocore.config import Config
    return session.client('s3',endpoint_url=f'https://s3.{REGION}.amazonaws.com',
        config=Config(signature_version='s3v4',s3={'addressing_style':'virtual'},
            connect_timeout=10,read_timeout=30,retries={'total_max_attempts':1}))


def clients(write=False):
    import boto3
    from botocore.config import Config
    # OIDC action supplies all three. Never use profiles, local files, IMDS or operator sessions.
    session=boto3.Session(aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],aws_session_token=os.environ['AWS_SESSION_TOKEN'],region_name=REGION)
    cfg=Config(connect_timeout=10,read_timeout=30,retries={'total_max_attempts':1})
    result={s:session.client(s,config=cfg) for s in ('sts','ssm','s3')}
    result['s3']=regional_s3(session)
    identity=result['sts'].get_caller_identity()
    role=WRITE_ROLE if write else READ_ROLE
    need(identity['Account']==ACCOUNT and identity['Arn'].startswith(f'arn:aws:sts::{ACCOUNT}:assumed-role/{role}/'),
         'AWS_IDENTITY_MISMATCH')
    need(result['s3'].get_bucket_versioning(Bucket=BUCKET,ExpectedBucketOwner=ACCOUNT).get('Status')=='Enabled',
         'VERSIONING_REQUIRED')
    return result


def load_plan(path,expected_sha):
    need(re.fullmatch(r'ops/operations/plans/[a-z0-9-]{1,80}\.json',path),'PLAN_PATH_REJECTED')
    target=Path(path);need(target.is_file() and not target.is_symlink(),'PLAN_NOT_REGULAR')
    need(target.stat().st_size<=60000,'PLAN_SIZE_LIMIT')
    raw=target.read_bytes();need(sha(raw)==expected_sha,'PLAN_HASH_CHANGED')
    plan=json.loads(raw)
    need(set(plan)=={'format','component','operation','approval_id','approved','document'},'PLAN_SCHEMA')
    need(plan['format']==1 and plan['approved'] is True,'PLAN_NOT_APPROVED')
    need(plan['component'] in ('backend','chatbot','ocr','db') and
         plan['operation'] in ('inspect','install','deploy','verify','rollback'),'PLAN_SCOPE')
    need(re.fullmatch('[A-Z0-9][A-Z0-9_-]{7,79}',plan['approval_id']),'APPROVAL_RECORD_REQUIRED')
    need(not plan['approval_id'].startswith('PENDING_'),'APPROVAL_RECORD_REQUIRED')
    doc=plan['document'];need(doc.get('schemaVersion')=='2.2' and doc.get('parameters')=={},'FIXED_DOCUMENT_REQUIRED')
    need(0<len(doc.get('mainSteps',[]))<=8 and len(canonical(doc))<=60000,'DOCUMENT_SIZE_LIMIT')
    need(all(s.get('action') in ('aws:runShellScript','aws:downloadContent') for s in doc['mainSteps']),
         'UNSUPPORTED_DOCUMENT_ACTION')
    need(doc['mainSteps'][-1].get('name')=='report','FINAL_REPORT_STEP_REQUIRED')
    return plan, HOSTS['ocr' if plan['component']=='ocr' else 'backend']


def safe_report(raw):
    need(len(raw.encode())<=16384,'REPORT_LIMIT')
    value=json.loads(raw)
    need(type(value) is dict and set(value)<={'status','checks','hashes','counts','codes','paths'},'REPORT_FIELDS')
    need(value.get('status') in {'OK','VERIFIED','INSTALLED_DISABLED','SUCCEEDED','ROLLED_BACK','STOPPED',
        'MANUAL_RECOVERY_REQUIRED','PREFLIGHT_FAILED','FAILED'},'REPORT_STATUS')
    for name,values in value.items():
        if name=='status':continue
        if name=='paths':
            from readiness_paths import checked_paths
            checked_paths(values)
            continue
        if name=='codes':
            need(type(values) is list and len(values)<=50 and all(type(v) is str and re.fullmatch('[A-Z][A-Z0-9_]{0,79}',v) for v in values),'REPORT_CODES')
            continue
        need(type(values) is dict and len(values)<=100,'REPORT_MAP')
        for k,v in values.items():
            need(re.fullmatch('[a-zA-Z][a-zA-Z0-9_.-]{0,79}',k),'REPORT_KEY')
            if name=='checks':need(type(v) is bool,'REPORT_BOOLEAN')
            if name=='hashes':need(type(v) is str and re.fullmatch('[0-9a-f]{64}',v),'REPORT_HASH')
            if name=='counts':need(type(v) is int and 0<=v<2**63,'REPORT_COUNT')
    return value


def save_local(name,data):
    out=Path('operation-results');out.mkdir(exist_ok=True)
    with (out/name).open('x',encoding='utf-8') as f:json.dump(data,f,indent=2)


def operation_succeeded(result):
    """Command completion alone is not application success, including collection."""
    return (result.get('status') == 'Success' and result.get('response_code') == 0
            and result.get('report', {}).get('status') in
            {'OK', 'VERIFIED', 'INSTALLED_DISABLED', 'SUCCEEDED'})


from immutable_receipt import put_once


def read_object(s3,key):
    result=s3.get_object(Bucket=BUCKET,Key=key,ExpectedBucketOwner=ACCOUNT)
    need(result['ContentLength']<=65536,'RECEIPT_LIMIT')
    raw=result['Body'].read(65537);need(len(raw)<=65536,'RECEIPT_LIMIT')
    return json.loads(raw)


def wait_result(ssm,cid,target,document,sleep=time.sleep,*,max_polls=360):
    need(max_polls in (360,450,600),'COMMAND_WAIT_BOUND')
    for _ in range(max_polls):
        try:
            invocations=ssm.list_command_invocations(CommandId=cid,InstanceId=target,Details=True)['CommandInvocations']
            if not invocations:sleep(5);continue
            need(len(invocations)==1,'INVOCATION_COUNT')
            overall=invocations[0]
            if overall['Status'] in ('Pending','InProgress','Delayed'):sleep(5);continue
            if overall['Status']!='Success':
                failed={'command_id':cid,'instance':target,'document':document,'status':overall['Status'],
                        'response_code':-1,'plugin_count':len(overall.get('CommandPlugins',[]))}
                plugins=overall.get('CommandPlugins',[])
                # Only the fixed, single report plugin can supply a sanitized failure code.
                # Never turn command failure into success or expose arbitrary stdout/stderr.
                if (overall['Status']=='Failed' and document.startswith(DOCUMENT_PREFIX) and
                    len(plugins)==1 and plugins[0].get('Name')=='report'):
                    observed=ssm.get_command_invocation(CommandId=cid,InstanceId=target,PluginName='report')
                    need(observed.get('CommandId')==cid and observed.get('InstanceId')==target and
                         observed.get('DocumentName')==document,'COMMAND_IDENTITY_MISMATCH')
                    if observed.get('Status')=='Failed' and observed.get('ResponseCode',0)!=0:
                        try:
                            diagnostic=safe_report(observed.get('StandardOutputContent',''))
                            if diagnostic.get('status') in ('STOPPED','FAILED','PREFLIGHT_FAILED','MANUAL_RECOVERY_REQUIRED'):
                                failed['diagnostic']={'status':diagnostic['status'],'codes':diagnostic.get('codes',[])}
                        except (ValueError,TypeError,KeyError,AttributeError):
                            pass
                return failed
            result=ssm.get_command_invocation(CommandId=cid,InstanceId=target,
                PluginName='inspectHost' if document==READ_DOCUMENT else 'report')
        except Exception as error:
            if getattr(error,'response',{}).get('Error',{}).get('Code')=='InvocationDoesNotExist':sleep(5);continue
            raise
        need(result.get('CommandId')==cid and result.get('InstanceId')==target and result.get('DocumentName')==document,
             'COMMAND_IDENTITY_MISMATCH')
        if result['Status'] in ('Pending','InProgress','Delayed'):sleep(5);continue
        # Never print raw stdout/stderr; an unexpected response remains in SSM for reviewed diagnosis.
        public={'command_id':cid,'instance':target,'document':document,'status':result['Status'],
                'response_code':result['ResponseCode'],'stdout_sha256':sha(result.get('StandardOutputContent','').encode()),
                'stderr_sha256':sha(result.get('StandardErrorContent','').encode())}
        if result['Status']=='Success' and result['ResponseCode']==0 and not result.get('StandardErrorContent'):
            if document==READ_DOCUMENT:
                # The fixed read document is immutable to these roles. Return aggregate success only;
                # detailed service metadata stays in SSM, not in this public repository's logs.
                observed=json.loads(result['StandardOutputContent'])
                need(observed.get('status')=='OBSERVED','INSPECTION_FAILED')
                public['checks']=observed['checks']
                public['hashes']=observed.get('hashes', {})
                public['counts']=observed.get('counts', {})
                public['free_bytes']=observed['free_bytes']
            else:public['report']=safe_report(result['StandardOutputContent'])
        return public
    raise ValueError('WAIT_LIMIT_COLLECT_ONLY_NEVER_RESEND')


def inspect(api):
    results=[]
    info=api['ssm'].describe_document(Name=READ_DOCUMENT)['Document']
    need(info['Owner']==ACCOUNT and info['LatestVersion']=='1','INSPECTION_DOCUMENT_CHANGED')
    for component,target in HOSTS.items():
        response=api['ssm'].send_command(InstanceIds=[target],DocumentName=READ_DOCUMENT,DocumentVersion='1',
            DocumentHash=info['Hash'],DocumentHashType='Sha256',Parameters={'HostKind':[component]},TimeoutSeconds=120,
            MaxConcurrency='1',MaxErrors='0',CloudWatchOutputConfig={'CloudWatchOutputEnabled':False},
            Comment='GitHub fixed metadata inspection '+component)
        cid=response['Command']['CommandId'];save_local('inspect-'+component+'-sent.json',{'command_id':cid})
        result=wait_result(api['ssm'],cid,target,READ_DOCUMENT);save_local('inspect-'+component+'.json',result);results.append(result)
    completed=all(r['status']=='Success' and r['response_code']==0 for r in results)
    healthy=completed and all(bool(r.get('checks')) and all(r['checks'].values()) for r in results)
    return {'status':'INSPECTION_FINISHED','hosts':len(results),
            'observation_completed':completed,'required_services_healthy':healthy,'success':healthy}


def execute(api,context_data,plan,plan_hash,target,*,output_prefix='',max_polls=None):
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        # A cancelled maintenance workflow must also block the older generic executor.
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cd'))
        from maintenance_gate import Gate
        Gate(api['s3']).manual_admission(context_data['request_id'], os.environ.get('GITHUB_WORKFLOW_REF', ''))
    need(output_prefix in ('','freeze-','apply-','recover-','install-','activate-',
                          'maintenance-before-','maintenance-work-','maintenance-verify-','maintenance-after-'),
         'OPERATION_OUTPUT_PREFIX')
    polls=max_polls if max_polls is not None else 450 if output_prefix=='apply-' else 360
    need(polls in (360,450,600),'COMMAND_WAIT_BOUND')
    op_id=sha(canonical({'commit':context_data['commit'],'plan_sha256':plan_hash,'target':target}))
    doc=plan['document'];content=canonical(doc).decode();name=DOCUMENT_PREFIX+sha(canonical(doc))
    # S3 precondition makes reruns fail before any second command, including a lost SendCommand response.
    intent={'operation_id':op_id,'document':name,'target':target,'plan_sha256':plan_hash,
            'component':plan['component'],'operation':plan['operation'],'context':context_data}
    put_once(api['s3'],'receipts/'+op_id+'/intent.json',intent)
    save_local(output_prefix+'intent.json',intent)
    try:info=api['ssm'].describe_document(Name=name)['Document']
    except Exception as error:
        if getattr(error,'response',{}).get('Error',{}).get('Code')!='InvalidDocument':raise
        info=api['ssm'].create_document(Name=name,Content=content,DocumentType='Command',DocumentFormat='JSON')['DocumentDescription']
    actual=api['ssm'].get_document(Name=name,DocumentVersion='1',DocumentFormat='JSON')
    need(json.loads(actual['Content'])==doc and info['Owner']==ACCOUNT and info['LatestVersion']=='1','DOCUMENT_MISMATCH')
    response=api['ssm'].send_command(InstanceIds=[target],DocumentName=name,DocumentVersion='1',DocumentHash=info['Hash'],
        DocumentHashType='Sha256',Parameters={},TimeoutSeconds=120,MaxConcurrency='1',MaxErrors='0',
        CloudWatchOutputConfig={'CloudWatchOutputEnabled':False},Comment='jjikmuk-ops:'+op_id)
    cid=response['Command']['CommandId']
    put_once(api['s3'],'receipts/'+op_id+'/sent.json',dict(intent,command_id=cid))
    save_local(output_prefix+'sent.json',{'operation_id':op_id,'command_id':cid})
    result=wait_result(api['ssm'],cid,target,name,max_polls=polls)
    put_once(api['s3'],'receipts/'+op_id+'/result.json',result);save_local(output_prefix+'result.json',result)
    return {'status':'OPERATION_FINISHED','operation_id':op_id,'command_id':cid,
            'success':operation_succeeded(result)}


def collect(api,op_id,*,output_prefix=''):
    need(output_prefix in ('','install-','activate-','recover-'),'COLLECT_OUTPUT_PREFIX')
    need(re.fullmatch('[0-9a-f]{64}',op_id),'INVALID_OPERATION_ID')
    intent=read_object(api['s3'],'receipts/'+op_id+'/intent.json')
    need(intent['target'] in HOSTS.values() and intent['document'].startswith(DOCUMENT_PREFIX),'INVALID_STORED_INTENT')
    try:cid=read_object(api['s3'],'receipts/'+op_id+'/sent.json')['command_id']
    except Exception as error:
        if getattr(error,'response',{}).get('Error',{}).get('Code')!='NoSuchKey':raise
        found=[];request={'InstanceId':intent['target'],'MaxResults':50}
        for _ in range(20):
            page=api['ssm'].list_commands(**request)
            found.extend(x['CommandId'] for x in page['Commands'] if x.get('Comment')=='jjikmuk-ops:'+op_id
                         and x.get('DocumentName')==intent['document'])
            if not page.get('NextToken'):break
            request['NextToken']=page['NextToken']
        else:raise ValueError('COMMAND_HISTORY_LIMIT_NO_RESEND')
        need(len(found)==1,'SEND_OUTCOME_UNCERTAIN_NO_RESEND');cid=found[0]
    result=wait_result(api['ssm'],cid,intent['target'],intent['document']);save_local(output_prefix+'collected.json',result)
    return {'status':'COLLECTED_NO_RESEND','operation_id':op_id,'command_id':cid,
            'success':operation_succeeded(result)}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['inspect','execute','collect'])
    parser.add_argument('--expected-sha',required=True);parser.add_argument('--plan');parser.add_argument('--plan-sha256')
    parser.add_argument('--operation-id');args=parser.parse_args()
    try:
        ctx=context(args.expected_sha,args.mode=='execute')
        selected=load_plan(args.plan,args.plan_sha256) if args.mode=='execute' else None
        api=clients(args.mode=='execute')
        result=(execute(api,ctx,selected[0],args.plan_sha256,selected[1]) if args.mode=='execute' else
                collect(api,args.operation_id) if args.mode=='collect' else inspect(api))
        print(json.dumps(result));raise SystemExit(0 if result.get('success',True) else 1)
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) else type(error).__name__
        print(json.dumps({'status':'STOPPED_KEEP_RECORDS','code':code,'resend':False}));raise SystemExit(1)
