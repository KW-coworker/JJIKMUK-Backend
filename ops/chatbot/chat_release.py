"""Chatbot push-only dispatcher. A lost SendCommand response is only collected."""
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cd'))
from auto_context import ACCOUNT,REGION,BUCKET,INSTANCE,select_snapshot,NoRedirect,identity
from release import clients,get_receipt,put_receipt,report,error_code
from package import REPO,REPO_ID,build,need,sha
from notices import REASONS
DOCUMENT='Jjikmuk-ChatbotDeploy-v1'


def guard():
    e=os.environ;commit,run,attempt=identity()
    need(e.get('GITHUB_REPOSITORY')==REPO and e.get('GITHUB_REPOSITORY_ID')==str(REPO_ID)
         and e.get('GITHUB_REF')=='refs/heads/chatbot' and e.get('GITHUB_EVENT_NAME')=='push'
         and e.get('GITHUB_WORKFLOW_REF')==REPO+'/.github/workflows/chatbot-cd.yml@refs/heads/chatbot'
         and e.get('CHATBOT_CD_ENABLED')=='true','CHATBOT_AUTOMATIC_CONTEXT')
    event=json.loads(Path(e['GITHUB_EVENT_PATH']).read_bytes())
    need(event.get('after')==commit and event.get('ref')=='refs/heads/chatbot' and event.get('forced') is False
         and event.get('deleted') is False and event['repository']['id']==REPO_ID,'CHATBOT_PUSH_IDENTITY')
    request=urllib.request.Request('https://api.github.com/repos/'+REPO+'/git/ref/heads/chatbot',headers={
        'Authorization':'Bearer '+e['GH_TOKEN'],'User-Agent':'JJIKMUK-Chatbot-CD'})
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=20) as response:
        raw=response.read(65537);need(len(raw)<=65536,'CHATBOT_GITHUB_LIMIT')
        need(json.loads(raw)['object']['sha']==commit,'SUPERSEDED')
    return commit,run,attempt


def collect(ssm,intent):
    # Search the command history even after an ambiguous network error. Never resend.
    found=[];token=None
    for _ in range(100):
        args={'InstanceId':INSTANCE,'MaxResults':50}
        if token:args['NextToken']=token
        page=ssm.list_commands(**args)
        for item in page.get('Commands',[]):
            if item.get('Comment')!=intent['comment']:continue
            need(item['DocumentName']==DOCUMENT and item['DocumentVersion']=='1' and item['InstanceIds']==[INSTANCE]
                 and not item.get('Targets') and item['Parameters']==intent['parameters'],'CHATBOT_COMMAND_CHANGED')
            found.append(item['CommandId'])
        token=page.get('NextToken')
        if not token:break
    else:raise ValueError('CHATBOT_COMMAND_HISTORY_LIMIT')
    need(len(found)<=1,'CHATBOT_AMBIGUOUS_COMMAND')
    return found[0] if found else None


def wait_result(ssm,intent):
    cid=None
    for _ in range(12):
        cid=collect(ssm,intent)
        if cid:break
        time.sleep(5)
    need(cid is not None,'STATUS_UNKNOWN_DO_NOT_REDISPATCH')
    for _ in range(360):
        try:r=ssm.get_command_invocation(CommandId=cid,InstanceId=INSTANCE,PluginName='deployChatbot')
        except Exception as error:
            if error_code(error)!='InvocationDoesNotExist':raise
            time.sleep(5);continue
        if r['Status'] in ('Pending','InProgress','Delayed'):time.sleep(5);continue
        try:observed=json.loads(r.get('StandardOutputContent',''))
        except (ValueError,TypeError):observed={}
        status=observed.get('status','UNKNOWN')
        if status not in {'SUCCEEDED','ROLLED_BACK','REJECTED','MANUAL_RECOVERY_REQUIRED','STOP_REVIEW_REQUIRED'}:status='UNKNOWN'
        if status=='SUCCEEDED' and (r['Status']!='Success' or r['ResponseCode']!=0):status='UNKNOWN'
        return {k:intent[k] for k in ('commit','run_id','attempt')}|{'command_id':cid,'status':status,
            'reason':observed['reason'] if observed.get('reason') in REASONS else 'REVIEW_REQUIRED'}
    raise ValueError('STATUS_UNKNOWN_DO_NOT_REDISPATCH')


