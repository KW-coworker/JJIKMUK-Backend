import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import maintenance_control as control
from connection import canonical, sha


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'journal'
        inputs = dict(mode='apply', expected_sha='a'*40, request_id='b'*32, work_plan='ops/operations/plans/work.json',
                      work_sha256='c'*64, verify_plan='ops/operations/plans/verify.json', verify_sha256='d'*64, confirm=True)
        self.request = {'inputs': inputs, 'approval': {'status': 'APPROVED', 'input_sha256': sha(canonical(inputs))}}
        self.main = 'e'*40
        self.api = Mock()
        self.api.call.side_effect = lambda path, *args: ({'value': 'true'} if path.endswith('/BACKEND_CD_ENABLED')
            else {'object': {'sha': self.main}} if '/git/ref/' in path else {'jobs': [{'name': 'deploy', 'conclusion': 'skipped'}]})
        self.calls = []; self.reports = {}

    def wait(self, api, workflow, inputs, folder, **kwargs):
        self.calls.append((workflow, inputs, kwargs))
        run = dict(id=100+len(self.calls), head_sha=inputs['expected_sha'], run_attempt=1, conclusion='success')
        if inputs.get('mode') == 'apply':
            result = dict(status='VERIFIED_AWAITING_LATEST_MAIN', request_id='b'*32, commit='a'*40,
                          run_id=str(run['id']), work_sha256='c'*64, verify_sha256='d'*64,
                          backend_commit_sha256=sha(('a'*40).encode()))
        elif workflow == 'backend-cd.yml':
            result = dict(status='SUCCEEDED', commit=inputs['expected_sha'], run_id=str(run['id']), attempt='1')
        else:
            result = dict(status='RESUMED_LATEST_MAIN_VERIFIED', request_id='b'*32, commit=inputs['expected_sha'])
        self.reports[run['id']] = result
        return run

    def execute(self, wait=None):
        plans = [{'component': 'db', 'operation': 'deploy', 'approval_id': 'APPROVED_TEST'},
                 {'component': 'db', 'operation': 'verify', 'approval_id': 'APPROVED_TEST'}]
        with patch.object(control, 'read_plan', side_effect=plans), patch.object(control, 'start_and_wait', side_effect=wait or self.wait), \
             patch.object(control, 'artifact', side_effect=lambda api, run, *args: self.reports[run['id']]):
            return control.execute(self.api, self.request, self.root, sleep=lambda _: None)

    def test_verified_work_then_latest_deploy_then_fresh_finish(self):
        result = self.execute()
        self.assertEqual(result['commit'], 'e'*40)
        self.assertEqual([x[0] for x in self.calls], ['server-maintenance.yml', 'backend-cd.yml', 'server-maintenance.yml'])
        self.assertTrue(self.calls[0][2]['approve']); self.assertTrue(self.calls[2][2]['approve'])
        self.assertTrue((self.root / 'completion.json').exists())
        self.assertFalse(any(x.args[1:] for x in self.api.call.call_args_list))  # No variable mutation.

    def test_same_commit_still_gets_fresh_finish_without_redeploy(self):
        self.main = 'a'*40
        self.execute()
        self.assertEqual([x[1]['mode'] for x in self.calls], ['apply', 'finish'])

    def test_new_merge_during_deploy_is_followed_before_finish(self):
        def moving(*args, **kwargs):
            result = self.wait(*args, **kwargs)
            if len(self.calls) == 2: self.main = 'f'*40
            return result
        result = self.execute(moving)
        self.assertEqual(result['commit'], 'f'*40)
        self.assertEqual([x[1].get('expected_sha') for x in self.calls], ['a'*40, 'e'*40, 'f'*40, 'f'*40])

    def test_main_moves_during_finish_stays_in_loop(self):
        def moving(*args, **kwargs):
            result = self.wait(*args, **kwargs)
            if len(self.calls) == 3:
                self.reports[result['id']]['status'] = 'LATEST_MAIN_MOVED'; self.main = 'f'*40
            return result
        self.assertEqual(self.execute(moving)['commit'], 'f'*40)
        self.assertEqual(len(self.calls), 5)

    def test_failure_never_finishes_or_replays_work(self):
        for failed_call in (1, 2, 3):
            with self.subTest(call=failed_call):
                self.root = Path(self.tmp.name) / str(failed_call); self.calls = []
                def failure(*args, **kwargs):
                    run = self.wait(*args, **kwargs)
                    if len(self.calls) == failed_call: run['conclusion'] = 'failure'
                    return run
                with self.assertRaises(ValueError): self.execute(failure)
                self.assertEqual(len(self.calls), failed_call + (1 if failed_call == 3 else 0))
                self.assertFalse((self.root / 'completion.json').exists())
                self.assertEqual(sum(c[1].get('mode') == 'apply' for c in self.calls), 1)

    def test_tampered_approval_does_not_create_a_journal_or_dispatch(self):
        self.request['inputs']['work_sha256'] = 'e'*64
        with self.assertRaisesRegex(ValueError, 'EXACT_APPROVAL'): self.execute()
        self.assertFalse(self.root.exists()); self.assertEqual(self.calls, [])

    def test_lost_dispatch_response_is_recorded_once_without_retry(self):
        api = Mock(); calls = []
        def call(path, method='GET', payload=None):
            calls.append(method)
            if method == 'POST': raise TimeoutError('lost')
            return {'object': {'sha': 'a'*40}}
        api.call.side_effect = call
        with self.assertRaises(TimeoutError):
            control.start_and_wait(api, 'server-maintenance.yml', self.request['inputs'], self.root)
        self.assertEqual(calls, ['GET', 'POST'])
        self.assertTrue((self.root / 'dispatch-intent.json').exists())
        with self.assertRaises(FileExistsError):
            control.start_and_wait(api, 'server-maintenance.yml', self.request['inputs'], self.root)

    def test_change_before_resume_dispatch_retries_only_new_main(self):
        count = 0
        def moving(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                self.main = 'f'*40
                raise ValueError('MAIN_CHANGED_BEFORE_DISPATCH')
            return self.wait(*args, **kwargs)
        self.assertEqual(self.execute(moving)['commit'], 'f'*40)

    def test_continuous_new_merges_are_bounded_and_do_not_reopen(self):
        def moving(*args, **kwargs):
            result = self.wait(*args, **kwargs)
            if args[1] == 'backend-cd.yml': self.main = f'{len(self.calls):040x}'
            return result
        with self.assertRaisesRegex(ValueError, 'CONTINUOUSLY_MOVING'): self.execute(moving)
        self.assertFalse((self.root / 'completion.json').exists())
        self.assertEqual(sum(x[1].get('mode') == 'apply' for x in self.calls), 1)

    def test_lost_finish_artifact_collects_durable_success_without_replaying_work(self):
        original = self.wait
        def missing(*args, **kwargs):
            run = original(*args, **kwargs)
            if len(self.calls) == 3: run['conclusion'] = 'failure'
            return run
        observed = {'current_main_verified': True, 'current_main': 'e'*40}
        with patch.object(control, 'collect', return_value=observed) as collect:
            result = self.execute(missing)
        collect.assert_called_once()
        self.assertTrue(result['collected_after_lost_completion'])
        self.assertEqual(len(self.calls), 3)

    def test_unknown_final_collection_never_claims_completion_or_replays(self):
        def failed(*args, **kwargs):
            run = self.wait(*args, **kwargs)
            if len(self.calls) == 3: run['conclusion'] = 'failure'
            return run
        with patch.object(control, 'collect', side_effect=ValueError('FINAL_STATE_UNKNOWN')):
            with self.assertRaisesRegex(ValueError, 'FINAL_STATE_UNKNOWN'): self.execute(failed)
        self.assertFalse((self.root / 'completion.json').exists())

    def test_repeated_collection_on_same_main_finds_its_own_run(self):
        self.root.mkdir(); control.save(self.root, 'approved-request.json', self.request)
        runs = []; dispatch_ids = []
        def call(path, method='GET', payload=None):
            if '/git/ref/' in path: return {'object': {'sha': self.main}}
            if path.endswith('/dispatches'):
                inputs = payload['inputs']; dispatch_ids.append(inputs['dispatch_id'])
                title = f"Maintenance collect at {self.main} [" + 'b'*32 + '] [' + inputs['dispatch_id'] + ']'
                runs.append({'id': 200+len(runs), 'display_title': title, 'head_branch': 'main',
                             'head_sha': self.main, 'run_attempt': 1, 'path': '.github/workflows/server-maintenance.yml',
                             'status': 'in_progress', 'conclusion': None})
                return {}
            if '/pending_deployments' in path:
                if method == 'POST':
                    runs[-1].update(status='completed', conclusion='success'); return {}
                return [{'environment': {'name': 'production', 'id': 1}, 'current_user_can_approve': True}]
            if '/runs?' in path: return {'workflow_runs': list(runs)}
            raise AssertionError(path)
        self.api.call.side_effect = call
        gate = dict(format=1, state='OPEN', request_id='b'*32, commit='a'*40, run_id='101', work_sha256='c'*64,
                    verify_sha256='d'*64, backend_commit_sha256=sha(self.main.encode()), verification_sha256='1'*64,
                    transition_id='2'*32, finish_verification_sha256='3'*64)
        observed = {'status': 'MAINTENANCE_STATE_COLLECTED', 'request_id': 'b'*32, 'gate': gate,
                    'current_main': self.main, 'current_main_verified': True}
        with patch.object(control, 'artifact', return_value=observed) as artifact:
            for _ in range(2): self.assertTrue(control.collect(self.api, self.root, sleep=lambda _: None)['current_main_verified'])
        self.assertEqual([x.args[1]['id'] for x in artifact.call_args_list], [200, 201])
        self.assertEqual(len(set(dispatch_ids)), 2)
