"""Local approved upload using existing GitHub login. No CloudShell/session file.

The ephemeral private key lives only in this process. A lost PUT response ends
with an unknown outcome; inspect the private object with OIDC, never resend.
"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request
import uuid
import zipfile
from connection import REPO,canonical,sha
from control import GitHub,NoRedirect
from bootstrap import need
from upload_ticket import open_ticket,validate,object_key


def file_sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
    return h.hexdigest()


def run(api,path,approval,journal,sleep=time.sleep):
    need(not journal.exists() and not journal.is_symlink(),'UPLOAD_JOURNAL_EXISTS_NO_REPLAY')
    need(path.is_file() and not path.is_symlink(),'UPLOAD_REGULAR_FILE_REQUIRED')
    digest=file_sha(path);size=path.stat().st_size
    need(approval.get('status')=='APPROVED' and approval.get('sha256')==digest and approval.get('bytes')==size
         and re.fullmatch('[a-f0-9]{40}',approval.get('commit','')),'EXACT_UPLOAD_APPROVAL_REQUIRED')
    need(api.call('/repos/'+REPO+'/git/ref/heads/main')['object']['sha']==approval['commit'],'MAIN_CHANGED')
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    private=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    public=private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    binding=dict(request_id=uuid.uuid4().hex,commit=approval['commit'],sha256=digest,bytes=size,public_key=public,expires=approval['expires'])
    validate(binding)
    inputs={'expected_sha':binding['commit'],'request_id':binding['request_id'],
        'binding':base64.b64encode(canonical(binding)).decode(),'confirm':True}
    state={'status':'DISPATCH_INTENT','binding':binding,'input_sha256':sha(canonical(inputs))}
    # A persistent non-secret journal prevents duplicate workflow dispatch after a crash.
    with journal.open('x',encoding='utf-8') as stream:
        os.chmod(journal,0o600)
        def save():stream.seek(0);json.dump(state,stream);stream.truncate();stream.flush();os.fsync(stream.fileno())
        save()
        api.call('/repos/'+REPO+'/actions/workflows/server-private-upload.yml/dispatches','POST',{'ref':'main','inputs':inputs})
        title='Private upload at '+binding['commit']+' ['+binding['request_id']+']'
        run=None
        for _ in range(180):
            runs=api.call('/repos/'+REPO+'/actions/workflows/server-private-upload.yml/runs?event=workflow_dispatch&per_page=100')['workflow_runs']
            matches=[r for r in runs if r.get('display_title')==title]
            need(len(matches)<=1,'UPLOAD_AMBIGUOUS_RUN')
            if matches:
                run=matches[0]
                need(run['head_sha']==binding['commit'] and run['head_branch']=='main' and run['run_attempt']==1
                     and run['path']=='.github/workflows/server-private-upload.yml','UPLOAD_RUN_CHANGED')
                state['run_id']=run['id'];save()
                pending=api.call(f'/repos/{REPO}/actions/runs/{run["id"]}/pending_deployments')
                if pending:
                    need(len(pending)==1 and pending[0]['environment']['name']=='production'
                         and pending[0]['current_user_can_approve'] is True,'UPLOAD_REVIEWER_UNAVAILABLE')
                    if not state.get('environment_approved'):
                        state['environment_approval_intent']=True;save()
                        api.call(f'/repos/{REPO}/actions/runs/{run["id"]}/pending_deployments','POST',{
                            'environment_ids':[pending[0]['environment']['id']],'state':'approved',
                            'comment':'User approved this exact object upload only. No server execution.'})
                        state['environment_approved']=True;save()
                if run['status']=='completed':break
            sleep(5)
        else:raise ValueError('UPLOAD_WAIT_LIMIT_NO_REDISPATCH')
        need(run['conclusion']=='success' and state.get('environment_approved') is True,'UPLOAD_TICKET_NOT_APPROVED')
        artifacts=api.call(f'/repos/{REPO}/actions/runs/{run["id"]}/artifacts')['artifacts']
        matches=[x for x in artifacts if x['name']==f'encrypted-upload-{run["id"]}-1' and not x['expired']]
        need(len(matches)==1,'UPLOAD_CIPHERTEXT_MISSING')
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cd'))
        from notify import GitHub as ArtifactReader
        data=ArtifactReader(REPO,api.token).artifact(matches[0]['id'])
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            need(z.namelist()==['ticket.json'] and z.getinfo('ticket.json').file_size<32768,'UPLOAD_CIPHERTEXT_ARCHIVE')
            ticket=open_ticket(private,binding,json.loads(z.read('ticket.json')))
        need(ticket['run_id']==str(run['id']) and ticket['attempt']=='1','UPLOAD_TICKET_RUN_MISMATCH')
        need(path.stat().st_size==size and file_sha(path)==digest,'UPLOAD_LOCAL_FILE_CHANGED')
        state['status']='PUT_INTENT';save()
        opener=urllib.request.build_opener(NoRedirect(),urllib.request.ProxyHandler({}))
        with path.open('rb') as body:
            request=urllib.request.Request(ticket['url'],data=body,method='PUT',headers=ticket['headers'])
            with opener.open(request,timeout=600) as response:
                need(response.status==200,'UPLOAD_RESPONSE_UNKNOWN')
                version=response.headers.get('x-amz-version-id','')
                need(re.fullmatch('[A-Za-z0-9._~+/-]{1,1024}',version) and version!='null','UPLOAD_VERSION_UNKNOWN')
        state.update(status='UPLOADED_REQUIRES_INDEPENDENT_HEAD_CHECK',key=object_key(binding),version=version);save()
        private=None;ticket=None
        return {k:state[k] for k in ('status','key','version','run_id')}|{'sha256':digest,'bytes':size,'request_id':binding['request_id']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--package',required=True);parser.add_argument('--approval',required=True);parser.add_argument('--journal',required=True)
    args=parser.parse_args();api=None
    try:
        api=GitHub();print(json.dumps(run(api,Path(args.package),json.loads(Path(args.approval).read_bytes()),Path(args.journal))))
    except Exception:
        print('PRIVATE_UPLOAD_STOPPED_KEEP_JOURNAL_NO_RETRY_NO_SECRET_OUTPUT');raise SystemExit(1)
    finally:
        if api:api.close()
