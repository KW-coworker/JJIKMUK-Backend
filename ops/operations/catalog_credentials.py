"""In-memory GitHub OIDC renewal for one bounded catalog phase, never IAM changes."""
import base64
from datetime import datetime
import json
import os
import re
import time
import urllib.parse
import urllib.request
from bootstrap import need
from connection import ACCOUNT,REGION,REPO,WRITE_ROLE
from control import NoRedirect
from oidc_precheck import validate_claims


class Renewal:
    def __init__(self,env,sts,*,seconds,clock=time.time,monotonic=time.monotonic,opener=None):
        need(type(seconds) is int and 60<=seconds<=9000,'CATALOG_CREDENTIAL_BUDGET')
        self.env=dict(env);self.sts=sts;self.clock=clock;self.monotonic=monotonic
        self.until=clock()+seconds;self.monotonic_until=monotonic()+seconds
        self.opener=opener or urllib.request.build_opener(NoRedirect())
        self.failed=False;self.renewals=0
        need(env.get('GITHUB_ACTIONS')=='true' and env.get('GITHUB_RUN_ATTEMPT')=='1' and
             env.get('GITHUB_WORKFLOW_REF')==REPO+'/.github/workflows/server-maintenance.yml@refs/heads/main' and
             env.get('OPERATIONS_CONFIRM')=='true' and env.get('MAINTENANCE_MODE')=='catalog-reapply',
             'CATALOG_RENEWAL_CONTEXT')
        need(re.fullmatch('[1-9][0-9]{0,19}',env.get('GITHUB_RUN_ID','')),'CATALOG_RENEWAL_RUN')
        self.session_name='catalog-'+env['GITHUB_RUN_ID']

    def check(self):
        need(not self.failed and self.clock()<self.until and self.monotonic()<self.monotonic_until,
             'CATALOG_RENEWAL_STOPPED_OR_EXPIRED')

    def before_sign(self,**unused):
        self.check()

    def admit(self,seconds):
        self.check()
        need(type(seconds) is int and seconds>0 and
             min(self.until-self.clock(),self.monotonic_until-self.monotonic())>seconds,
             'CATALOG_REMAINING_TIME_INSUFFICIENT')

    def token(self):
        self.check()
        url=urllib.parse.urlsplit(self.env['ACTIONS_ID_TOKEN_REQUEST_URL'])
        need(url.scheme=='https' and bool(url.hostname) and url.hostname.endswith('.actions.githubusercontent.com') and
             not url.username and not url.password and url.port in (None,443) and not url.fragment,'CATALOG_OIDC_ENDPOINT')
        query=urllib.parse.parse_qsl(url.query,keep_blank_values=True)
        need(not any(k=='audience' for k,v in query),'CATALOG_OIDC_DUPLICATE_AUDIENCE')
        query.append(('audience','sts.amazonaws.com'))
        request=urllib.request.Request(urllib.parse.urlunsplit(url._replace(query=urllib.parse.urlencode(query))),
            headers={'Authorization':'Bearer '+self.env['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
        with self.opener.open(request,timeout=15) as response:
            raw=response.read(32769);need(len(raw)<=32768,'CATALOG_OIDC_SIZE')
        token=json.loads(raw)['value']
        need(type(token) is str and len(token)<=24000,'CATALOG_OIDC_TOKEN_SIZE')
        parts=token.split('.');need(len(parts)==3,'CATALOG_OIDC_FORMAT')
        claims=json.loads(base64.urlsafe_b64decode(parts[1]+'='*((4-len(parts[1])%4)%4)))
        # Local checks bind the run; AWS validates the signature and role trust.
        validate_claims(claims,dict(self.env,OIDC_ENVIRONMENT='production'))
        need(claims.get('workflow_ref')==self.env['GITHUB_WORKFLOW_REF'] and str(claims.get('run_attempt'))=='1' and
             type(claims.get('exp')) is int and self.clock()<claims['exp']<=self.clock()+600,'CATALOG_OIDC_EXPIRY_OR_WORKFLOW')
        self.check()
        return token

    def refresh(self):
        try:
            self.check()
            token=self.token()
            response=self.sts.assume_role_with_web_identity(RoleArn=f'arn:aws:iam::{ACCOUNT}:role/{WRITE_ROLE}',
                RoleSessionName=self.session_name,WebIdentityToken=token,DurationSeconds=3600)
            self.check()
            need(response['AssumedRoleUser']['Arn']==f'arn:aws:sts::{ACCOUNT}:assumed-role/{WRITE_ROLE}/{self.session_name}',
                 'CATALOG_RENEWED_ROLE_CHANGED')
            creds=response['Credentials'];expiry=creds['Expiration']
            need(isinstance(expiry,datetime) and expiry.tzinfo is not None and
                 600<expiry.timestamp()-self.clock()<=3660,'CATALOG_RENEWED_EXPIRY')
            need(all(type(creds[k]) is str and bool(creds[k]) for k in ('AccessKeyId','SecretAccessKey','SessionToken')),
                 'CATALOG_RENEWED_FIELDS')
            self.renewals+=1
            return {'access_key':creds['AccessKeyId'],'secret_key':creds['SecretAccessKey'],
                    'token':creds['SessionToken'],'expiry_time':expiry.isoformat()}
        except Exception:
            self.failed=True
            # No JWT, credentials, response, endpoint or underlying exception in logs.
            raise ValueError('CATALOG_CREDENTIAL_REFRESH_FAILED') from None


def session(env,*,seconds):
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    from botocore.credentials import RefreshableCredentials
    from botocore.session import Session
    core=Session()
    core.set_config_variable('credentials_file',os.devnull)
    core.set_config_variable('config_file',os.devnull)
    sts=core.create_client('sts',region_name=REGION,endpoint_url=f'https://sts.{REGION}.amazonaws.com',
        config=Config(signature_version=UNSIGNED,connect_timeout=5,read_timeout=15,retries={'total_max_attempts':1}))
    renewal=Renewal(env,sts,seconds=seconds)
    credentials=RefreshableCredentials.create_from_metadata(metadata=renewal.refresh(),refresh_using=renewal.refresh,
        method='assume-role-with-web-identity',advisory_timeout=900,mandatory_timeout=900)
    # Pinned botocore 1.43.119 shares this lock-protected provider across clients.
    # Equal windows make every refresh failure mandatory, with no stale fallback.
    core._credentials=credentials
    core.get_component('event_emitter').register('before-sign.*.*',renewal.before_sign)
    return boto3.Session(botocore_session=core,region_name=REGION),renewal
