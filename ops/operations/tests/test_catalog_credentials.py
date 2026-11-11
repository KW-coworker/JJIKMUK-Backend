import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import io
import json
import threading
import time
import unittest
from unittest.mock import Mock,patch
from catalog_credentials import Renewal
from connection import ACCOUNT,REPO,REPO_ID,WRITE_ROLE


class CredentialTests(unittest.TestCase):
    def fixture(self):
        now=[1794369000.0]
        env={'GITHUB_ACTIONS':'true','GITHUB_RUN_ATTEMPT':'1','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'123',
             'GITHUB_WORKFLOW_REF':REPO+'/.github/workflows/server-maintenance.yml@refs/heads/main',
             'OPERATIONS_CONFIRM':'true','MAINTENANCE_MODE':'catalog-reapply',
             'ACTIONS_ID_TOKEN_REQUEST_URL':'https://vstoken.actions.githubusercontent.com/test?run=123',
             'ACTIONS_ID_TOKEN_REQUEST_TOKEN':'synthetic-request-token'}
        claims={'iss':'https://token.actions.githubusercontent.com','aud':'sts.amazonaws.com',
                'sub':'repo:'+REPO+':environment:production','repository_id':REPO_ID,'ref':'refs/heads/main',
                'sha':env['GITHUB_SHA'],'run_id':'123','run_attempt':'1','workflow_ref':env['GITHUB_WORKFLOW_REF'],
                'exp':int(now[0]+300)}
        def body():
            payload=base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
            return io.BytesIO(json.dumps({'value':'synthetic.'+payload+'.synthetic'}).encode())
        opener=Mock();opener.open.side_effect=lambda *a,**k:body()
        sts=Mock();sts.assume_role_with_web_identity.side_effect=lambda **kw:{
            'AssumedRoleUser':{'Arn':f'arn:aws:sts::{ACCOUNT}:assumed-role/{WRITE_ROLE}/catalog-123'},
            'Credentials':{'AccessKeyId':'synthetic-access','SecretAccessKey':'synthetic-secret',
                           'SessionToken':'synthetic-session','Expiration':datetime.fromtimestamp(now[0]+3600,timezone.utc)}}
        renewal=Renewal(env,sts,seconds=7500,clock=lambda:now[0],monotonic=lambda:now[0],opener=opener)
        return renewal,now,env,claims,sts,opener

    def test_multiple_fresh_tokens_same_role_without_extending_budget(self):
        renewal,now,env,claims,sts,opener=self.fixture();end=renewal.until
        renewal.refresh();now[0]+=1800;claims['exp']=int(now[0]+300);renewal.refresh()
        self.assertEqual(renewal.renewals,2);self.assertEqual(renewal.until,end)
        self.assertEqual(opener.open.call_count,2)
        for call in sts.assume_role_with_web_identity.call_args_list:
            self.assertEqual(call.kwargs['RoleArn'],f'arn:aws:iam::{ACCOUNT}:role/{WRITE_ROLE}')
            self.assertEqual(call.kwargs['DurationSeconds'],3600)
        now[0]=end
        with self.assertRaisesRegex(ValueError,'CATALOG_CREDENTIAL_REFRESH_FAILED'):renewal.refresh()
        self.assertEqual(sts.assume_role_with_web_identity.call_count,2)

    def test_wrong_claim_or_endpoint_never_reaches_sts(self):
        for key,value in [('sub','repo:other/repo:environment:production'),('sha','b'*40),('exp',0),('workflow_ref','other')]:
            renewal,now,env,claims,sts,opener=self.fixture();claims[key]=value
            with self.assertRaisesRegex(ValueError,'CATALOG_CREDENTIAL_REFRESH_FAILED'):renewal.refresh()
            sts.assume_role_with_web_identity.assert_not_called()
        for url in ('https://evil.example/token','http://vstoken.actions.githubusercontent.com/','https://vstoken.actions.githubusercontent.com/?audience=other'):
            renewal,now,env,claims,sts,opener=self.fixture();renewal.env['ACTIONS_ID_TOKEN_REQUEST_URL']=url
            with self.assertRaisesRegex(ValueError,'CATALOG_CREDENTIAL_REFRESH_FAILED'):renewal.refresh()
            opener.open.assert_not_called();sts.assume_role_with_web_identity.assert_not_called()

    def test_transport_or_sts_rejection_latches_failure_without_secret_output(self):
        for target in ('token','sts'):
            renewal,now,env,claims,sts,opener=self.fixture()
            if target=='token':opener.open.side_effect=OSError('synthetic-SECRET')
            else:sts.assume_role_with_web_identity.side_effect=ValueError('synthetic-SECRET')
            for _ in range(2):
                with self.assertRaises(ValueError) as result:renewal.refresh()
                self.assertEqual(str(result.exception),'CATALOG_CREDENTIAL_REFRESH_FAILED')
                self.assertTrue(result.exception.__suppress_context__)
            self.assertEqual(opener.open.call_count,1)
            self.assertEqual(sts.assume_role_with_web_identity.call_count,int(target=='sts'))

    def test_deadline_during_request_cannot_yield_credentials(self):
        renewal,now,env,claims,sts,opener=self.fixture()
        original=sts.assume_role_with_web_identity.side_effect
        def late(**kw):
            result=original(**kw);now[0]=renewal.until;return result
        sts.assume_role_with_web_identity.side_effect=late
        with self.assertRaisesRegex(ValueError,'CATALOG_CREDENTIAL_REFRESH_FAILED'):renewal.refresh()
        self.assertEqual(renewal.renewals,0)

    def test_pinned_sdk_serializes_concurrent_renewals_and_never_falls_back(self):
        from botocore.credentials import RefreshableCredentials
        now=[1794369000.0];calls=[];lock=threading.Lock()
        def metadata(seconds,key='synthetic-old'):
            return {'access_key':key,'secret_key':'synthetic-secret','token':'synthetic-token',
                    'expiry_time':datetime.fromtimestamp(now[0]+seconds,timezone.utc).isoformat()}
        def refresh():
            with lock:calls.append(1)
            time.sleep(0.02)
            return metadata(3600,'synthetic-new-'+str(len(calls)))
        creds=RefreshableCredentials.create_from_metadata(metadata=metadata(600),refresh_using=refresh,
            method='assume-role-with-web-identity',advisory_timeout=900,mandatory_timeout=900)
        creds._time_fetcher=lambda:datetime.fromtimestamp(now[0],timezone.utc)
        with ThreadPoolExecutor(max_workers=4) as pool:
            keys=list(pool.map(lambda _:creds.get_frozen_credentials().access_key,range(4)))
        self.assertEqual(keys,['synthetic-new-1']*4);self.assertEqual(len(calls),1)
        now[0]+=2900;self.assertEqual(creds.get_frozen_credentials().access_key,'synthetic-new-2')
        now[0]+=2900
        creds._refresh_using=Mock(side_effect=ValueError('CATALOG_CREDENTIAL_REFRESH_FAILED'))
        with self.assertLogs('botocore.credentials',level='WARNING'):
            with self.assertRaisesRegex(ValueError,'CATALOG_CREDENTIAL_REFRESH_FAILED'):creds.get_frozen_credentials()

    def test_cached_credentials_cannot_sign_after_budget_or_latched_failure(self):
        from catalog_credentials import session
        from botocore.config import Config
        for stop in ('wall','monotonic','failure'):
            renewal,now,env,claims,sts,opener=self.fixture()
            with patch('catalog_credentials.Renewal',return_value=renewal):
                aws,actual=session(env,seconds=7500)
            self.assertIs(actual,renewal)
            aws._session._credentials._time_fetcher=lambda:datetime.fromtimestamp(now[0],timezone.utc)
            client=aws.client('s3',region_name='ap-northeast-2',endpoint_url='https://s3.ap-northeast-2.amazonaws.com',
                config=Config(signature_version='s3v4',retries={'total_max_attempts':1}))
            if stop=='wall':renewal.clock=lambda:renewal.until
            elif stop=='monotonic':renewal.monotonic=lambda:renewal.monotonic_until
            else:renewal.failed=True
            client._endpoint.http_session.send=Mock(side_effect=AssertionError('HTTP MUST NOT BE SENT'))
            with self.assertRaisesRegex(ValueError,'CATALOG_RENEWAL_STOPPED_OR_EXPIRED'):
                client.get_object(Bucket='synthetic-test-bucket',Key='read-only')
            client._endpoint.http_session.send.assert_not_called()


if __name__=='__main__':unittest.main()
