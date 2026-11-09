import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import jdbc_diagnostic as diag
import jdbc_diagnostic_document as builder
from run import safe_report, operation_succeeded

ROOT = Path(__file__).resolve().parents[3]
SECRET = 'SYNTHETIC_PRIVATE_VALUE_391'


class JdbcDiagnosticTests(unittest.TestCase):
    def url(self, pairs):
        return 'jdbc:mysql://' + diag.probe.DB_HOST + ':3306/jjikmuk?' + urlencode(pairs)

    def test_names_and_duplicates_are_observed_without_exporting_values(self):
        url = self.url([('sslMode', SECRET), ('createDatabaseIfNotExist', SECRET),
                        ('sslMode', SECRET), ('SSLMODE', SECRET),
                        ('trustCertificateKeyStorePassword', SECRET)])
        report = diag.option_report(url)
        self.assertEqual(2, report['counts']['jdbc.option.sslMode'])
        self.assertEqual(1, report['counts']['duplicate_option_names'])
        self.assertEqual(1, report['counts']['case_variant_names'])
        self.assertEqual(0, report['counts']['database_connections'])
        self.assertFalse(report['checks']['deployment_ready'])
        self.assertNotIn(SECRET, json.dumps(report))
        self.assertNotIn('jdbc:mysql:', json.dumps(report))
        self.assertEqual(report, safe_report(json.dumps(report)))

    def test_other_db_target_is_rejected_without_reporting_it(self):
        url = self.url([('sslMode', 'VERIFY_IDENTITY')])
        for changed in (url.replace(diag.probe.DB_HOST, 'other.invalid'),
                        url.replace('/jjikmuk?', '/other?'), url.replace(':3306', ':3307')):
            with self.assertRaisesRegex(ValueError, '^DATABASE_TARGET_REJECTED$'):
                diag.option_report(changed)

    def test_bad_names_and_limits_do_not_open_general_output_channel(self):
        report = diag.option_report(self.url([('bad\nname', SECRET), ('../file', SECRET)]))
        self.assertEqual(2, report['counts']['invalid_option_names'])
        self.assertFalse(report['checks']['option_names_complete'])
        self.assertNotIn('bad', json.dumps(report))
        bounded = diag.option_report(self.url([('a' + str(i), SECRET) for i in range(64)]))
        self.assertEqual(bounded, safe_report(json.dumps(bounded)))
        with self.assertRaises(ValueError):
            diag.option_report(self.url([('a' + str(i), SECRET) for i in range(65)]))

    def test_observation_checks_identity_and_never_uses_database_helpers(self):
        raw = ('spring.datasource.url=' + self.url([('createDatabaseIfNotExist', SECRET)])).encode()
        with patch.object(diag.os, 'geteuid', return_value=0, create=True), \
             patch.object(diag.probe, 'jar_digest', return_value=diag.probe.JAR_SHA), \
             patch.object(diag.probe, 'backend_identity', return_value=('123', b'args', b'1')) as identity, \
             patch.object(diag.probe, 'environment', return_value=(b'secret-env', {})), \
             patch.object(diag.probe, 'read', return_value=raw), \
             patch.object(diag.probe, 'database_inputs', side_effect=AssertionError('no DB path')), \
             patch.object(diag.probe, 'query_schema', side_effect=AssertionError('no SQL')), \
             patch.object(diag.probe.subprocess, 'run', side_effect=AssertionError('no extra process')):
            self.assertTrue(diag.observe()['checks']['observation_stable'])
            identity.side_effect = [('123', b'args', b'1'), ('123', b'args', b'2')]
            with self.assertRaisesRegex(ValueError, 'INPUTS_CHANGED_DURING_OBSERVATION'):
                diag.observe()

    def test_exception_details_are_withheld(self):
        output = io.StringIO()
        with patch.object(diag, 'observe', side_effect=RuntimeError(SECRET)), contextlib.redirect_stdout(output):
            diag.main()
        self.assertNotIn(SECRET, output.getvalue())
        report = safe_report(output.getvalue())
        self.assertFalse(operation_succeeded({'status': 'Success', 'response_code': 0, 'report': report}))

    def test_new_plan_is_pending_and_bounded(self):
        expected = builder.plan(ROOT)
        path = ROOT / 'ops/operations/plans' / builder.PLAN_NAME
        builder.verify_record(json.loads(path.read_bytes()), expected)
        self.assertFalse(expected['approved'])
        self.assertEqual({}, expected['document']['parameters'])
        self.assertLess(len(builder.canonical(expected['document'])), 60000)
        command = expected['document']['mainSteps'][0]['inputs']['runCommand'][0]
        source = command.split('\n', 1)[1].rsplit('\nJJIKMUK_JDBC_NAMES', 1)[0]
        compile(source, '<diagnostic-loader>', 'exec')


if __name__ == '__main__':
    unittest.main()
