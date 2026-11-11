import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'cd'))
import initial_source_host as source
from host import atomic_json


class InitialSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.drop = self.root / 'owned.conf'
        self.before = {'identity': 'original', 'references': {}, 'environment_sha256': 'a'*64,
                       'security': {'User': 'food-chatbot'}}
        self.original = self.root / 'original.conf'; self.original.write_text('PRESERVED')
        self.drop_patch = patch.object(source, 'DROP', self.drop); self.drop_patch.start(); self.addCleanup(self.drop_patch.stop)
        self.backend = Mock()

    def switch(self):
        return source.switch_source(self.root, self.before, self.backend, 'unchanged-backend', {}, {})

    def test_success_writes_only_source_directory_override(self):
        with patch.object(source, 'run') as run, patch.object(source, 'stable', return_value={'healthy': True}) as stable, patch.object(source, 'verify_source'), patch.object(source, 'old_source_hash', return_value='c88c2314467b31b3147bf9ea419bf765d7b516aad6fb4a0ded22a78ce01e82b6'):
            result = self.switch()
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertEqual(self.drop.read_text(), '[Service]\nWorkingDirectory=' + str(source.RELEASE / 'AI') + '\n')
        self.assertTrue((self.root / 'switch-intent.json').is_file())
        self.assertEqual(self.original.read_text(), 'PRESERVED')
        self.assertEqual(stable.call_args.args[3], 'unchanged-backend')
        self.assertEqual(run.call_args_list[1].args[0], ['/usr/bin/systemctl', 'restart', source.SERVICE])

    def test_ambiguous_restart_rolls_back_only_owned_dropin_and_verifies_old(self):
        with patch.object(source, 'run', side_effect=[None, TimeoutError(), None, None]), patch.object(source, 'unit', return_value='ambiguous-process'), patch.object(source, 'stable', return_value={'healthy': True}) as stable:
            result = self.switch()
        self.assertEqual(result['status'], 'ROLLED_BACK')
        self.assertFalse(self.drop.exists())
        self.assertEqual(self.original.read_text(), 'PRESERVED')
        self.assertEqual(stable.call_args.args[0]['identity'], 'ambiguous-process')
        self.assertEqual(stable.call_args.args[1], source.OLD)

    def test_failed_new_health_rolls_back_and_does_not_claim_success(self):
        with patch.object(source, 'run'), patch.object(source, 'unit', return_value='new-process'), patch.object(source, 'stable', side_effect=[ValueError('health'), {'healthy': True}]):
            self.assertEqual(self.switch()['status'], 'ROLLED_BACK')
        self.assertFalse(self.drop.exists())

    def test_foreign_dropin_change_is_not_deleted_during_rollback(self):
        def run(*args):
            if args[0][1] == 'restart':
                self.drop.write_text('FOREIGN'); raise TimeoutError()
        with patch.object(source, 'run', side_effect=run), patch.object(source, 'stable') as stable:
            with self.assertRaisesRegex(ValueError, 'ROLLBACK_DROP_DRIFT'):
                self.switch()
            stable.assert_not_called()
        self.assertEqual(self.drop.read_text(), 'FOREIGN')

    def test_incomplete_or_false_candidate_checks_never_qualify(self):
        keys = ('dependencies_match', 'existing_rag_current', 'candidate_ready', 'deployment_boundary_valid',
                'product_repository_available', 'activity_repository_available', 'conversation_repository_available')
        report = {'status': 'OK', 'checks': dict.fromkeys(keys, True)}
        self.assertTrue(source.candidate_accepted(report, 0))
        for key in keys:
            altered = json.loads(json.dumps(report)); altered['checks'][key] = False
            self.assertFalse(source.candidate_accepted(altered, 0))
            altered['checks'].pop(key)
            self.assertFalse(source.candidate_accepted(altered, 0))
        self.assertFalse(source.candidate_accepted(report, 1))

    def test_runtime_drift_is_rejected_with_same_executable(self):
        after = dict(self.before, cwd=str(source.RELEASE / 'AI'))
        source.same_runtime(self.before, after, source.RELEASE / 'AI')
        for key, value in [('security', {'User': 'root'}), ('environment_sha256', 'b'*64), ('references', {'foreign': 'a'*64})]:
            with self.assertRaisesRegex(ValueError, 'RUNTIME_DRIFT'):
                source.same_runtime(self.before, dict(after, **{key: value}), source.RELEASE / 'AI')
