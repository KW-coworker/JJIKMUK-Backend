import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'cd/tests'))
from test_maintenance_gate import MemoryS3
import maintenance as m
from maintenance_gate import Gate
from maintenance_probe import drained, plan as probe
from connection import HOSTS, sha


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.old = Path.cwd(); os.chdir(self.tmp.name)
        Path('operation-results').mkdir()
        self.addCleanup(self.tmp.cleanup); self.addCleanup(lambda: os.chdir(self.old))
        self.s3 = MemoryS3(); self.api = {'s3': self.s3, 'ssm': Mock()}
        self.api['ssm'].list_commands.return_value = {'Commands': []}
        self.ctx = dict(commit='a'*40, run_id='100', attempt='1', request_id='b'*32)
        self.work = ({'component': 'db', 'operation': 'deploy', 'approval_id': 'APPROVED_TEST'}, HOSTS['backend'])
        self.verify = ({'component': 'db', 'operation': 'verify', 'approval_id': 'APPROVED_TEST'}, HOSTS['backend'])
        self.report = {'status': 'VERIFIED', 'checks': {'valid': True},
                       'hashes': {'backend_commit_sha256': sha(('a'*40).encode())}}
        self.environment = patch.dict(os.environ, {'CD_ENABLED': 'true'})
        self.environment.start(); self.addCleanup(self.environment.stop)

    def perform(self):
        return m.perform(self.api, self.ctx, self.work, self.verify, 'c'*64, 'd'*64, sleep=lambda _: None)

    def test_work_and_verification_run_between_fresh_host_checks(self):
        with patch.object(m, 'checked_execute', return_value=self.report) as operation:
            result = self.perform()
        self.assertEqual([x.args[-1] for x in operation.call_args_list],
                         ['maintenance-before-', 'maintenance-work-', 'maintenance-verify-', 'maintenance-after-'])
        self.assertEqual(result['status'], 'VERIFIED_AWAITING_LATEST_MAIN')
        self.assertEqual(Gate(self.s3).read()[0]['state'], 'VERIFIED')

    def test_every_step_failure_leaves_hold_and_does_not_run_later_steps(self):
        for at in range(4):
            with self.subTest(step=at):
                self.s3 = MemoryS3(); self.api['s3'] = self.s3
                with patch.object(m, 'checked_execute', side_effect=[self.report]*at + [ValueError('failure')]) as operation:
                    with self.assertRaises(ValueError): self.perform()
                self.assertEqual(operation.call_count, at+1)
                self.assertEqual(Gate(self.s3).read()[0]['state'], 'WORKING')

    def test_ssm_that_outlives_runner_blocks_all_new_server_work(self):
        self.api['ssm'].list_commands.return_value = {'Commands': [{'Status': 'InProgress'}]}
        with patch.object(m, 'checked_execute') as operation:
            with self.assertRaisesRegex(ValueError, 'DRAIN_TIMEOUT'): self.perform()
            operation.assert_not_called()
        self.assertEqual(Gate(self.s3).read()[0]['state'], 'WORKING')

    def test_ocr_waits_for_both_hosts_and_still_checks_backend(self):
        self.work = (dict(self.work[0], component='ocr'), HOSTS['ocr'])
        self.verify = (dict(self.verify[0], component='ocr'), HOSTS['ocr'])
        with patch.object(m, 'checked_execute', return_value=self.report): self.perform()
        self.assertEqual({x.kwargs['InstanceId'] for x in self.api['ssm'].list_commands.call_args_list}, set(HOSTS.values()))

    def test_finish_cannot_use_old_success_and_rechecks_main_after_host(self):
        with patch.object(m, 'checked_execute', return_value=self.report): self.perform()
        changed = {'object': {'sha': 'e'*40}}; current = {'object': {'sha': 'a'*40}}
        with patch.object(m, 'github', side_effect=[current, changed]), patch.object(m, 'checked_execute', return_value=self.report) as live:
            self.assertEqual(m.finish(self.api, dict(self.ctx, run_id='101'))['status'], 'LATEST_MAIN_MOVED')
            live.assert_called_once()
        self.assertEqual(Gate(self.s3).read()[0]['state'], 'VERIFIED')

    def test_finish_after_fresh_health_database_and_commit_proof_reopens(self):
        with patch.object(m, 'checked_execute', return_value=self.report): self.perform()
        with patch.object(m, 'github', return_value={'object': {'sha': 'a'*40}}), patch.object(m, 'checked_execute', return_value=self.report):
            self.assertEqual(m.finish(self.api, dict(self.ctx, run_id='101'))['status'], 'RESUMED_LATEST_MAIN_VERIFIED')
        self.assertEqual(Gate(self.s3).read()[0]['state'], 'OPEN')

    def test_finish_wrong_runtime_or_failed_health_keeps_hold(self):
        with patch.object(m, 'checked_execute', return_value=self.report): self.perform()
        for result in [ValueError('health'), dict(self.report, hashes={'backend_commit_sha256': 'e'*64})]:
            with patch.object(m, 'github', return_value={'object': {'sha': 'a'*40}}), patch.object(m, 'checked_execute', side_effect=[result]):
                with self.assertRaises(ValueError): m.finish(self.api, dict(self.ctx, run_id='101'))
        self.assertEqual(Gate(self.s3).read()[0]['state'], 'VERIFIED')

    def test_false_check_cannot_be_accepted_as_success(self):
        Path('operation-results/maintenance-work-result.json').write_text(json.dumps({'report': {'checks': {'valid': False}}}))
        with patch.object(m, 'execute', return_value={'success': True}):
            with self.assertRaisesRegex(ValueError, 'CHECKS_FAILED'):
                m.checked_execute({}, {}, {}, '', '', 'maintenance-work-')

    def test_operator_disabled_cd_is_never_overridden(self):
        with patch.object(m, 'checked_execute', return_value=self.report): self.perform()
        with patch.dict(os.environ, {'CD_ENABLED': 'false'}), patch.object(m, 'checked_execute') as live:
            with self.assertRaisesRegex(ValueError, 'OPERATOR_DISABLED'): m.finish(self.api, self.ctx)
            live.assert_not_called()
        self.assertEqual(Gate(self.s3).read()[0]['state'], 'VERIFIED')

    def test_drain_paginates_and_blocks_delayed_or_cancelling_commands(self):
        for status in ('Pending', 'InProgress', 'Delayed', 'Cancelling'):
            api = Mock(); api.list_commands.side_effect = [{'Commands': [], 'NextToken': 'next'}, {'Commands': [{'Status': status}]}]
            self.assertFalse(drained(api, ['i-test']))
            self.assertEqual(api.list_commands.call_args.kwargs['NextToken'], 'next')

    def test_probe_uses_installed_full_health_and_database_verifier_under_shared_lock(self):
        body = probe('a'*32, 'finish-101')['document']['mainSteps'][0]['inputs']['runCommand'][0]
        script = body.split("\n", 1)[1].rsplit('\nJJIKMUK_MAINTENANCE_PROBE', 1)[0]
        compile(script, 'fixed-probe', 'exec')
        self.assertIn("host.verify(host.baseline,'')", script)
        self.assertIn('with deployment_lock', script)
        self.assertNotIn('restart(', script)
