import copy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock,MagicMock


@unittest.skipUnless(os.name=='posix','Linux host service boundary')
class HostTests(unittest.TestCase):
    def setUp(self):
        import catalog_host
        self.module=catalog_host

    def work(self,root,status):
        module=self.module
        work=module.Work.__new__(module.Work)
        work.stage=Path(root);work.state_path=work.stage/'state.json';work.state_path.touch()
        work.binding={'previous_commit':'b'*40};work.require_lease=True
        prior={'protected':{'sha':'fixture'},'manifest':{'commit':'b'*40}}
        work.state={'status':status,'previous':prior,'old_identity':'old-process',
                    'chatbot':{'runtime':'same'},'candidate_release':{'manifest':{'commit':'c'*40}},
                    'schema':{'old':True}}
        work.load=Mock();work.guard=Mock();work.resources=Mock(side_effect=AssertionError('Source/S3 must not be needed'))
        work.host=Mock();work.host.protected.return_value=prior['protected']
        work.record=lambda state:work.state.update(status=state) if isinstance(state,str) else None
        return work

    def test_pre_ddl_service_recovery_without_source_or_monitor(self):
        for status in ('FREEZE_INTENT','SERVICES_FROZEN','FROZEN_WITH_BASELINE','SNAPSHOT_VERIFIED'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as root:
                work=self.work(root,status)
                with patch.object(self.module,'systemctl') as ctl,patch.object(self.module,'start_and_enroll') as start:
                    result=work.recover(False)
                self.assertEqual(result['status'],'VERIFIED');self.assertFalse(work.require_lease)
                work.resources.assert_not_called();work.host.database.assert_called_once_with(work.state['previous']['manifest'])
                self.assertEqual(start.call_args.args[1],work.state['previous'])
                self.assertEqual(work.state['status'],'RECOVERED')

    def test_changed_db_cannot_be_written_without_monitor(self):
        with tempfile.TemporaryDirectory() as root:
            work=self.work(root,'V21_VERIFIED');work.verify_schema=Mock();work.connect=MagicMock()
            with patch.object(self.module,'systemctl'),patch('initial_flyway.owned_ids',return_value=set()),\
                 patch('initial_flyway.settle'),patch('pwd.getpwnam',return_value=SimpleNamespace(pw_uid=1000)),\
                 patch.object(self.module,'read_from_connection',return_value={'new':True}),\
                 patch.object(self.module,'start_and_enroll') as start:
                with self.assertRaisesRegex(ValueError,'WRITES_REQUIRE_MONITOR'):work.recover(False)
            work.resources.assert_not_called();start.assert_not_called()

    def test_success_and_consumed_recovery_are_never_replayed(self):
        for status in ('SUCCEEDED','RECOVERY_INTENT','RECOVERED'):
            with tempfile.TemporaryDirectory() as root:
                work=self.work(root,status)
                with patch.object(self.module,'systemctl') as ctl,self.assertRaisesRegex(ValueError,'NO_REPLAY'):
                    work.recover(True)
                ctl.assert_not_called()


if __name__=='__main__':unittest.main()
