from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from auto_context import ACCOUNT, DOCUMENT, INSTANCE
from manifest import make_manifest
from release import dispatch
from test_host import fixture_jar

class ServiceError(Exception):
    def __init__(self,code):
        self.response={'Error':{'Code':code}}

class FakeS3:
    def __init__(self):
        self.objects={}
        self.writes=[]
    def list_objects_v2(self,**args):
        return {'Contents':[{'Key':key} for key in self.objects if key.startswith(args['Prefix'])][:args['MaxKeys']]}
    def get_object(self,**args):
        if args['Key'] not in self.objects:raise ServiceError('NoSuchKey')
        return {'Body':io.BytesIO(self.objects[args['Key']])}
    def put_object(self,**args):
        assert args['ExpectedBucketOwner']==ACCOUNT
        assert args['IfNoneMatch']=='*'
        key=args['Key']
        if key in self.objects:raise ServiceError('PreconditionFailed')
        body=args['Body']
        self.objects[key]=body.read() if hasattr(body,'read') else body
        self.writes.append(key)
        return {'VersionId':'v'+str(len(self.writes))}
    def get_bucket_versioning(self,**args):return {'Status':'Enabled'}

@contextmanager
def release_fixture():
    with tempfile.TemporaryDirectory() as tmp:
        old=os.getcwd();os.chdir(tmp)
        try:
            Path('release').mkdir();fixture_jar('release/backend.jar')
            m=make_manifest('release/backend.jar','a'*40,'12','1')
            Path('release/manifest.json').write_text(json.dumps(m))
            with patch('release.guard'),patch('release.identity',return_value=('a'*40,'12','1')),patch('sys.stdout',new_callable=io.StringIO),patch('release.time.sleep'):
                yield
        finally:os.chdir(old)

