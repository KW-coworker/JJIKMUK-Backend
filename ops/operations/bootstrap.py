"""One human-admin CloudShell setup. No session export; never installs an application."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request
from connection import (ACCOUNT, REGION, REPO, REPO_ID, HOSTS, HOST_ROLE, BUCKET, STACK,
                        READ_ROLE, WRITE_ROLE, READ_DOCUMENT, DEPLOY_DOCUMENT, template, canonical, sha)


def need(value, code):
    if not value:raise ValueError(code)


def github(path):
    request=urllib.request.Request('https://api.github.com/repos/'+REPO+'/'+path,
                                   headers={'User-Agent':'jjikmuk-operations-setup','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request,timeout=20) as response:
        need(response.url.startswith('https://api.github.com/'),'GITHUB_REDIRECT')
        data=response.read(1048577);need(len(data)<=1048576,'GITHUB_RESPONSE_LIMIT')
        return json.loads(data)


def check_github(commit):
    need(re.fullmatch('[0-9a-f]{40}',commit),'EXPECTED_MAIN_REQUIRED')
    need(github('git/ref/heads/main')['object']['sha']==commit,'MAIN_CHANGED')
    repo=github('');need(repo['id']==REPO_ID,'REPOSITORY_ID_CHANGED')
    oidc=github('actions/oidc/customization/sub')
    need(oidc.get('use_default') is True and oidc.get('use_immutable_subject') is False,'OIDC_SUBJECT_CHANGED')
    workflow=github('actions/workflows/server-operations.yml')
    need(workflow['state']=='active','WORKFLOW_NOT_ACTIVE')
    environment=github('environments/production')
    rules=environment.get('protection_rules',[])
    need(any(r.get('type')=='required_reviewers' and r.get('reviewers') for r in rules),'PRODUCTION_REVIEWER_REQUIRED')
    need(environment.get('can_admins_bypass') is False,'PRODUCTION_ADMIN_BYPASS')
    branches=github('environments/production/deployment-branch-policies')['branch_policies']
    need(len(branches)==1 and branches[0]['name']=='main' and branches[0].get('type','branch')=='branch',
         'PRODUCTION_MAIN_ONLY_REQUIRED')
    return {'repository_id':REPO_ID,'main':commit,'production_reviewers_configured':True}


def aws_clients():
    # Only called by the human in their existing administrator CloudShell login.
    need('CLOUDSHELL' in os.environ.get('AWS_EXECUTION_ENV','').upper(),'HUMAN_CLOUDSHELL_REQUIRED')
    import boto3
    from botocore.config import Config
    sdk=boto3.Session(region_name=REGION)
    config=Config(connect_timeout=10,read_timeout=30,retries={'total_max_attempts':1})
    return {s:sdk.client(s,region_name=REGION,config=config) for s in ('sts','iam','ssm','ec2','s3','cloudformation')}


def absent(call,**kwargs):
    try:call(**kwargs)
    except Exception as error:
        code=getattr(error,'response',{}).get('Error',{}).get('Code')
        if code in ('NoSuchEntity','InvalidDocument','NoSuchBucket','404'):return
        if code=='ValidationError' and 'does not exist' in str(getattr(error,'response',{}).get('Error',{}).get('Message','')):return
        raise
    raise ValueError('SETUP_RESOURCE_ALREADY_EXISTS')


def preflight(clients,commit):
    gh=check_github(commit)
    identity=clients['sts'].get_caller_identity();need(identity['Account']==ACCOUNT,'WRONG_AWS_ACCOUNT')
    # All required APIs must be usable by the human's administrator, without changing users.
    iam=clients['iam']; ec2=clients['ec2']; ssm=clients['ssm']; cf=clients['cloudformation']
    absent(cf.describe_stacks,StackName=STACK)
    for name in (READ_ROLE,WRITE_ROLE):
        absent(iam.get_role,RoleName=name)
        absent(iam.get_policy,PolicyArn=f'arn:aws:iam::{ACCOUNT}:policy/{name}Policy')
    absent(iam.get_role_policy,RoleName=HOST_ROLE,PolicyName='JjikmukOperationsArtifactRead')
    absent(ssm.describe_document,Name=READ_DOCUMENT)
    absent(ssm.describe_document,Name=DEPLOY_DOCUMENT)
    absent(clients['s3'].head_bucket,Bucket=BUCKET,ExpectedBucketOwner=ACCOUNT)
    profiles=iam.get_instance_profile(InstanceProfileName=HOST_ROLE)['InstanceProfile']
    need([r['RoleName'] for r in profiles['Roles']]==[HOST_ROLE],'HOST_ROLE_CHANGED')
    response=ec2.describe_instances(InstanceIds=list(HOSTS.values()))
    instances=[i for r in response['Reservations'] for i in r['Instances']]
    need({i['InstanceId'] for i in instances}==set(HOSTS.values()),'HOST_SET_CHANGED')
    for i in instances:
        need(i.get('IamInstanceProfile',{}).get('Arn')==f'arn:aws:iam::{ACCOUNT}:instance-profile/{HOST_ROLE}'
             and i['State']['Name']=='running','HOST_PROFILE_OR_STATE_CHANGED')
    associated=ec2.describe_iam_instance_profile_associations()
    bindings=list(associated['IamInstanceProfileAssociations'])
    while associated.get('NextToken'):
        need(len(bindings)<1000,'PROFILE_ASSOCIATION_LIMIT')
        associated=ec2.describe_iam_instance_profile_associations(NextToken=associated['NextToken'])
        bindings.extend(associated['IamInstanceProfileAssociations'])
    selected=[a for a in bindings if a['IamInstanceProfile']['Arn']==profiles['Arn']]
    need({a['InstanceId'] for a in selected if a['State']=='associated'}==set(HOSTS.values())
         and all(a['State']=='associated' for a in selected),'SHARED_HOST_PROFILE_REQUIRES_REVIEW')
    nodes=ssm.describe_instance_information(Filters=[{'Key':'InstanceIds','Values':list(HOSTS.values())}])
    need({n['InstanceId'] for n in nodes['InstanceInformationList'] if n['PingStatus']=='Online' and n['PlatformType']=='Linux'}
         ==set(HOSTS.values()),'BOTH_HOSTS_MUST_BE_SSM_ONLINE')
    provider=f'arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com'
    existing=True
    try:
        p=iam.get_open_id_connect_provider(OpenIDConnectProviderArn=provider)
        need(p['Url'] in ('token.actions.githubusercontent.com','https://token.actions.githubusercontent.com')
             and 'sts.amazonaws.com' in p['ClientIDList'],'EXISTING_PROVIDER_DIFFERENT')
    except Exception as error:
        if getattr(error,'response',{}).get('Error',{}).get('Code')=='NoSuchEntity':existing=False
        else:raise
    raw=canonical(template());need(len(raw)<=51200,'TEMPLATE_SIZE_LIMIT')
    cf.validate_template(TemplateBody=raw.decode())
    return raw,existing,gh


def create_connection(clients,commit,approved_hash,journal,confirm=input,sleep=time.sleep):
    need(not journal.exists() and not journal.is_symlink(),'KEEP_EXISTING_JOURNAL_NO_RETRY')
    raw,existing,gh=preflight(clients,commit)
    need(sha(raw)==approved_hash,'APPROVED_TEMPLATE_CHANGED')
    need(confirm('Type CONNECT JJIKMUK OPERATIONS ONCE: ')=='CONNECT JJIKMUK OPERATIONS ONCE','NOT_CONFIRMED')
    state={'status':'CREATE_INTENT','template_sha256':approved_hash,'main':commit,'operations':[]}
    with journal.open('x',encoding='utf-8') as log:
        os.chmod(journal,0o600)
        def save():
            log.seek(0);json.dump(state,log);log.truncate();log.flush();os.fsync(log.fileno())
        save()
        try:
            response=clients['cloudformation'].create_stack(StackName=STACK,TemplateBody=raw.decode(),
                Parameters=[{'ParameterKey':'ExistingGitHubProvider','ParameterValue':str(existing).lower()}],
                Capabilities=['CAPABILITY_NAMED_IAM'],DisableRollback=True,
                ClientRequestToken='setup-'+approved_hash,Tags=[{'Key':'Project','Value':'JJIKMUK'}])
            state.update(stack_id=response['StackId'],status='STACK_REQUESTED');save()
            for _ in range(180):
                stack=clients['cloudformation'].describe_stacks(StackName=state['stack_id'])['Stacks'][0]
                status=stack['StackStatus']
                if status=='CREATE_COMPLETE':break
                need(status=='CREATE_IN_PROGRESS','STACK_STOPPED_KEEP_RESOURCES')
                sleep(5)
            else:raise ValueError('STACK_WAIT_LIMIT_AGENT_CAN_OBSERVE_DO_NOT_RECREATE')
            report={'status':'CONNECTION_CREATED','account':ACCOUNT,'region':REGION,'hosts':HOSTS,
                    'main':commit,'template_sha256':approved_hash,'stack_id':state['stack_id'],
                    'utc':datetime.now(timezone.utc).isoformat(),'github':gh,
                    'application_installations':0,'deployments':0,'credential_export':False}
            # Non-secret receipt retrieved later by the GitHub read role; no user download.
            clients['s3'].put_object(Bucket=BUCKET,Key='connection/setup.json',Body=canonical(report),
                ContentType='application/json',ServerSideEncryption='AES256',IfNoneMatch='*',ExpectedBucketOwner=ACCOUNT)
            state['status']='CONNECTION_CREATED';save()
            print('CONNECTION_CREATED_NO_DOWNLOAD_NO_OPERATOR_SWITCH')
            return report
        except Exception:
            state['status']='STOPPED_KEEP_RECORDS_NO_RETRY';save();raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--human-cloudshell',action='store_true',required=True)
    parser.add_argument('--main',required=True);parser.add_argument('--approved-template-sha256',required=True)
    args=parser.parse_args()
    try:
        need(re.fullmatch('[0-9a-f]{64}',args.approved_template_sha256),'APPROVAL_HASH_REQUIRED')
        create_connection(aws_clients(),args.main,args.approved_template_sha256,
                          Path('/home/cloudshell-user/jjikmuk-operations-setup.json'))
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) else type(error).__name__
        print('STOP: '+code+'. Preserve records; do not repeat setup.');raise SystemExit(1)
