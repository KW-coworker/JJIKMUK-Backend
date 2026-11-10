import copy
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import time
import unittest
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'operations'))
import initial_maintenance_host as host
import initial_flyway as flyway


class MaintenanceTests(unittest.TestCase):
    def test_existing_app_config_uses_observed_owner_and_content_not_root_policy(self):
        raw=b'spring.datasource.username=synthetic\nspring.datasource.password=synthetic\n'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'properties';path.write_bytes(raw)
            info=SimpleNamespace(st_mode=0o100600,st_uid=1000,st_gid=1000,st_size=len(raw),
                                 st_ino=1,st_mtime_ns=2,st_ctime_ns=3)
            with patch.object(host.probe,'open_regular',side_effect=lambda p:os.open(path,os.O_RDONLY)), \
                    patch.object(host.os,'fstat',return_value=info), \
                    patch.object(host,'OBSERVED_PROPERTIES',hashlib.sha256(raw).hexdigest()):
                self.assertEqual(host.observed_properties()['spring.datasource.username'],'synthetic')
                for key,value in (('st_uid',0),('st_gid',0),('st_mode',0o100644)):
                    saved=getattr(info,key);setattr(info,key,value)
                    with self.assertRaisesRegex(ValueError,'METADATA_CHANGED'):host.observed_properties()
                    setattr(info,key,saved)
                with patch.object(host,'OBSERVED_PROPERTIES','f'*64),self.assertRaisesRegex(ValueError,'PROPERTIES_CHANGED'):
                    host.observed_properties()

    def test_failed_backend_stop_still_attempts_chatbot_stop_and_marks_uncertain(self):
        state={'status':'DB_VERIFIED_SERVICES_STOPPED'}
        def command(*args):
            if args in (('start',host.UNITS[0]),('stop',host.UNITS[0])):raise ValueError('SYNTHETIC_FAILURE')
        def state_change(state,status):state['status']=status
        with patch.object(host,'require_inputs'),patch.object(host,'set_state',side_effect=state_change), \
                patch.object(host,'systemctl',side_effect=command) as commands, \
                patch.object(host,'stopped',side_effect=ValueError('STILL_RUNNING')):
            with self.assertRaisesRegex(ValueError,'SYNTHETIC'):host.restore_services(state)
        self.assertIn(('stop',host.UNITS[1]),[c.args for c in commands.call_args_list])
        self.assertEqual(state['status'],'RESTORE_FAILED_STOP_UNCONFIRMED')

    def test_second_service_start_failure_stops_both_and_journals_truth(self):
        state={'status':'DB_VERIFIED_SERVICES_STOPPED'}
        events=[]
        def systemctl(*args):
            if args==('start',host.UNITS[0]):raise ValueError('SYNTHETIC_START_FAILURE')
        def state_change(state,status):state['status']=status;events.append(status)
        with patch.object(host,'require_inputs'),patch.object(host,'set_state',side_effect=state_change), \
                patch.object(host,'systemctl',side_effect=systemctl) as command,patch.object(host,'stopped') as stopped:
            with self.assertRaisesRegex(ValueError,'SYNTHETIC'):host.restore_services(state)
        self.assertEqual(events,['RESTORE_INTENT','RESTORE_FAILED_SERVICES_STOPPED'])
        self.assertEqual(state['restore_origin'],'DB_VERIFIED_SERVICES_STOPPED')
        self.assertEqual([c.args for c in command.call_args_list[-2:]],[('stop',x) for x in host.UNITS])
        stopped.assert_called_once()

    def test_partial_ddl_recovery_cannot_restart_apps(self):
        for phase in ('FULLTEXT_DROPPED','PRODUCTS_REBUILT','ORIGINAL_V17_V20_APPLIED','RESTORE_INTENT'):
            with self.subTest(phase=phase),patch.object(host,'private_state',return_value={'status':phase}), \
                    patch.object(host,'verify_binding'),patch.object(host,'restore_services') as restore:
                with self.assertRaisesRegex(ValueError,'DDL_STATE'):host.recover(Path('/opt/fake'),{})
                restore.assert_not_called()

    def test_recovery_uses_verified_origin_after_restore_mutates_state(self):
        state={'status':'DB_VERIFIED_SERVICES_STOPPED'}
        def restore(s):s['status']='RESTORE_INTENT'
        with patch.object(host,'private_state',return_value=state),patch.object(host,'verify_binding'), \
                patch.object(host,'restore_services',side_effect=restore),patch.object(host,'set_state') as save:
            self.assertEqual(host.recover(Path('/opt/fake'),{})['status'],'SUCCEEDED')
            self.assertEqual(save.call_args.args[1],'DB_PREPARED')

    def test_flyway_never_cancels_unknown_owner(self):
        conn=MagicMock();cur=conn.__enter__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=((15,'jjikmuk',0),)
        with self.assertRaisesRegex(ValueError,'OWNERSHIP'):
            flyway.settle(lambda:conn,[15],MagicMock(),cancel=True)
        self.assertFalse(any(c.args[0].startswith('KILL') for c in cur.execute.call_args_list))

    def test_lost_cancel_is_not_repeated_and_end_is_confirmed(self):
        conn=MagicMock();cur=conn.__enter__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect=[((15,'jjikmuk',1),),((15,'jjikmuk',1),),()]
        def command(sql,*args):
            if sql.startswith('KILL'):raise OSError('synthetic lost response')
        cur.execute.side_effect=command
        with patch.object(flyway.time,'sleep'):
            flyway.settle(lambda:conn,[15],MagicMock(),cancel=True)
        self.assertEqual(sum(c.args[0].startswith('KILL') for c in cur.execute.call_args_list),1)

    @unittest.skipUnless(os.name=='posix','Linux process group semantics')
    def test_parent_exit_does_not_leave_term_ignoring_child(self):
        with tempfile.TemporaryDirectory() as folder:
            ready=Path(folder)/'ready';late=Path(folder)/'late'
            code="import signal,time,pathlib;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path("+repr(str(ready))+").touch();time.sleep(4);pathlib.Path("+repr(str(late))+").touch()"
            parent="import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',"+repr(code)+"]);time.sleep(20)"
            with subprocess.Popen([sys.executable,'-c',parent],start_new_session=True) as child:
                deadline=time.monotonic()+5
                while not ready.exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue(ready.exists())
                flyway.stop_child(child)
                time.sleep(4.2)
                self.assertFalse(late.exists())


if __name__=='__main__':unittest.main()
