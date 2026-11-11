import copy
import os
import sys
import subprocess
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock,MagicMock


@unittest.skipUnless(os.name=='posix','Linux host service boundary')
class HostTests(unittest.TestCase):
    def test_release_directory_is_traversable_under_private_maintenance_umask(self):
        import hashlib
        from catalog_host_support import prepare_release
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stage=root/'stage';stage.mkdir()
            jar=stage/'backend.jar';jar.write_bytes(b'synthetic jar')
            host=SimpleNamespace(baseline={'protected':{},'environment_sha256':'fixture'},release_path=lambda release:root/'release')
            old=os.umask(0o077)
            try:prepare_release(host,stage,{'jar_sha256':hashlib.sha256(jar.read_bytes()).hexdigest()})
            finally:os.umask(old)
            self.assertEqual((root/'release').stat().st_mode & 0o777,0o755)
            self.assertEqual((root/'release/backend.jar').stat().st_mode & 0o777,0o644)
            self.assertEqual((root/'release/manifest.json').stat().st_mode & 0o777,0o600)

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

    def test_preservation_loads_isolated_driver_before_import(self):
        work=self.module.Work.__new__(self.module.Work)
        driver=SimpleNamespace(cursors=SimpleNamespace(SSCursor=object()))
        connection=SimpleNamespace(open=True,close=Mock())
        def connect():
            sys.modules['pymysql']=driver
            return connection
        work.connect=connect;work.state={'schema':{},'bounds':{}};work.guard=Mock()
        with patch.dict(sys.modules,{'pymysql':None}),patch.object(self.module,'capture',return_value={'verified':True}) as capture:
            self.assertEqual(work.preservation(),{'verified':True})
            self.assertIs(capture.call_args.args[0],connection)
        self.assertIs(capture.call_args.args[-2],driver.cursors.SSCursor)
        self.assertEqual(capture.call_args.args[-1],work.progress)
        connection.close.assert_called_once()

    def test_streaming_failure_preserves_original_error_without_double_close(self):
        class Connection:
            open=True
            closed=0
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
            def close(self):
                self.closed+=1
                if not self.open:raise RuntimeError('Already closed')
                self.open=False
        conn=Connection();work=self.module.Work.__new__(self.module.Work)
        work.connect=lambda:conn;work.state={'schema':{},'bounds':{}};work.guard=Mock()
        def fail(*unused):
            conn.close()
            raise ValueError('CATALOG_PRESERVATION_ROW_BOUND')
        driver=SimpleNamespace(cursors=SimpleNamespace(SSCursor=object()))
        with patch.dict(sys.modules,pymysql=driver),patch.object(self.module,'capture',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'CATALOG_PRESERVATION_ROW_BOUND'):work.preservation()
        self.assertEqual(conn.closed,1)

    def test_preservation_is_first_db_entry_in_fresh_isolated_process(self):
        ops=Path(self.module.__file__).parent
        code=f'''
import sys
from types import SimpleNamespace
sys.path[:0]=[{str(ops)!r},{str(ops.parent/'cd')!r}]
import catalog_host
assert 'pymysql' not in sys.modules
def connect():
 sys.modules['pymysql']=SimpleNamespace(cursors=SimpleNamespace(SSCursor=object()))
 return SimpleNamespace(open=True,close=lambda:None)
work=catalog_host.Work.__new__(catalog_host.Work)
work.connect=connect;work.state={{'schema':{{}},'bounds':{{}}}};work.guard=lambda:None
catalog_host.capture=lambda *args:{{'verified':True}}
assert work.preservation()=={{'verified':True}}
print('ISOLATED_FIRST_DB_ENTRY_VERIFIED')
'''
        result=subprocess.run([sys.executable,'-I','-S','-B','-c',code],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'ISOLATED_FIRST_DB_ENTRY_VERIFIED')

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
