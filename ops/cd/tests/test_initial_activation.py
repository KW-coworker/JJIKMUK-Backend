import copy,json,sys,tempfile,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'operations'))
import initial_activation as activation


class TransitionTests(unittest.TestCase):
    def test_repeated_process_restarts_cannot_count_as_continuous_recovery(self):
        obj=activation.Actions.__new__(activation.Actions);clock=[0];count=[0]
        def observe():
            clock[0]+=30;count[0]+=1
            return 'process-'+str(count[0])
        obj.old_runtime=observe
        with patch.object(activation.time,'monotonic',side_effect=lambda:clock[0]),patch.object(activation.time,'sleep'):
            with self.assertRaisesRegex(ValueError,'HEALTH_FAILED'):obj.verify_old_recovery('previous')
        self.assertEqual(count[0],8)

    def test_late_health_result_does_not_extend_the_deadline(self):
        obj=activation.Actions.__new__(activation.Actions);obj.old_runtime=MagicMock(return_value='new')
        with patch.object(activation.time,'monotonic',side_effect=[0,1,2,250,251]),patch.object(activation.time,'sleep'):
            with self.assertRaisesRegex(ValueError,'HEALTH_FAILED'):obj.verify_old_recovery('old')

    def test_original_input_drift_prevents_restart_during_rollback(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            root=Path(folder);obj=activation.Actions.__new__(activation.Actions)
            obj.guard=MagicMock();obj.host=MagicMock();obj.record=MagicMock();obj.prepared={}
            obj.config={'enabled':True,'service':'fixture'};obj.disabled={**obj.config,'enabled':False}
            obj.state={'db_preparation_sha256':'a'*64};obj.dropin=b'fixed'
            drop=root/'cd.conf';drop.write_bytes(obj.dropin)
            for name,value in [('ROOT',root),('FAILED',root/'preserved'),('DROPIN',str(drop)),('SETTINGS',root/'config.json')]:
                stack.enter_context(patch.object(activation,name,value))
            stack.enter_context(patch.object(activation,'digest',return_value='a'*64))
            stack.enter_context(patch.object(activation,'secure'))
            stack.enter_context(patch.object(activation,'read_host_state',return_value=obj.config))
            stack.enter_context(patch.object(activation.maintenance,'require_inputs',side_effect=ValueError('INPUT_DRIFT')))
            commands=stack.enter_context(patch.object(activation,'command'))
            with self.assertRaisesRegex(ValueError,'INPUT_DRIFT'):obj.rollback()
            obj.host.restart.assert_not_called();obj.host.database.assert_not_called()
            commands.assert_called_once_with(['systemctl','stop','fixture'],90)
            obj.record.assert_called_once_with('MANUAL_RECOVERY_REQUIRED')

    def test_preflight_rejection_does_not_change_service_or_attempt_rollback(self):
        actions=MagicMock();actions.preflight.side_effect=ValueError('OLD_INPUT_CHANGED')
        with self.assertRaisesRegex(ValueError,'OLD_INPUT'):activation.execute_transition(actions)
        actions.intent.assert_not_called();actions.switch.assert_not_called();actions.rollback.assert_not_called()

    def test_each_failure_after_intent_runs_restore_instead_of_success(self):
        for name in ('configure','switch','verify','enroll','complete'):
            with self.subTest(phase=name):
                actions=MagicMock();getattr(actions,name).side_effect=ValueError('FIXTURE')
                self.assertEqual(activation.execute_transition(actions),'ROLLED_BACK')
                actions.rollback.assert_called_once()

    def test_failed_restore_never_claims_rolled_back(self):
        actions=MagicMock();actions.switch.side_effect=ValueError('START_FAILED')
        actions.rollback.side_effect=ValueError('RESTORE_FAILED')
        with self.assertRaisesRegex(ValueError,'RESTORE_FAILED'):activation.execute_transition(actions)

    def test_success_runs_all_probes_before_enrolling(self):
        actions=MagicMock()
        self.assertEqual(activation.execute_transition(actions),'SUCCEEDED')
        self.assertEqual([x[0] for x in actions.mock_calls],
            ['preflight','intent','configure','switch','verify','enroll','complete'])

    def test_actual_file_restore_preserves_dropin_and_baseline_without_sql(self):
        for failure in ('verify','enroll','complete'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
                root=Path(folder);settings=root/'config.json';state=root/'state.json';drop=root/'cd.conf'
                failed=root/'preserved';db=root/'db';db.mkdir();(db/'state.json').write_text('{}')
                for name,value in [('ROOT',root),('SETTINGS',settings),('STATE',state),('DROPIN',str(drop)),('FAILED',failed)]:
                    stack.enter_context(patch.object(activation,name,value))
                stack.enter_context(patch.object(activation.maintenance,'JOURNAL_ROOT',db))
                stack.enter_context(patch.object(activation,'secure'))
                stack.enter_context(patch('host.secure'))
                stack.enter_context(patch.object(activation.maintenance,'require_inputs'))
                commands=stack.enter_context(patch.object(activation,'command'))
                stack.enter_context(patch.object(activation.time,'sleep'))
                stack.enter_context(patch.object(activation.time,'monotonic',side_effect=[0,1,2,62]))
                obj=activation.Actions.__new__(activation.Actions)
                obj.guard=MagicMock();obj.host=MagicMock();obj.host.protected.return_value={}
                obj.folder=root/'release';obj.folder.mkdir()
                obj.disabled={'enabled':False,'service':'fixture'};obj.config={**obj.disabled,'enabled':True}
                obj.manifest={'commit':'a'*40};obj.dropin=b'[Service]\nExecStart=fixture\n'
                obj.prepared={'environment_sha256':'b'*64};obj.old_identity='old'
                obj.state={'db_preparation_sha256':activation.digest(db/'state.json')}
                obj.preflight=MagicMock();obj.old_runtime=MagicMock()
                def recovered():
                    self.assertFalse(drop.exists())
                    self.assertEqual(json.loads(settings.read_bytes()),obj.disabled)
                    return 'restored'
                obj.old_runtime.side_effect=recovered
                obj.host.commit.side_effect=lambda value:activation.atomic_json(root/'baseline.json',value)
                obj.verify=MagicMock()
                original=getattr(obj,failure)
                def injected():
                    if failure=='complete':obj.record('SUCCEEDED')
                    elif failure=='enroll':original()
                    raise ValueError('FIXTURE_FAILURE')
                setattr(obj,failure,injected)
                self.assertEqual(activation.execute_transition(obj),'ROLLED_BACK')
                self.assertEqual((failed/'dropin.conf').read_bytes(),obj.dropin)
                if failure!='verify':self.assertEqual(json.loads((failed/'baseline.json').read_bytes())['manifest'],obj.manifest)
                self.assertEqual(json.loads(state.read_bytes())['status'],'ROLLED_BACK')
                self.assertEqual(obj.host.restart.call_count,2)
                self.assertNotIn(['systemctl','stop','fixture'],[x.args[0] for x in commands.call_args_list])


if __name__=='__main__':unittest.main()
