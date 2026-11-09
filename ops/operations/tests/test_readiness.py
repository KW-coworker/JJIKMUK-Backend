import ast
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import readiness_document as builder
import readiness_probe as probe
from readiness_paths import checked_paths
from run import load_plan, safe_report, operation_succeeded

ROOT = Path(__file__).resolve().parents[3]
SECRET = 'NEVER_EXPORT_DB_PASSWORD_001'


class ReadinessTests(unittest.TestCase):
    def test_pending_plan_cannot_execute_and_document_has_no_parameters(self):
        expected = builder.plan(ROOT)
        builder.verify_archive(ROOT)
        path = ROOT / 'ops/operations/plans' / builder.PLAN_NAME
        builder.verify_record(json.loads(path.read_bytes()), expected)
        self.assertFalse(expected['approved'])
        self.assertEqual({}, expected['document']['parameters'])
        self.assertLess(len(builder.canonical(expected['document'])), 60000)
        with tempfile.TemporaryDirectory() as td:
            pending = Path(td) / 'pending.json'
            pending.write_bytes(builder.canonical(expected))
            with patch('run.Path', return_value=pending), self.assertRaisesRegex(ValueError, 'PLAN_NOT_APPROVED'):
                load_plan('ops/operations/plans/' + builder.PLAN_NAME, builder.sha(pending.read_bytes()))
        approved = dict(expected, approved=True, approval_id='EXPLICIT_USER_APPROVAL_001')
        self.assertEqual(builder.sha(builder.canonical(expected['document'])),
                         builder.sha(builder.canonical(approved['document'])))
        builder.verify_record(approved, expected)
        with self.assertRaises(ValueError):
            builder.verify_record(dict(expected, approved=True), expected)
        changed = json.loads(json.dumps(approved))
        changed['document']['mainSteps'][0]['inputs']['timeoutSeconds'] = '999'
        with self.assertRaisesRegex(ValueError, 'READINESS_PLAN_STALE'):
            builder.verify_record(changed, expected)

    def test_generated_shell_and_embedded_python_are_valid(self):
        plan = builder.plan(ROOT)
        command = plan['document']['mainSteps'][0]['inputs']['runCommand'][0]
        source = command.split('\n', 1)[1].rsplit('\nJJIKMUK_READINESS', 1)[0]
        tree = ast.parse(source)
        constants = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
                     if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
        self.assertTrue(constants['STAGE'].startswith('/opt/jjikmuk-readiness-'))
        self.assertEqual({'readiness_probe.py', 'readiness_paths.py', 'contract.json'}, set(constants['FILES']))
        self.assertIn("response.read(46741)", source)
        self.assertIn("response.geturl()==WHEEL_URL", source)
        self.assertIn("ProxyHandler({})", source)
        self.assertIn("assert not os.path.lexists(p)", source)

    def bootstrap(self, stage):
        command = builder.plan(ROOT)['document']['mainSteps'][0]['inputs']['runCommand'][0]
        source = command.split('\n', 1)[1].rsplit('\nJJIKMUK_READINESS', 1)[0]
        tree = ast.parse(source)
        original = ast.literal_eval(tree.body[0].value)
        return source.replace(repr(original), repr(str(stage)), 1)

    def test_existing_stage_blocks_download_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            marker = path / 'keep.txt'
            marker.write_text('unchanged')
            source = self.bootstrap(path)
            info = type('Info', (), {'st_uid': 0, 'st_mode': 0o40755})()
            output = io.StringIO()
            with patch.object(os, 'geteuid', return_value=0, create=True), \
                 patch.object(Path, 'lstat', return_value=info), \
                 patch('urllib.request.build_opener') as opener, contextlib.redirect_stdout(output):
                exec(compile(source, '<fixed-bootstrap-fixture>', 'exec'), {})
            opener.assert_not_called()
            self.assertEqual('unchanged', marker.read_text())
            self.assertEqual('PREFLIGHT_FAILED', json.loads(output.getvalue())['status'])

    @unittest.skipUnless(os.name == 'posix', 'Linux file-descriptor and umask semantics')
    def test_native_file_reads_refuse_parent_links_and_special_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'real').mkdir()
            (root / 'real/data').write_bytes(b'bounded')
            (root / 'link').symlink_to(root / 'real', target_is_directory=True)
            self.assertEqual(b'bounded', probe.read(root / 'real/data', 7))
            with self.assertRaises(Exception):
                probe.read(root / 'link/data', 7)
            with self.assertRaises(probe.ProbeStop):
                probe.read(root / 'real/data', 6)
            os.mkfifo(root / 'fifo')
            with self.assertRaises(probe.ProbeStop):
                probe.read(root / 'fifo', 7)

    @unittest.skipUnless(os.name == 'posix', 'Linux umask semantics')
    def test_new_stage_readable_under_restrictive_umask_and_bad_download_is_not_executed(self):
        for corrupt in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                stage = Path(directory) / 'stage'
                raw = b'x' * 46740
                source = self.bootstrap(stage).replace(builder.WHEEL_SHA, builder.sha(raw))
                response = MagicMock()
                response.__enter__.return_value = response
                response.status = 200
                response.geturl.return_value = builder.WHEEL_URL
                response.read.return_value = b'bad' if corrupt else raw
                opener = MagicMock()
                opener.open.return_value = response
                result = type('Result', (), {'returncode': 0, 'stdout': b'{"status":"OK"}'})()
                info = type('Info', (), {'st_uid': 0, 'st_mode': 0o40755})()
                output = io.StringIO()
                old = os.umask(0o077)
                try:
                    with patch.object(os, 'geteuid', return_value=0), \
                         patch.object(Path, 'lstat', return_value=info), \
                         patch('urllib.request.build_opener', return_value=opener), \
                         patch('subprocess.run', return_value=result) as run, contextlib.redirect_stdout(output):
                        exec(compile(source, '<fixed-bootstrap-fixture>', 'exec'), {})
                finally:
                    os.umask(old)
                self.assertEqual(0o755, stage.stat().st_mode & 0o777)
                if corrupt:
                    run.assert_not_called()
                    self.assertEqual('PREFLIGHT_FAILED', json.loads(output.getvalue())['status'])
                else:
                    run.assert_called_once()
                    self.assertEqual(4, len(list(stage.iterdir())))
                    self.assertEqual('OK', json.loads(output.getvalue())['status'])

    def test_path_output_is_not_a_general_text_channel(self):
        values = {'backend.env_0': '/etc/jjikmuk-institution/backend.env',
                  'backend.working_directory': probe.WORKDIR,
                  'chatbot.executable': '/opt/food-chatbot/venv/bin/python'}
        report = {'status': 'OK', 'paths': values, 'checks': {'deployment_ready': False}}
        self.assertEqual(report, safe_report(json.dumps(report)))
        for key, value in [('password', SECRET), ('backend.env_0', '/etc/shadow'),
                           ('backend.env_0', '/etc/.aws/credentials'),
                           ('backend.env_0', '/etc/../root/key'), ('backend.env_0', '/etc/a\nsecret'),
                           ('backend.env_0', 'https://example.com/?token=' + SECRET),
                           ('backend.env_0', '/etc//key'), ('chatbot.argv', '/usr/bin/python')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                safe_report(json.dumps({'status': 'OK', 'paths': {key: value}}))
        with self.assertRaises(ValueError):
            checked_paths({'backend.env_' + str(i): '/etc/input' for i in range(81)})

    def db(self, fail=False, overflow=False, mismatch=False):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value.__enter__.return_value
        columns = [('chatbot_logs', 'policy_version', 1, 'varchar(256)', 'YES', 256),
                   ('flyway_schema_history', 'version', 1, 'varchar(50)', 'YES', 50)]
        contract = {'required_columns': {'19': [['users', 'profile_version']]},
                    'migrations': [{'version': '19', 'script': 'V19__add.sql', 'checksum': 123}]}
        columns.append(('users', 'profile_version', 2, 'bigint', 'NO', None))
        cur.fetchmany.side_effect = [columns * 1400 if overflow else columns, [],
                                    [('19', 'V19__add.sql', 999 if mismatch else 123, 1, 'SQL')]]
        if fail:
            cur.execute.side_effect = RuntimeError(SECRET)
        connect = MagicMock(return_value=conn)
        return conn, cur, connect, contract

    def test_db_uses_one_tls_connection_metadata_only_and_rolls_back(self):
        conn, cur, connect, contract = self.db()
        report = probe.query_schema(connect, {'spring.datasource.username': 'fixture',
                                              'spring.datasource.password': SECRET}, contract)
        connect.assert_called_once()
        args = connect.call_args.kwargs
        self.assertEqual(probe.DB_HOST, args['host'])
        self.assertTrue(args['ssl_verify_cert'] and args['ssl_verify_identity'])
        self.assertFalse(args['local_infile'])
        self.assertEqual([10, 5, 5], [args['read_timeout'], args['write_timeout'], args['connect_timeout']])
        sql = [c.args[0] for c in cur.execute.call_args_list]
        self.assertEqual('START TRANSACTION READ ONLY', sql[2])
        self.assertEqual(6, len(sql))
        self.assertTrue(all('information_schema.' in s or 'FROM flyway_schema_history ' in s for s in sql[3:]))
        conn.rollback.assert_called_once()
        conn.__exit__.assert_called_once()
        self.assertTrue(report['checks']['db.history_matches_candidate'])
        self.assertNotIn(SECRET, json.dumps(report))
        self.assertEqual(report, safe_report(json.dumps(report)))

    def test_db_error_or_limit_still_rolls_back_and_exits(self):
        for opts in ({'fail': True}, {'overflow': True}):
            conn, _, connect, contract = self.db(**opts)
            with self.assertRaises(Exception):
                probe.query_schema(connect, {'spring.datasource.username': 'fixture',
                                             'spring.datasource.password': SECRET}, contract)
            conn.rollback.assert_called_once()
            conn.__exit__.assert_called_once()

    def test_missing_history_and_changed_checksum_are_observations_not_deployment_passes(self):
        conn, cur, connect, contract = self.db(mismatch=True)
        report = probe.query_schema(connect, {'spring.datasource.username': 'fixture',
                                              'spring.datasource.password': SECRET}, contract)
        self.assertFalse(report['checks']['db.history_matches_candidate'])
        cur.fetchmany.side_effect = [[('users', 'id', 1, 'bigint', 'NO', None)], []]
        report = probe.query_schema(connect, {'spring.datasource.username': 'fixture',
                                              'spring.datasource.password': SECRET}, contract)
        self.assertFalse(report['checks']['db.history_matches_candidate'])
        self.assertFalse(report['checks']['db.v19_columns_present'])
        self.assertFalse(report['checks']['db.chatbot_policy_version_256'])

    def test_db_override_target_and_ambiguous_properties_fail_before_connection(self):
        raw = ('spring.datasource.url=jdbc:mysql://' + probe.DB_HOST + ':3306/jjikmuk?useSSL=false\n'
               'spring.datasource.username=fixture\nspring.datasource.password=' + SECRET).encode()
        for env, content in [({'SPRING_DATASOURCE_URL': 'x'}, raw), ({'JAVA_TOOL_OPTIONS': '-Dx=y'}, raw),
                             ({}, raw.replace(probe.DB_HOST.encode(), b'other.example.com')),
                             ({}, raw + b'\nspring.datasource.username=duplicate'),
                             ({}, raw + b'\nspring.config.import=file:elsewhere')]:
            with patch.object(probe, 'backend_identity', return_value=('123', b'args', b'1')), \
                 patch.object(probe, 'environment', return_value=(b'raw', env)), \
                 patch.object(probe, 'read', return_value=content), self.assertRaises(ValueError):
                probe.database_inputs()

    def test_vendor_tamper_does_not_modify_import_path(self):
        stage = MagicMock()
        wheel = stage.__truediv__.return_value
        wheel.parents = []
        wheel.is_symlink.return_value = False
        wheel.lstat.return_value = type('Info', (), {'st_uid': 0, 'st_mode': 0o100644})()
        with patch.object(probe, 'read', return_value=b'x' * 46740), \
             patch.object(probe.sys, 'path', list(probe.sys.path)):
            before = list(probe.sys.path)
            with self.assertRaisesRegex(ValueError, 'DB_VENDOR_HASH'):
                probe.load_pinned_vendor(stage)
            self.assertEqual(before, probe.sys.path)

    def test_top_level_errors_never_print_credentials(self):
        output = io.StringIO()
        with patch.object(probe, 'need', side_effect=RuntimeError(SECRET)), \
             contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            probe.main()
        self.assertNotIn(SECRET, output.getvalue())
        report = safe_report(output.getvalue())
        self.assertFalse(operation_succeeded({'status': 'Success', 'response_code': 0, 'report': report}))

    def test_large_realistic_metadata_fits_report_limits(self):
        report = {'status': 'OK', 'paths': {}, 'checks': {'deployment_ready': False}, 'counts': {}, 'hashes': {}}
        info = type('Info', (), {'st_uid': 0, 'st_gid': 0, 'st_mode': 0o100600,
                                'st_dev': 1, 'st_ino': 2, 'st_size': 10, 'st_mtime_ns': 123})()
        with patch.object(Path, 'lstat', return_value=info):
            for prefix in ('backend', 'chatbot'):
                for i in range(18):
                    probe.metadata(report, prefix + '.env_' + str(i), '/etc/jjikmuk-institution/env-' + str(i))
        self.assertEqual(report, safe_report(json.dumps(report)))
        self.assertLess(len(json.dumps(report).encode()), 16384)

    def test_observe_preserves_db_failure_and_checks_reference_stability(self):
        args = (('123', b'args', b'1'), b'env', b'props', {}, {})
        result = type('Child', (), {'returncode': 1, 'stdout': SECRET.encode()})()
        space = type('Space', (), {'f_bavail': 10000, 'f_frsize': 4096})()
        def metadata(section, prefix, service):
            section['paths'][prefix + '.fragment'] = '/etc/systemd/system/' + service
        with patch.object(probe.os, 'geteuid', return_value=0, create=True), \
             patch.object(probe.os, 'statvfs', return_value=space, create=True), \
             patch.object(probe, 'jar_digest', return_value=probe.JAR_SHA), \
             patch.object(probe, 'database_inputs', return_value=args), \
             patch.object(probe, 'unchanged') as unchanged, \
             patch.object(probe, 'service_metadata', side_effect=metadata) as meta, \
             patch.object(probe.subprocess, 'run', return_value=result) as run:
            report = probe.observe({}, Path('/opt/jjikmuk-readiness-fixture'), 'a' * 64)
            self.assertFalse(report['checks']['deployment_ready'])
            self.assertFalse(report['checks']['db.read_succeeded'])
            self.assertNotIn(SECRET, json.dumps(report))
            self.assertEqual(4, meta.call_count)
            unchanged.assert_called_once_with(args)
            self.assertEqual(['/usr/sbin/runuser', '-u', 'ubuntu'], run.call_args.args[0][:3])
            self.assertEqual(report, safe_report(json.dumps(report)))
            counter = [0]
            def changed(section, prefix, service):
                metadata(section, prefix, service)
                counter[0] += 1
                if counter[0] > 2:
                    section['counts']['changed'] = 1
            meta.side_effect = changed
            with self.assertRaisesRegex(ValueError, 'SERVICE_REFERENCES_CHANGED'):
                probe.observe({}, Path('/opt/jjikmuk-readiness-fixture'), 'a' * 64)
            counter[0] = 0
            def restarted(section, prefix, service):
                metadata(section, prefix, service)
                counter[0] += 1
                return ('same_pid', 'new_start_time' if counter[0] > 2 else 'old_start_time')
            meta.side_effect = restarted
            with self.assertRaisesRegex(ValueError, 'SERVICE_REFERENCES_CHANGED'):
                probe.observe({}, Path('/opt/jjikmuk-readiness-fixture'), 'a' * 64)


if __name__ == '__main__':
    unittest.main()
