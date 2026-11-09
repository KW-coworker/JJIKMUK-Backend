"""Exercise first-run imports in a fresh interpreter and fresh installed bin."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class EntryPointTests(unittest.TestCase):
    def test_fresh_entry_points_preserve_protected_bin(self):
        source = Path(__file__).resolve().parents[1]
        for entrypoint in ['commission', 'deploy']:
            with self.subTest(entrypoint=entrypoint), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                installed = root / 'bin'
                installed.mkdir()
                for path in source.glob('*.py'):
                    shutil.copyfile(path, installed / path.name)
                (root / 'application-local.properties').write_text(
                    'spring.jpa.hibernate.ddl-auto=validate\nspring.sql.init.mode=never', encoding='utf-8')
                script = root / 'probe.py'
                script.write_text('''
import runpy
from pathlib import Path
import sys
from unittest.mock import patch

root = Path(__file__).parent
sys.path.insert(0, str(root / 'bin'))
runpy.run_path(str(root / 'bin' / (sys.argv[1] + '.py')), run_name='entrypoint_inspection')
from host import Host
host = Host.__new__(Host)
host.config = {
    'runtime_contract': {'flyway_enabled': True, 'sql_init_mode': 'never'},
    'protected_paths': [str(root / 'bin')],
    'working_directory': str(root),
    'database': {'properties_file': str(root / 'application-local.properties')},
}
before = host.protected()
original = Path.read_bytes
def process_environment(path):
    if path.as_posix().endswith('/proc/123/environ'):
        return b'HIBERNATE_DDL_AUTO=validate\\0'
    return original(path)
with patch.object(Path, 'read_bytes', process_environment):
    host.environment(123, [])
assert before == host.protected(), 'PROTECTED_BIN_CHANGED_DURING_INSPECTION'
assert not list((root / 'bin').rglob('*.pyc')), 'ENTRYPOINT_WROTE_BYTECODE'
''', encoding='utf-8')
                result = subprocess.run([sys.executable, '-I', str(script), entrypoint],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(0, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main()
