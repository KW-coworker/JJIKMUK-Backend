"""Fail-closed automatic event, main freshness and backup tests."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from auto_context import ACCOUNT, DATABASE, REPOSITORY, guard, select_snapshot

class AutoContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'event.json'
        self.payload = {'ref':'refs/heads/main','after':'a'*40,'deleted':False,'forced':False,'repository':{'id':1300060655}}
        self.path.write_text(json.dumps(self.payload))
        self.env = {'GITHUB_REPOSITORY':REPOSITORY, 'GITHUB_REPOSITORY_ID':'1300060655',
                    'GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'push',
                    'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'12','GITHUB_RUN_ATTEMPT':'1',
                    'GITHUB_WORKFLOW_REF':REPOSITORY+'/.github/workflows/backend-cd.yml@refs/heads/main',
                    'GITHUB_EVENT_PATH':str(self.path),'CD_ENABLED':'true'}
        self.addCleanup(self.tmp.cleanup)

    def test_main_push_needs_no_per_release_approval(self):
        with patch.dict(os.environ,self.env,clear=True), patch('auto_context.main_head',return_value='a'*40):
            guard()

    def test_disabled_and_wrong_context_fail_before_network(self):
        for key,value in [('GITHUB_REPOSITORY','other/repo'),('GITHUB_REPOSITORY_ID','1'),
                          ('GITHUB_REF','refs/pull/1/merge'),('GITHUB_EVENT_NAME','pull_request'),
                          ('GITHUB_WORKFLOW_REF','other.yml'),('CD_ENABLED','false')]:
            with self.subTest(key=key),patch.dict(os.environ,{**self.env,key:value},clear=True),patch('auto_context.main_head') as network:
                with self.assertRaises(ValueError):guard()
                network.assert_not_called()

    def test_force_push_delete_and_payload_identity_changes_are_blocked(self):
        for changes in ({'forced':True},{'deleted':True},{'after':'b'*40},{'ref':'refs/heads/feature'},{'repository':{'id':1}}):
            self.path.write_text(json.dumps({**self.payload,**changes}))
            with self.subTest(changes=changes),patch.dict(os.environ,self.env,clear=True),patch('auto_context.main_head') as network:
                with self.assertRaisesRegex(ValueError,'PUSH_EVENT_MISMATCH'):guard()
                network.assert_not_called()

    def test_manual_run_only_verifies_and_never_deploys(self):
        with patch.dict(os.environ,{**self.env,'GITHUB_EVENT_NAME':'workflow_dispatch','CD_ENABLED':'false'},clear=True),patch('auto_context.main_head',return_value='a'*40):
            guard(deployment=False)
            with self.assertRaisesRegex(ValueError,'AUTOMATIC_PUSH_OR_VERIFIED_RESUME_ONLY'):guard()

    def test_changed_main_blocks_deployment(self):
        with patch.dict(os.environ,self.env,clear=True),patch('auto_context.main_head',return_value='b'*40):
            with self.assertRaisesRegex(ValueError,'MAIN_MOVED'):guard()

    def test_resume_event_requires_exact_main_and_fresh_attempt(self):
        base = {**self.env, 'GITHUB_EVENT_NAME': 'workflow_dispatch', 'MAINTENANCE_ID': 'b'*32, 'EXPECTED_SHA': 'a'*40}
        with patch.dict(os.environ, base, clear=True), patch('auto_context.main_head', return_value='a'*40):
            guard()  # Dispatch still has to validate the durable VERIFIED gate before AWS SendCommand.
        for key, value in [('EXPECTED_SHA', 'c'*40), ('GITHUB_RUN_ATTEMPT', '2'), ('MAINTENANCE_ID', '../bad')]:
            with patch.dict(os.environ, {**base, key: value}, clear=True), patch('auto_context.main_head') as network:
                with self.assertRaises(ValueError): guard()
                network.assert_not_called()

    def snapshot(self, age=1, **changes):
        now=datetime(2026,11,9,tzinfo=timezone.utc)
        return {'Status':'available','Encrypted':True,'DBInstanceIdentifier':DATABASE,
                'DBSnapshotArn':f'arn:aws:rds:ap-northeast-2:{ACCOUNT}:snapshot:backup-{age}',
                'SnapshotCreateTime':now-timedelta(hours=age),'SnapshotType':'automated',**changes}

    def test_backup_automatically_selects_newest_valid_across_pages(self):
        rds=Mock()
        rds.describe_db_snapshots.side_effect=[
            {'DBSnapshots':[self.snapshot(25),self.snapshot(1,Encrypted=False),self.snapshot(2)],'Marker':'next'},
            {'DBSnapshots':[self.snapshot(1),self.snapshot(0,SnapshotType='shared')]}]
        actual=select_snapshot(rds,datetime(2026,11,9,tzinfo=timezone.utc))
        self.assertTrue(actual['arn'].endswith('backup-1'))
        self.assertEqual('next',rds.describe_db_snapshots.call_args.kwargs['Marker'])
        self.assertEqual(DATABASE,rds.describe_db_snapshots.call_args.kwargs['DBInstanceIdentifier'])

    def test_no_fresh_backup_rejects_without_creating_one(self):
        rds=Mock()
        rds.describe_db_snapshots.return_value={'DBSnapshots':[self.snapshot(25),self.snapshot(0,Encrypted=False)]}
        with self.assertRaisesRegex(ValueError,'NO_FRESH_ENCRYPTED_BACKUP'):
            select_snapshot(rds,datetime(2026,11,9,tzinfo=timezone.utc))
        rds.create_db_snapshot.assert_not_called()

