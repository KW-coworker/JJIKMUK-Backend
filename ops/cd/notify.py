"""Observe a completed trusted CD run; no AWS access and no untrusted code execution."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from notices import TARGETS,need,parse_result,classify,message


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


class GitHub:
    def __init__(self,repo,token):
        need(repo in TARGETS,'NOTICE_REPOSITORY')
        self.repo=repo;self.token=token
        self.opener=urllib.request.build_opener(NoRedirect(),urllib.request.ProxyHandler({}))

    def request(self,path,method='GET',body=None):
        need(path.startswith('/') and '://' not in path,'NOTICE_API_PATH')
        request=urllib.request.Request('https://api.github.com/repos/'+self.repo+path,method=method,
            data=None if body is None else json.dumps(body).encode(),headers={
                'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json',
                'Content-Type':'application/json','User-Agent':'JJIKMUK-CD-notifications'})
        with self.opener.open(request,timeout=25) as response:
            raw=response.read(2*1024**2+1);need(len(raw)<=2*1024**2,'NOTICE_API_LIMIT')
            return json.loads(raw) if raw else None

    def pages(self,path,key=None):
        rows=[]
        for page in range(1,11):
            result=self.request(path+('&' if '?' in path else '?')+f'per_page=100&page={page}')
            batch=result[key] if key else result
            rows.extend(batch)
            if len(batch)<100:return rows
        raise ValueError('NOTICE_PAGINATION_LIMIT')

    def artifact(self,artifact_id):
        need(type(artifact_id) is int and artifact_id>0,'NOTICE_ARTIFACT_ID')
        request=urllib.request.Request(f'https://api.github.com/repos/{self.repo}/actions/artifacts/{artifact_id}/zip',
            headers={'Authorization':'Bearer '+self.token,'User-Agent':'JJIKMUK-CD-notifications'})
        try:self.opener.open(request,timeout=25)
        except urllib.error.HTTPError as e:
            need(e.code==302,'NOTICE_DOWNLOAD_RESPONSE');url=e.headers['Location']
        else:raise ValueError('NOTICE_DOWNLOAD_REDIRECT_REQUIRED')
        parts=urllib.parse.urlsplit(url)
        need(parts.scheme=='https' and not parts.username and parts.port in (None,443)
             and parts.hostname.endswith(('.blob.core.windows.net','.actions.githubusercontent.com')),'NOTICE_DOWNLOAD_HOST')
        # Auth is deliberately not forwarded to artifact storage.
        with self.opener.open(urllib.request.Request(url),timeout=30) as response:
            data=response.read(1024**2+1);need(len(data)<=1024**2,'NOTICE_ARCHIVE_LIMIT')
            return data


def observe(api,event):
    repo=api.repo;branch,workflow,component=TARGETS[repo]
    supplied=event['workflow_run']
    run=api.request('/actions/runs/'+str(supplied['id'])+'/attempts/'+str(supplied['run_attempt']))
    need(run['head_sha']==supplied['head_sha'] and run['run_attempt']==supplied['run_attempt'],'NOTICE_RUN_CHANGED')
    need(run['repository']['full_name']==repo and run['head_repository']['full_name']==repo,'NOTICE_RUN_REPOSITORY')
    if run['head_branch']!=branch or run['event']!='push' or run['name']!=workflow:
        return {'status':'IGNORED_NON_PRODUCTION_RUN'}
    expected_path='.github/workflows/'+('backend-cd.yml' if component=='backend' else 'chatbot-cd.yml')
    need(run['path']==expected_path and run['status']=='completed','NOTICE_WORKFLOW_IDENTITY')
    if run['conclusion']=='success':return {'status':'NO_FAILURE_NOTIFICATION'}
    jobs=api.pages(f'/actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs','jobs')
    result=None
    artifacts=api.pages(f'/actions/runs/{run["id"]}/artifacts','artifacts')
    expected_name=f'deployment-result-{run["id"]}-{run["run_attempt"]}'
    matches=[a for a in artifacts if a['name']==expected_name and not a['expired']]
    if len(matches)==1:
        try: result=parse_result(api.artifact(matches[0]['id']),run)
        except (ValueError,KeyError,TypeError,zipfile.BadZipFile,urllib.error.URLError,TimeoutError): result=None
    outcome=classify(run,jobs,result)
    prs=api.pages('/commits/'+run['head_sha']+'/pulls')
    prs=[p for p in prs if p.get('merged_at') and p['base']['ref']==branch and p.get('merge_commit_sha')==run['head_sha']]
    people=[run.get('actor',{}).get('login')]
    for p in prs:
        detail=api.request('/pulls/'+str(p['number']))
        people.extend([detail['user']['login'],(detail.get('merged_by') or {}).get('login')])
    marker,body=message(repo,run,outcome,people)
    if prs:
        for p in prs:
            comments=api.pages('/issues/'+str(p['number'])+'/comments')
            if any(marker in c['body'] and c.get('user',{}).get('type')=='Bot' for c in comments):continue
            api.request('/issues/'+str(p['number'])+'/comments','POST',{'body':body})
    else:
        # Direct pushes have no PR thread; create one auditable incident issue.
        issues=api.pages('/issues?state=all&creator=github-actions%5Bbot%5D')
        if not any(marker in (i.get('body') or '') for i in issues):
            api.request('/issues','POST',{'title':f'[CD] {component} deployment needs review ({run["head_sha"][:12]})','body':body})
    return {'status':'NOTIFICATION_RECORDED','run_id':run['id'],'outcome':outcome['status']}


if __name__=='__main__':
    try:
        need(os.environ.get('GITHUB_EVENT_NAME')=='workflow_run','NOTICE_COMPLETED_RUN_REQUIRED')
        event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_bytes())
        print(json.dumps(observe(GitHub(os.environ['GITHUB_REPOSITORY'],os.environ['GH_TOKEN']),event)))
    except Exception:
        # Network exception strings can contain signed artifact URLs.
        print('NOTIFICATION_DELIVERY_FAILED_NO_DEPLOYMENT_RETRY');raise SystemExit(1)
