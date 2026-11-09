from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from package_install import formal_main,package


class InstallPackageTests(unittest.TestCase):
    def test_local_branch_cannot_be_packaged_as_main(self):
        with patch('package_install.subprocess.check_output',side_effect=['a'*40,'b'*40]),self.assertRaisesRegex(ValueError,'FORMAL_MAIN_REQUIRED'):
            formal_main(Path('.'),'a'*40)

    def test_dirty_main_cannot_be_packaged(self):
        with patch('package_install.subprocess.check_output',side_effect=['a'*40,'a'*40,' M ops/cd/host.py']),self.assertRaisesRegex(ValueError,'SOURCE_NOT_CLEAN'):
            formal_main(Path('.'),'a'*40)

    def test_unresolved_config_stops_before_archive_creation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);config=p/'config.json';config.write_text('{"enabled":false,"runtime_contract":"REQUIRES_OBSERVATION"}')
            with patch('package_install.formal_main'),self.assertRaisesRegex(ValueError,'UNRESOLVED_CONFIG'):
                package(p,p,p/'jar',config,'a'*40,p/'payload.zip')
            self.assertFalse((p/'payload.zip').exists())
