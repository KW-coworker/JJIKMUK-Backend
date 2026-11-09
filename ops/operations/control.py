"""Local Codex controller: existing GitHub login only, never AWS session files.

The controller prepares/dispatches a reviewed main workflow and reads its state.
Deployment-environment approval remains a separate explicitly authorized API action.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request
import urllib.error
from connection import REPO,REPO_ID,canonical,sha
from bootstrap import need


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('GITHUB_REDIRECT_REFUSED')


class GitHub:
    def __init__(self):
        result=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\npath='+REPO+'.git\n\n',
            capture_output=True,text=True,timeout=30,env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'Never'})
        need(result.returncode==0,'EXISTING_GITHUB_LOGIN_UNAVAILABLE')
        values=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
        self.token=values.get('password');need(bool(self.token),'EXISTING_GITHUB_LOGIN_UNAVAILABLE')
        values.clear();result=None
        self.opener=urllib.request.build_opener(NoRedirect())

    def call(self,path,method='GET',payload=None):
        need(path=='/user' or path.startswith('/repos/'+REPO+'/') or path=='/repos/'+REPO,'GITHUB_TARGET_REJECTED')
        request=urllib.request.Request('https://api.github.com'+path,
            data=None if payload is None else canonical(payload),method=method,
            headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json',
                     'Content-Type':'application/json','User-Agent':'JJIKMUK-Operations',
                     'X-GitHub-Api-Version':'2022-11-28'})
        try:
            with self.opener.open(request,timeout=30) as response:
                raw=response.read(2*1024*1024+1);need(len(raw)<=2*1024*1024,'GITHUB_RESPONSE_LIMIT')
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            raise ValueError('GITHUB_HTTP_'+str(error.code)) from None

    def close(self):self.token=None


def check(api):
    me=api.call('/user');repo=api.call('/repos/'+REPO)
    need(repo['id']==REPO_ID,'GITHUB_REPOSITORY_CHANGED')
    environments=api.call('/repos/'+REPO+'/environments')
    return {'actor':me['login'],'actor_id':me['id'],'push':repo['permissions']['push'],
            'admin':repo['permissions']['admin'],'environments':[e['name'] for e in environments['environments']],
            'credentials_exported':False,'aws_credentials_used':False}


def dispatch(api,request,journal):
    need(set(request)=={'workflow','inputs','approval'},'DISPATCH_SCHEMA')
    need(request['workflow']=='server-operations.yml','WORKFLOW_REJECTED')
    inputs=request['inputs'];need(inputs.get('mode') in ('precheck','inspect','execute','collect'),'MODE_REJECTED')
    need(set(inputs)<={'mode','expected_sha','plan','plan_sha256','operation_id','confirm','request_id'}
         and re.fullmatch('[0-9a-f]{32}',inputs.get('request_id','')),'REQUEST_FIELDS_REJECTED')
    need(re.fullmatch('[0-9a-f]{40}',inputs.get('expected_sha','')),'EXACT_SHA_REQUIRED')
    need(api.call('/repos/'+REPO+'/git/ref/heads/main')['object']['sha']==inputs['expected_sha'],'MAIN_CHANGED')
    approval=request['approval']
    need(approval.get('status')=='APPROVED' and approval.get('input_sha256')==sha(canonical(inputs)),'EXACT_USER_APPROVAL_REQUIRED')
    if inputs['mode']=='execute':need(inputs.get('confirm') is True,'WRITE_CONFIRMATION_REQUIRED')
    need(not journal.exists(),'DISPATCH_INTENT_EXISTS_DO_NOT_REPLAY')
    with journal.open('x',encoding='utf-8') as f:
        json.dump({'status':'DISPATCH_INTENT','workflow':request['workflow'],'inputs':inputs},f);f.flush();os.fsync(f.fileno())
    api.call('/repos/'+REPO+'/actions/workflows/'+request['workflow']+'/dispatches','POST',{'ref':'main','inputs':inputs})
    return {'status':'DISPATCH_ACCEPTED','collect_runs':True,'credentials_exported':False}


def approve_environment(api,run_id,approval):
    need(re.fullmatch('[1-9][0-9]{0,19}',run_id),'RUN_ID_INVALID')
    need(approval.get('status')=='APPROVED' and str(approval.get('run_id'))==run_id,
         'EXACT_ENVIRONMENT_APPROVAL_REQUIRED')
    run=api.call('/repos/'+REPO+'/actions/runs/'+run_id)
    need(run.get('path')=='.github/workflows/server-operations.yml' and run['head_branch']=='main'
         and run['head_sha']==approval.get('expected_sha'),'APPROVED_RUN_MISMATCH')
    request_id=approval.get('request_id','');need(re.fullmatch('[0-9a-f]{32}',request_id),'REQUEST_ID_REQUIRED')
    mode=approval.get('mode','execute');need(mode in ('precheck','execute'),'ENVIRONMENT_MODE_REJECTED')
    need(run.get('display_title')=='Server operations '+mode+' at '+approval['expected_sha']+' ['+request_id+']',
         'APPROVED_REQUEST_MISMATCH')
    pending=api.call('/repos/'+REPO+'/actions/runs/'+run_id+'/pending_deployments')
    need(len(pending)==1 and pending[0]['environment']['name']=='production'
         and pending[0]['current_user_can_approve'] is True,'APPROVER_IDENTITY_REQUIRED')
    return api.call('/repos/'+REPO+'/actions/runs/'+run_id+'/pending_deployments','POST',{
        'environment_ids':[pending[0]['environment']['id']],'state':'approved',
        'comment':'User explicitly approved this exact operation; Codex submits the recorded approval.'})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['check','dispatch','runs','approve-environment'])
    p.add_argument('--request');p.add_argument('--journal');p.add_argument('--run-id');p.add_argument('--approval')
    args=p.parse_args();api=None
    try:
        api=GitHub()
        if args.mode=='check':result=check(api)
        elif args.mode=='dispatch':result=dispatch(api,json.loads(Path(args.request).read_bytes()),Path(args.journal))
        elif args.mode=='approve-environment':
            approve_environment(api,args.run_id,json.loads(Path(args.approval).read_bytes()));result={'status':'ENVIRONMENT_APPROVAL_SUBMITTED'}
        else:
            runs=api.call('/repos/'+REPO+'/actions/workflows/server-operations.yml/runs?event=workflow_dispatch&per_page=10')['workflow_runs']
            result={'runs':[{k:r[k] for k in ('id','status','conclusion','head_sha','html_url')} for r in runs]}
        print(json.dumps(result))
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{0,100}',str(error)) else type(error).__name__
        print(json.dumps({'status':'STOPPED','code':code,'retry':False}));raise SystemExit(1)
    finally:
        if api:api.close()