class ReleaseTests(unittest.TestCase):
    def setup_clients(self):
        self.s3=FakeS3();self.ssm=Mock();self.sts=Mock();self.rds=Mock()
        self.sts.get_caller_identity.return_value={'Account':ACCOUNT,'Arn':f'arn:aws:sts::{ACCOUNT}:assumed-role/JjikmukBackendAutoDeploy/test'}
        self.commands=[]
        def send(**args):
            self.commands.append({**args,'CommandId':'11111111-2222-4333-8444-555555555555'})
            return {'Command':self.commands[-1]}
        self.ssm.send_command.side_effect=send
        self.ssm.get_command_invocation.return_value={'Status':'Success','ResponseCode':0,'StandardOutputContent':'{"status":"SUCCEEDED"}'}
        self.ssm.list_commands.side_effect=lambda **_: {'Commands':self.commands}
        return {'s3':self.s3,'ssm':self.ssm,'sts':self.sts,'rds':self.rds}

    def test_success_uses_fixed_target_versions_and_rerun_only_collects(self):
        c=self.setup_clients()
        with release_fixture(),patch('release.clients',return_value=c),patch('release.select_snapshot',return_value={'arn':'backup'}):
            dispatch()
            self.assertEqual('SUCCEEDED',dispatch()['status'])
        self.ssm.send_command.assert_called_once()
        args=self.ssm.send_command.call_args.kwargs
        self.assertEqual([INSTANCE],args['InstanceIds'])
        self.assertEqual(DOCUMENT,args['DocumentName'])
        self.assertEqual(['v2'],args['Parameters']['JarVersion'])
        self.assertEqual(['v3'],args['Parameters']['ManifestVersion'])
        self.assertTrue(self.s3.writes[0].endswith('/intent.json'))

    def test_no_backup_prevents_all_s3_writes_and_ssm(self):
        c=self.setup_clients()
        with release_fixture(),patch('release.clients',return_value=c),patch('release.select_snapshot',side_effect=ValueError('NO_FRESH_ENCRYPTED_BACKUP')):
            with self.assertRaisesRegex(ValueError,'NO_FRESH'):dispatch()
        self.assertEqual([],self.s3.writes);self.ssm.send_command.assert_not_called()

    def test_changed_artifact_blocks_all_aws_calls(self):
        with release_fixture(),patch('release.clients') as cloud:
            with Path('release/backend.jar').open('ab') as f:f.write(b'changed')
            with self.assertRaisesRegex(ValueError,'DOWNLOADED_ARTIFACT_MISMATCH'):dispatch()
            cloud.assert_not_called()

    def test_wrong_role_blocks_all_writes(self):
        c=self.setup_clients();self.sts.get_caller_identity.return_value['Arn']='other'
        with release_fixture(),patch('release.clients',return_value=c):
            with self.assertRaisesRegex(ValueError,'WRONG_AWS_IDENTITY'):dispatch()
        self.assertEqual([],self.s3.writes)

    def test_failed_health_rollback_is_a_failed_deployment_never_resent(self):
        c=self.setup_clients()
        self.ssm.get_command_invocation.return_value={'Status':'Failed','ResponseCode':1,'StandardOutputContent':'{"status":"ROLLED_BACK"}'}
        with release_fixture(),patch('release.clients',return_value=c),patch('release.select_snapshot',return_value={'arn':'backup'}):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'DEPLOYMENT_NOT_SUCCESSFUL'):dispatch()
            self.assertEqual('ROLLED_BACK',json.loads(Path('deployment-results/result.json').read_text())['status'])
        self.ssm.send_command.assert_called_once()

    def test_lost_send_response_collects_without_duplicate(self):
        c=self.setup_clients();self.ssm.send_command.side_effect=TimeoutError('hidden')
        def lost(**args):
            self.commands.append({**args,'CommandId':'11111111-2222-4333-8444-555555555555'})
            raise TimeoutError('hidden')
        self.ssm.send_command.side_effect=lost
        with release_fixture(),patch('release.clients',return_value=c),patch('release.select_snapshot',return_value={'arn':'backup'}):
            self.assertEqual('SUCCEEDED',dispatch()['status'])
            dispatch()
        self.ssm.send_command.assert_called_once()

    def test_lost_send_unknown_outcome_blocks_rerun(self):
        c=self.setup_clients();self.ssm.send_command.side_effect=TimeoutError('hidden')
        with release_fixture(),patch('release.clients',return_value=c),patch('release.select_snapshot',return_value={'arn':'backup'}):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'SEND_OUTCOME_UNKNOWN'):dispatch()
        self.ssm.send_command.assert_called_once()

    def test_lost_intent_write_response_never_sends(self):
        c=self.setup_clients();original=self.s3.put_object
        def lost(**args):
            original(**args)
            raise TimeoutError('hidden')
        with release_fixture(),patch('release.clients',return_value=c),patch('release.select_snapshot',return_value={'arn':'backup'}),patch.object(self.s3,'put_object',side_effect=lost):
            with self.assertRaises(TimeoutError):dispatch()
            with self.assertRaisesRegex(ValueError,'SEND_OUTCOME_UNKNOWN'):dispatch()
        self.ssm.send_command.assert_not_called()

    def test_main_advanced_during_upload_blocks_send(self):
        c=self.setup_clients()
        with release_fixture(),patch('release.clients',return_value=c),patch('release.select_snapshot',return_value={'arn':'backup'}),patch('release.guard',side_effect=[None,ValueError('MAIN_MOVED')]):
            with self.assertRaisesRegex(ValueError,'MAIN_MOVED'):dispatch()
        self.ssm.send_command.assert_not_called()


    def test_cached_success_for_another_commit_is_rejected(self):
        c=self.setup_clients()
        with release_fixture(),patch('release.clients',return_value=c),patch('release.select_snapshot',return_value={'arn':'backup'}):
            dispatch()
            key='receipts/backend-cd/'+'a'*40+'/result.json'
            bad=json.loads(self.s3.objects[key]);bad['commit']='b'*40
            self.s3.objects[key]=json.dumps(bad).encode()
            with self.assertRaisesRegex(ValueError,'CACHED_RESULT_MISMATCH'):dispatch()
        self.ssm.send_command.assert_called_once()

    def test_command_receipt_for_another_run_is_rejected(self):
        c=self.setup_clients()
        with release_fixture(),patch('release.clients',return_value=c),patch('release.select_snapshot',return_value={'arn':'backup'}):
            dispatch()
            self.commands[0]['Parameters']['RunId']=['99']
            with self.assertRaisesRegex(ValueError,'COMMAND_PARAMETERS_MISMATCH'):dispatch()
        self.ssm.send_command.assert_called_once()
