import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import chat_release as release
from package import sha


class S3:
    def __init__(self):self.objects={}
    def list_objects_v2(self,**kw):return {'Contents':[{'Key':k} for k in self.objects if k.startswith(kw['Prefix'])]}
    def get_object(self,**kw):return {'Body':io.BytesIO(self.objects[kw['Key']])}
    def get_bucket_versioning(self,**kw):return {'Status':'Enabled'}
    def put_object(self,**kw):
        if kw['Key'] in self.objects:raise RuntimeError('already exists')
        self.assertions(kw);body=kw['Body'];self.objects[kw['Key']]=body.read() if hasattr(body,'read') else body
        return {'VersionId':'v'+str(len(self.objects))}
    def assertions(self,kw):assert kw['IfNoneMatch']=='*' and kw['ExpectedBucketOwner']==release.ACCOUNT


class ChatReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=os.getcwd();os.chdir(self.tmp.name)
        Path('release').mkdir();Path('release/chatbot.zip').write_bytes(b'archive')
        m=dict(commit='a'*40,run_id='12',attempt='1',archive_bytes=7,archive_sha256=sha(b'archive'))
        Path('release/manifest.json').write_text(json.dumps(m))
        self.s3=S3();self.ssm=Mock();self.sts=Mock();self.api=dict(s3=self.s3,ssm=self.ssm,sts=self.sts,rds=Mock())
        self.sts.get_caller_identity.return_value={'Account':release.ACCOUNT,'Arn':f'arn:aws:sts::{release.ACCOUNT}:assumed-role/JjikmukChatbotAutoDeploy/test'}
        self.commands=[]
        def send(**kw):self.commands.append(dict(kw,CommandId='command'));return {}
        self.ssm.send_command.side_effect=send
        self.ssm.list_commands.side_effect=lambda **kw:{'Commands':self.commands}
        self.ssm.get_command_invocation.return_value={'Status':'Success','ResponseCode':0,'StandardOutputContent':'{"status":"SUCCEEDED"}'}
        self.patches=[patch.object(release,'guard',return_value=('a'*40,'12','1')),patch.object(release,'clients',return_value=self.api),
            patch.object(release,'select_snapshot',return_value={'arn':'fixed'}),patch.object(release.time,'sleep')]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        os.chdir(self.old);self.tmp.cleanup()
    def test_success_and_repeat_collect_without_another_command(self):
        self.assertEqual(release.dispatch()['status'],'SUCCEEDED')
        self.assertEqual(release.dispatch()['status'],'SUCCEEDED')
        self.assertEqual(len(self.commands),1)
        self.assertEqual(self.commands[0]['DocumentName'],'Jjikmuk-ChatbotDeploy-v1')
    def test_lost_send_is_collected_and_never_retried(self):
        original=self.ssm.send_command.side_effect
        def lost(**kw):original(**kw);raise TimeoutError()
        self.ssm.send_command.side_effect=lost
        self.assertEqual(release.dispatch()['status'],'SUCCEEDED');self.assertEqual(len(self.commands),1)
    def test_unknown_send_and_upload_claim_block_replay(self):
        self.ssm.send_command.side_effect=TimeoutError()
        with self.assertRaisesRegex(ValueError,'UNKNOWN'):release.dispatch()
        with self.assertRaisesRegex(ValueError,'UNKNOWN'):release.dispatch()
        self.assertEqual(self.ssm.send_command.call_count,1)
    def test_db_gate_failure_is_not_success(self):
        self.ssm.get_command_invocation.return_value={'Status':'Failed','ResponseCode':1,
            'StandardOutputContent':'{"status":"REJECTED","reason":"CHATBOT_SCHEMA_MISMATCH","secret":"not printable"}'}
        result=release.dispatch();self.assertEqual(result['reason'],'CHATBOT_SCHEMA_MISMATCH')
        self.assertNotIn('secret',result)
    def test_backup_failure_prevents_publication(self):
        release.select_snapshot.side_effect=ValueError('NO_FRESH_ENCRYPTED_BACKUP')
        with self.assertRaises(ValueError):release.dispatch()
        self.assertEqual(self.s3.objects,{});self.ssm.send_command.assert_not_called()
