from pathlib import Path
import tempfile,unittest
from unittest.mock import Mock
from initial_service_state import stopped


class StoppedStateTests(unittest.TestCase):
    def state(self,**overrides):
        values=dict(ActiveState='inactive',SubState='dead',MainPID='0',ControlPID='0',ControlGroup='',Job='')
        values.update(overrides)
        return '\n'.join(k+'='+v for k,v in values.items())

    def test_failed_exit_with_no_process_or_job_is_stopped(self):
        for state in (self.state(),self.state(ActiveState='failed',SubState='failed')):
            stopped(('fixed.service',),Mock(return_value=state))

    def test_process_control_job_or_active_transition_is_rejected(self):
        for changed in ({'MainPID':'20'},{'ControlPID':'21'},{'Job':'17 /job/17'},
                        {'ActiveState':'activating','SubState':'auto-restart'},
                        {'ActiveState':'deactivating','SubState':'stop-sigterm'}):
            with self.subTest(changed=changed),self.assertRaisesRegex(ValueError,'NOT_STOPPED'):
                stopped(('fixed.service',),Mock(return_value=self.state(**changed)))

    def test_empty_main_pid_does_not_hide_descendant_and_racing_start(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);group=root/'system.slice/fixed.service/descendant';group.mkdir(parents=True)
            (group/'cgroup.procs').write_text('22\n')
            with self.assertRaisesRegex(ValueError,'CGROUP_NOT_EMPTY'):
                stopped(('fixed.service',),Mock(return_value=self.state(ControlGroup='/system.slice/fixed.service')),cgroup_root=root)
        with self.assertRaisesRegex(ValueError,'STATE_CHANGED'):
            stopped(('fixed.service',),Mock(side_effect=[self.state(),self.state(MainPID='20')]))


if __name__=='__main__':unittest.main()
