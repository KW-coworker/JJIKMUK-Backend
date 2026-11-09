from contextlib import contextmanager
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from manifest import make_manifest
from release import dispatch
from test_host import fixture_jar


@contextmanager
def release_fixture():
    with tempfile.TemporaryDirectory() as tmp:
        old=os.getcwd(); os.chdir(tmp)
        try:
            Path('release').mkdir(); fixture_jar('release/backend.jar')
            m=make_manifest('release/backend.jar','a'*40,'12','1')
            Path('release/manifest.json').write_text(json.dumps(m))
            env={'AWS_ACCOUNT_ID':'111111111111','CD_BUCKET':'test-bucket','CD_PREFIX':'backend-releases',
                 'CD_INSTANCE_ID':'i-'+'a'*17,'CD_DOCUMENT':'ApprovedCD','CD_DOCUMENT_VERSION':'1',
                 'SNAPSHOT_ID':'snapshot','CD_DATABASE_ID':'database'}
            with patch.dict(os.environ,env,clear=True),patch('release.guard'),patch('release.identity',return_value=('a'*40,'12','1')):
                yield
        finally: os.chdir(old)


class ReleaseTests(unittest.TestCase):
    def run_dispatch(self, final_status='Success', snapshot_status='available'):
        calls=[]
        def fake(*args,**kwargs):
            calls.append(args)
            if args[:2]==('sts','get-caller-identity'): return {'Account':'111111111111'}
            if args[:2]==('rds','describe-db-snapshots'):
                return {'DBSnapshots':[{'Status':snapshot_status,'Encrypted':True,'DBInstanceIdentifier':'database',
                        'DBSnapshotArn':'arn:aws:rds:ap-northeast-2:111111111111:snapshot:snapshot',
                        'SnapshotCreateTime':datetime.now(timezone.utc).isoformat()}]}
            if args[:2]==('s3api','get-bucket-versioning'): return {'Status':'Enabled'}
            if args[:2]==('s3api','put-object'): return {'VersionId':'version'+str(len(calls))}
            if args[:2]==('ssm','send-command'): return {'Command':{'CommandId':'command'}}
            if args[:2]==('ssm','get-command-invocation'):
                return {'Status':final_status,'ResponseCode':0,'StandardOutputContent':'{"status":"SUCCEEDED"}'}
            raise AssertionError(args)
        with release_fixture(),patch('release.aws',side_effect=fake),patch('sys.stdout',new_callable=io.StringIO):
            if final_status=='Success' and snapshot_status=='available': dispatch()
            else:
                with self.assertRaises(ValueError): dispatch()
        return calls

    def test_only_one_command_sent_and_exact_versions_pinned(self):
        calls=self.run_dispatch()
        sends=[c for c in calls if c[:2]==('ssm','send-command')]
        self.assertEqual(1,len(sends))
        params=json.loads(sends[0][sends[0].index('--parameters')+1])
        self.assertEqual(['version4'],params['JarVersion'])
        self.assertEqual(['version5'],params['ManifestVersion'])
        self.assertEqual(['a'*40],params['ReleaseCommit'])

    def test_failed_ssm_is_not_redispatched(self):
        calls=self.run_dispatch(final_status='Failed')
        self.assertEqual(1,len([c for c in calls if c[:2]==('ssm','send-command')]))

    def test_unready_backup_blocks_all_writes(self):
        calls=self.run_dispatch(snapshot_status='creating')
        self.assertEqual([('sts','get-caller-identity'),('rds','describe-db-snapshots')],[c[:2] for c in calls])

    def test_changed_downloaded_jar_blocks_all_aws_calls(self):
        with release_fixture(), patch('release.aws') as aws:
            with Path('release/backend.jar').open('ab') as jar:
                jar.write(b'changed-after-build')
            with self.assertRaisesRegex(ValueError,'DOWNLOADED_ARTIFACT_MISMATCH'):
                dispatch()
            aws.assert_not_called()
