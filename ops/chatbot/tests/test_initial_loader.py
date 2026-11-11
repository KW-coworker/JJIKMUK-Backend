import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import initial_source_loader as loader


class InitialLoaderTests(unittest.TestCase):
    def test_dependencies_import_with_only_the_installed_payload(self):
        root = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as name:
            target = Path(name)
            for source in (root / 'ops/cd').glob('*.py'):
                shutil.copyfile(source, target / source.name)
            for name in ('install_coordinator.py', 'private_runner.py', 'private_plan.py', 'connection.py',
                         'bootstrap.py', 'readiness_probe.py', 'readiness_paths.py', 'fulltext_definition.py'):
                shutil.copyfile(root / 'ops/operations' / name, target / name)
            self.assertFalse((target / 'run.py').exists())
            source = str(root / 'ops/chatbot/initial_source_loader.py')
            script = ('import importlib.util,sys;sys.path.insert(0,' + repr(str(target)) + ');'
                      'spec=importlib.util.spec_from_file_location("loader",' + repr(source) + ');'
                      'm=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);'
                      'assert len(m.installed_modules())==11;print("INSTALLED_IMPORTS_OK")')
            run = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', script], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout.strip(), 'INSTALLED_IMPORTS_OK')

    def test_report_retains_failure_and_rejects_unbounded_or_secret_fields(self):
        for status in ('SUCCEEDED', 'ROLLED_BACK', 'PREFLIGHT_FAILED', 'MANUAL_RECOVERY_REQUIRED'):
            report = {'status': status, 'checks': {'healthy': True}, 'codes': ['CHECK_FAILED'],
                      'counts': {'files': 361}, 'hashes': {'source': 'a'*64}}
            self.assertEqual(loader.safe_report(json.dumps(report)), report)
        for report in ({'status': 'OK'}, {'status': 'SUCCEEDED', 'environment': {'password': 'value'}},
                       {'status': 'SUCCEEDED', 'checks': {'healthy': 1}},
                       {'status': 'SUCCEEDED', 'codes': ['raw secret text']},
                       {'status': 'SUCCEEDED', 'counts': {'files': -1}},
                       {'status': 'SUCCEEDED', 'hashes': {'source': 'raw value'}}):
            with self.assertRaises(ValueError):
                loader.safe_report(json.dumps(report))

    def test_previous_host_attempt_is_rejected_before_acquiring_a_new_lock(self):
        from unittest.mock import Mock, patch
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            operation = 'a'*64
            (root/'history'/operation).mkdir(parents=True)
            need = lambda ok, code: None if ok else (_ for _ in ()).throw(ValueError(code))
            locked = Mock()
            dependencies = (lambda e: None, Mock(), Mock(), root, locked, Mock(),
                            lambda e: b'', lambda e: operation, 'bucket', 'account', need)
            real_path = Path
            def path(value):
                if value == '/opt/jjikmuk-cd/bin':
                    item = Mock()
                    item.parents = []
                    item.is_symlink.return_value = False
                    item.lstat.return_value = SimpleNamespace(st_uid=0, st_mode=0o755)
                    return item
                return real_path(value)
            envelope = {'component': 'chatbot', 'operation': 'deploy',
                        'approval_id': 'USER_RESUME_BACKEND_AND_CHATBOT_20261112', 'recovery_sha256': None}
            with patch.object(loader, 'Path', side_effect=path), patch.object(loader, 'installed_modules', return_value=dependencies):
                with self.assertRaisesRegex(ValueError, 'PREVIOUS_EXECUTION_EXISTS'):
                    loader.execute(envelope)
            locked.assert_not_called()