def dispatch():
    commit,run,attempt=guard();api=clients()
    caller=api['sts'].get_caller_identity()
    need(caller['Account']==ACCOUNT and caller['Arn'].startswith(f'arn:aws:sts::{ACCOUNT}:assumed-role/JjikmukChatbotAutoDeploy/'),'CHATBOT_ROLE_REQUIRED')
    root='receipts/chatbot-cd/'+commit;s3=api['s3'];intent=get_receipt(s3,root+'/intent.json')
    if intent:
        need(intent['commit']==commit and intent['document']==DOCUMENT and intent['instance']==INSTANCE,'CHATBOT_INTENT_CHANGED')
        # Successful collection reports the original attempt, never a second mutation.
        return wait_result(api['ssm'],intent)
    backup=select_snapshot(api['rds'])
    need(s3.get_bucket_versioning(Bucket=BUCKET,ExpectedBucketOwner=ACCOUNT).get('Status')=='Enabled','VERSIONING_REQUIRED')
    m=json.loads(Path('release/manifest.json').read_bytes())
    need([m[k] for k in ('commit','run_id','attempt')]==[commit,run,attempt]
         and Path('release/chatbot.zip').stat().st_size==m['archive_bytes']
         and sha(Path('release/chatbot.zip').read_bytes())==m['archive_sha256'],'CHATBOT_DOWNLOAD_CHANGED')
    # Durable claim precedes all publication; a partial upload cannot silently restart.
    put_receipt(s3,root+'/claim.json',{'commit':commit,'run_id':run,'attempt':attempt})
    versions={}
    for name in ('manifest.json','chatbot.zip'):
        with open('release/'+name,'rb') as stream:
            response=s3.put_object(Bucket=BUCKET,Key=f'artifacts/chatbot/{commit}/{run}-{attempt}/{name}',Body=stream,
                ExpectedBucketOwner=ACCOUNT,ServerSideEncryption='AES256',ChecksumAlgorithm='SHA256',IfNoneMatch='*')
        version=response.get('VersionId','');need(version not in ('','null'),'CHATBOT_VERSION_REQUIRED');versions[name]=version
    parameters={'ReleaseCommit':[commit],'RunId':[run],'RunAttempt':[attempt],'ArchiveSha256':[m['archive_sha256']],
                'ArchiveVersion':[versions['chatbot.zip']],'ManifestVersion':[versions['manifest.json']]}
    intent=dict(commit=commit,run_id=run,attempt=attempt,document=DOCUMENT,instance=INSTANCE,backup=backup,
        comment=f'chatbot-auto:{commit}:{run}-{attempt}',parameters=parameters)
    guard();put_receipt(s3,root+'/intent.json',intent)
    try:api['ssm'].send_command(InstanceIds=[INSTANCE],DocumentName=DOCUMENT,DocumentVersion='1',
        Parameters=parameters,TimeoutSeconds=60,Comment=intent['comment'])
    except Exception:pass
    result=wait_result(api['ssm'],intent);put_receipt(s3,root+'/result.json',result)
    return result


if __name__=='__main__':
    try:
        if sys.argv[1]=='package':
            commit,run,attempt=identity();build('source',commit,run,attempt,'release')
        elif sys.argv[1]=='dispatch':
            result=dispatch();report(result);raise SystemExit(0 if result['status']=='SUCCEEDED' else 1)
        else:raise ValueError('MODE_REJECTED')
    except Exception as error:
        report({'status':'UNKNOWN','reason':str(error) if str(error) in REASONS else 'REVIEW_REQUIRED'})
        raise SystemExit(1)
