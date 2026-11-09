import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from preflight import inspect_disabled
from test_host import fixture_jar
from manifest import make_manifest,digest


class PreflightTests(unittest.TestCase):
    def test_disabled_read_checks_do_not_activate_or_enroll(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);jar=root/'old.jar';fixture_jar(jar)
            h=MagicMock();h.root=root;h.config={'enabled':False,'working_directory':td,'health_checks':[]}
            h.unit.side_effect=lambda name:{'ActiveState':'active','MainPID':'321'}[name]
            h.identity.return_value='same';h.environment.return_value='same';h.protected.return_value={'same':1}
            argv=['java','-Dchatbot.developer-test-auto-consent=true','-jar',str(jar)]
            current={'jar':str(jar),'jar_sha256':digest(jar),'argv':argv}
            m=make_manifest(jar,'a'*40,'1','1')
            original=Path.read_bytes
            def read(p):
                return ('\0'.join(argv)+'\0').encode() if str(p).endswith('cmdline') else original(p)
            with patch.object(Path,'read_bytes',read),patch.object(Path,'resolve',return_value=root):
                self.assertEqual('DISABLED_PREFLIGHT_PASSED',inspect_disabled(h,m,current)['status'])
                h.database.assert_called_once_with(m)
                h.restart.assert_not_called();h.activate.assert_not_called();h.commit.assert_not_called()
                self.assertEqual([jar],list(root.iterdir()))
                import copy
                changed=copy.deepcopy(m);changed['configuration']['BOOT-INF/classes/application.properties']='f'*64
                with self.assertRaisesRegex(ValueError,'INITIAL_SCHEMA_OR_CONFIGURATION_CHANGE'):
                    inspect_disabled(h,changed,current)
                h.database.side_effect=ValueError('BAD_HISTORY')
                with self.assertRaisesRegex(ValueError,'BAD_HISTORY'):inspect_disabled(h,m,current)
                h.restart.assert_not_called()

    def test_enabled_or_enrolled_server_refused(self):
        h=MagicMock();h.config={'enabled':True}
        with self.assertRaisesRegex(ValueError,'DISABLED_PREFLIGHT_ONLY'):inspect_disabled(h,{}, {})
        with tempfile.TemporaryDirectory() as td:
            h.root=Path(td);h.config={'enabled':False};(h.root/'baseline.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'ALREADY_COMMISSIONED'):inspect_disabled(h,{}, {})
