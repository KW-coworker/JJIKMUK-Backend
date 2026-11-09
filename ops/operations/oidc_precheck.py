"""Verify the actual GitHub-issued claim before the human's sole AWS setup. No AWS calls."""
import base64
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
from connection import REPO, REPO_ID, CHATBOT_REPO, CHATBOT_REPO_ID
from bootstrap import need
from control import NoRedirect


def validate_claims(claims,env):
    environment = env.get('OIDC_ENVIRONMENT', 'production')
    need(environment in ('production', 'backend-production','chatbot-production'), 'UNSUPPORTED_OIDC_ENVIRONMENT')
    repo,repo_id,ref=(CHATBOT_REPO,CHATBOT_REPO_ID,'refs/heads/chatbot') if environment=='chatbot-production' else (REPO,REPO_ID,'refs/heads/main')
    need(claims.get('iss')=='https://token.actions.githubusercontent.com' and claims.get('aud')=='sts.amazonaws.com',
         'OIDC_ISSUER_OR_AUDIENCE')
    need(claims.get('sub')=='repo:'+repo+':environment:'+environment and str(claims.get('repository_id'))==str(repo_id),
         'OIDC_SUBJECT_OR_REPOSITORY')
    need(claims.get('ref')==ref and claims.get('sha')==env['GITHUB_SHA']
         and str(claims.get('run_id'))==env['GITHUB_RUN_ID'],'OIDC_RUN_CONTEXT')
    return {'status':'OIDC_CLAIMS_VERIFIED_NO_AWS','repository_id':repo_id,
            'subject':claims['sub'],'commit':claims['sha'],'run_id':claims['run_id']}


def main():
    need(os.environ.get('GITHUB_ACTIONS')=='true','GITHUB_ONLY')
    source=os.environ['ACTIONS_ID_TOKEN_REQUEST_URL'];url=urllib.parse.urlsplit(source)
    need(url.scheme=='https' and url.hostname.endswith('.actions.githubusercontent.com') and not url.username,
         'OIDC_ENDPOINT_REJECTED')
    query=urllib.parse.parse_qsl(url.query);query.append(('audience','sts.amazonaws.com'))
    request=urllib.request.Request(urllib.parse.urlunsplit(url._replace(query=urllib.parse.urlencode(query))),
        headers={'Authorization':'Bearer '+os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=15) as response:
        raw=response.read(32769);need(len(raw)<=32768,'OIDC_RESPONSE_LIMIT')
        token=json.loads(raw)['value']
    parts=token.split('.');need(len(parts)==3,'OIDC_TOKEN_FORMAT')
    claims=json.loads(base64.urlsafe_b64decode(parts[1]+'='*((4-len(parts[1])%4)%4)))
    result=validate_claims(claims,os.environ)
    token=None;raw=None;parts=None;claims=None
    path=Path('operation-results');path.mkdir(exist_ok=True)
    (path/'oidc-precheck.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':
    try:main()
    except Exception:print('OIDC_PRECHECK_FAILED_NO_TOKEN_OUTPUT');raise SystemExit(1)
