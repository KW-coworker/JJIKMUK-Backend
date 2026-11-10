import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock,patch
import initial_maintenance_host as host
import initial_flyway as flyway


class MaintenanceTests(unittest.TestCase):
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
