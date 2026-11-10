import unittest
from unittest.mock import MagicMock,patch
from initial_activation_runner import run_phases
import initial_activation_runner as runner
from initial_activation_document import document


class ActivationRunnerTests(unittest.TestCase):
    def test_main_movement_blocks_new_work_but_not_fixed_recovery(self):
        ctx={'commit':'a'*40};events=[]
        def phase(name):
            runner.check_phase_context(ctx,name);events.append(name)
            if name=='activate':return {'success':False,'report':{'status':'STOPPED'}}
            return {'success':True,'report':{'status':'ROLLED_BACK'}}
        with patch.object(runner,'validate_context',side_effect=[ctx,ctx,ValueError('MAIN_CHANGED')]) as current:
            with self.assertRaisesRegex(ValueError,'BACKEND_ROLLED_BACK'):run_phases(phase)
            self.assertEqual(current.call_count,2)
            with self.assertRaisesRegex(ValueError,'MAIN_CHANGED'):runner.check_phase_context(ctx,'activate')
        self.assertEqual(events,['install','activate','recover'])

    def test_install_failure_never_starts_or_recovers_application(self):
        phase=MagicMock(return_value={'success':False})
        with self.assertRaisesRegex(ValueError,'DISABLED_INSTALL_FAILED'):run_phases(phase)
        self.assertEqual([c.args[0] for c in phase.call_args_list],['install'])

    def test_success_requires_both_install_and_activation_results(self):
        phase=MagicMock(return_value={'success':True})
        self.assertTrue(run_phases(phase)['success'])
        self.assertEqual([c.args[0] for c in phase.call_args_list],['install','activate'])

    def test_completed_rollback_is_never_repeated_or_claimed_success(self):
        phase=MagicMock(side_effect=[{'success':True},{'success':False,'report':{'status':'ROLLED_BACK'}}])
        with self.assertRaisesRegex(ValueError,'BACKEND_ROLLED_BACK'):run_phases(phase)
        self.assertEqual(phase.call_count,2)

    def test_interrupted_switch_uses_one_fixed_recovery_and_requires_proof(self):
        for result in ('ROLLED_BACK','STOPPED'):
            phase=MagicMock(side_effect=[{'success':True},{'success':False,'report':{'status':'STOPPED'}},
                {'success':False,'report':{'status':result}}])
            expected='BACKEND_ROLLED_BACK' if result=='ROLLED_BACK' else 'RECOVERY_REQUIRES_REVIEW'
            with self.subTest(result=result),self.assertRaisesRegex(ValueError,expected):run_phases(phase)
            self.assertEqual([c.args[0] for c in phase.call_args_list],['install','activate','recover'])

    def test_fixed_document_verifies_payload_and_bounds_whole_process_group(self):
        meta={'commit':'a'*40,'archive_sha256':'b'*64,'manifest_sha256':'c'*64,'jar_sha256':'d'*64}
        for phase in ('activate','recover'):
            doc=document(meta,phase)
            self.assertEqual(doc['parameters'],{})
            code=doc['mainSteps'][0]['inputs']['runCommand'][0]
            for value in meta.values():self.assertIn(value,code)
            self.assertIn('KillMode=control-group',code);self.assertIn('RuntimeMaxSec=',code)
            self.assertIn("item['sha256']",code);self.assertNotIn('pip install',code)
            compile(code.split("<<'INITIAL_ACTIVATION_FIXED'\n")[1].rsplit('\nINITIAL_ACTIVATION_FIXED',1)[0],'<fixed>','exec')
        with self.assertRaises(ValueError):document({**meta,'commit':'shell;injection'},'activate')


if __name__=='__main__':unittest.main()
