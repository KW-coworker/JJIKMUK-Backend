import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'cd/tests'))
from test_maintenance_gate import MemoryS3
from maintenance_gate import Gate
from connection import canonical, sha
import paused_images_closeout as closeout
import paused_images_host as host
from run import safe_report


class CloseoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.old = Path.cwd(); os.chdir(self.tmp.name)
        self.addCleanup(self.tmp.cleanup); self.addCleanup(lambda: os.chdir(self.old))
        Path('operation-results').mkdir()
        self.api = {'s3': MemoryS3(), 'ssm': Mock()}
        self.api['ssm'].list_commands.return_value = {'Commands': []}
        self.ctx = {'request_id': closeout.REQUEST, 'commit': 'a'*40, 'run_id': '123', 'attempt': '1'}
        Gate(self.api['s3']).start(closeout.REQUEST, 'b'*40, '43041472793', 'c'*64, 'd'*64)
        self.report = {'status': 'VERIFIED', 'checks': {'valid': True},
                       'counts': {'checked_rows': 241000, 'changed_rows': 236207},
                       'hashes': {'backend_commit_sha256': 'e'*64}}
        self.run = {'id': int(closeout.IMAGE_RUN), 'status': 'completed', 'conclusion': 'cancelled'}

    def execute(self, *args, **kwargs):
        self.assertEqual(kwargs, {})  # Use the actual executor's supported default prefix.
        compile(args[2]['document']['mainSteps'][0]['inputs']['runCommand'][0].split('\n', 1)[1].rsplit('\n', 1)[0], '<document>', 'exec')
        Path('operation-results/result.json').write_text(json.dumps({'report': self.report}))
        return {'success': True}

    def perform(self):
        with patch.object(closeout, 'github', return_value=self.run), patch.object(closeout, 'execute', side_effect=self.execute):
            return closeout.perform(self.api, self.ctx)

    def test_verified_partial_work_allows_resume_but_does_not_open_gate(self):
        result = self.perform()
        self.assertTrue(result['image_work_remains_paused'])
        self.assertEqual(result['remaining_rows'], 857863)
        gate = Gate(self.api['s3']).read()[0]
        self.assertEqual(gate['state'], 'VERIFIED')
        self.assertEqual(gate['run_id'], '43041472793')

    def test_running_image_work_or_non_cancelled_run_blocks_before_ssm(self):
        for status, conclusion in [('in_progress', None), ('completed', 'success')]:
            self.run.update(status=status, conclusion=conclusion)
            with self.assertRaisesRegex(ValueError, 'NOT_CANCELLED'):
                self.perform()
            self.assertEqual(Gate(self.api['s3']).read()[0]['state'], 'WORKING')

    def test_ssm_outliving_runner_blocks_closeout(self):
        self.api['ssm'].list_commands.return_value = {'Commands': [{'Status': 'InProgress'}]}
        with self.assertRaisesRegex(ValueError, 'SSM_BUSY'):
            self.perform()
        self.assertEqual(Gate(self.api['s3']).read()[0]['state'], 'WORKING')

    def test_partial_proof_or_failed_health_keeps_hold(self):
        for change in [('checked_rows', 240500), ('changed_rows', 236208)]:
            old = self.report['counts'][change[0]]
            self.report['counts'][change[0]] = change[1]
            with self.assertRaisesRegex(ValueError, 'PROOF'):
                self.perform()
            self.report['counts'][change[0]] = old
        self.report['checks']['valid'] = False
        with self.assertRaisesRegex(ValueError, 'PROOF'):
            self.perform()
        self.assertEqual(Gate(self.api['s3']).read()[0]['state'], 'WORKING')


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); (self.root / 'slices').mkdir()
        self.input_hash = 'c702663c6375447b0847334dc9d1707cf5383165622ca3a8cdb350838c322cdd'
        self.spec = {'input_sha256': self.input_hash, 'rows': 1098863, 'slices': []}
        for index in range(13):
            count = 1000 if index == 0 else 20000
            last = 328344 if index == 12 else index*25000 + 1498
            self.spec['slices'].append({'count': count, 'last_id': last})
            folder = self.root / 'slices' / f'{index:03d}'; folder.mkdir()
            request = {'seed_operation': closeout.SEED, 'package_sha256': '9e41ee6fcdacf6d95ef92d6d4c71ab0a696ecc8fa9776e8b9663fb4712f3a034',
                       'index': index, 'input_sha256': self.input_hash}
            value = {'status': 'VERIFIED', 'operation_id': sha(canonical(request)), 'checks': {'preserved': True},
                     'counts': {'checked': count, 'changed': count - (4793 if index == 1 else 0), 'last_id': last}}
            (folder / 'result.json').write_text(json.dumps(value))
        (self.root / 'input.json').write_text(json.dumps(self.spec))
        self.patch = patch.object(host, 'read', side_effect=lambda p, limit: p.read_bytes())
        self.patch.start(); self.addCleanup(self.patch.stop)
        host.SEED = closeout.SEED

    def test_complete_fixed_boundary_is_accepted(self):
        counts, digest = host.paused_boundary(self.root)
        self.assertEqual(counts, {'checked_rows': 241000, 'changed_rows': 236207})
        safe_report(json.dumps({'status': 'VERIFIED', 'counts': counts, 'hashes': {'proof': digest}}))

    def test_next_slice_even_without_result_blocks_acceptance(self):
        (self.root / 'slices/013').mkdir()
        with self.assertRaisesRegex(ValueError, 'BOUNDARY_CHANGED'):
            host.paused_boundary(self.root)

    def test_one_incomplete_or_wrong_source_result_blocks_acceptance(self):
        target = self.root / 'slices/012/result.json'
        original = json.loads(target.read_bytes())
        for value in [dict(original, status='FAILED'), dict(original, operation_id='a'*64),
                      dict(original, checks={'preserved': False})]:
            target.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'UNVERIFIED'):
                host.paused_boundary(self.root)
