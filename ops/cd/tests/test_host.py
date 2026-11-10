import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from host import Host
from manifest import make_manifest
from database_probe import probe


def fixture_jar(path):
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('META-INF/MANIFEST.MF','JarLauncher')
        z.writestr('BOOT-INF/classes/org/jjikmuk/backend/domain/chat/AiChatClient.class','chatbot.developer-test-auto-consent')
        z.writestr('BOOT-INF/classes/application.properties','spring.flyway.enabled=true')
        z.writestr('BOOT-INF/classes/db/migration/V1__test.sql','select 1;')


class HostTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix','Real symlink/crash test runs on Linux CI')
    def test_process_death_preserves_previous_and_blocks_replay(self):
        for stage in ['SWITCH_INTENT','activate','restart','verify','commit']:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); fixture_jar(root/'source.jar')
                env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])}
                p=subprocess.run([sys.executable,str(Path(__file__).with_name('crash_worker.py')),tmp,stage],env=env,
                                 capture_output=True,timeout=20)
                self.assertEqual(77,p.returncode,p.stderr.decode())
                journal=json.loads((root/'runs/2-1.json').read_text())
                self.assertEqual('a'*40,journal['transition']['previous']['manifest']['commit'])
                self.assertEqual('b'*40,journal['transition']['candidate']['manifest']['commit'])
                host=Host.__new__(Host); host.root=root
                # This fixture lives in a user-owned temporary directory, not an
                # installed root-owned host tree. Test journal recovery separately.
                with patch('host.secure'),self.assertRaisesRegex(ValueError,'UNRESOLVED_RUN'):
                    host.existing({'run_key':'3-1'})
                current=(root/'current').resolve().name
                self.assertTrue(current.startswith('a'*40 if stage=='SWITCH_INTENT' else 'b'*40))

    def test_environment_drift_and_unsafe_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary=Path(tmp)/'application-local.properties'; primary.write_text('spring.jpa.hibernate.ddl-auto=validate\nspring.sql.init.mode=never')
            host=Host.__new__(Host); host.config={'runtime_contract':{'flyway_enabled':True,'sql_init_mode':'never'},'working_directory':tmp,'database':{'properties_file':str(primary)}}
            with patch('pathlib.Path.read_bytes',return_value=b'HIBERNATE_DDL_AUTO=validate\0INVOCATION_ID=old\0'):
                first=host.environment(123,[])
            with patch('pathlib.Path.read_bytes',return_value=b'HIBERNATE_DDL_AUTO=validate\0INVOCATION_ID=new\0'):
                self.assertEqual(first,host.environment(456,[]))
            with patch('pathlib.Path.read_bytes',return_value=b'HIBERNATE_DDL_AUTO=validate\0DIFFERENT=1\0'):
                self.assertNotEqual(first,host.environment(456,[]))
            for values in [b'SPRING_JPA_HIBERNATE_DDLAUTO=update\0',b'SPRING_DATASOURCE_URL=wrong\0',
                           b'JAVA_TOOL_OPTIONS=-Dspring.jpa.hibernate.ddl-auto=create\0',b'PRODUCT_IMPORT_ENABLED=true\0']:
                with self.subTest(values=values),patch('pathlib.Path.read_bytes',return_value=values),self.assertRaises(ValueError):
                    host.environment(456,[])

    def test_probe_target_mismatch_fails_before_connect(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'app.properties'; path.write_text('spring.datasource.url=jdbc:mysql://approved:3306/db')
            db={'properties_file':str(path),'expected_jdbc_url':'jdbc:mysql://approved:3306/db','host':'other','name':'db'}
            from unittest.mock import MagicMock
            mysql=MagicMock()
            with patch.dict('sys.modules',{'pymysql':mysql}), self.assertRaisesRegex(ValueError,'DATABASE_TARGET_MISMATCH'):
                probe({'database':db})
            mysql.connect.assert_not_called()

    def test_oversized_remote_object_stops_before_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Host.__new__(Host); host.root=Path(tmp); (host.root/'releases').mkdir()
            host.config={'prefix':'releases','aws':'aws','region':'ap-northeast-2','bucket':'test'}
            req={'commit':'a'*40,'run_id':'1','attempt':'1','manifest_version':'v1','jar_version':'v2'}
            with patch('host_aws.require_identity'),patch('host_aws.command',return_value=json.dumps({'ContentLength':200000})) as cli:
                with self.assertRaisesRegex(ValueError,'S3_OBJECT_SIZE'): host.prepare(req)
                self.assertEqual(1,cli.call_count)
                self.assertIn('head-object',cli.call_args.args[0])
