import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock

import backend_schema_detail as detail
import backend_schema_detail_document as builder
from readiness_document import contract
from run import safe_report

ROOT = Path(__file__).resolve().parents[3]


class SchemaDetailTests(unittest.TestCase):
    def setUp(self):
        self.contract = contract(ROOT)
        self.history = [(m['version'], m['script'], m['checksum'], 1, 'SQL')
                        for m in self.contract['migrations'] if int(m['version']) <= 17]
        self.columns = [('users', 'id', 1, 'bigint', 'NO', None),
                        ('flyway_schema_history', 'version', 1, 'varchar(50)', 'YES', 50)]

    def report(self, columns=None, history=None):
        return detail.summarize(self.columns if columns is None else columns, [],
                                self.history if history is None else history, self.contract)

    def test_exact_unapplied_shape_and_safe_output(self):
        result = self.report()
        self.assertTrue(result['checks']['exact_unapplied_v18_v19_v20_shape'])
        self.assertFalse(result['checks']['deployment_ready'])
        self.assertEqual(result, safe_report(json.dumps(result)))
        self.assertEqual(1, result['counts']['v19.required_columns_missing'])

    def test_partial_apply_never_reported_as_clean_unapplied(self):
        for table in detail.TABLES:
            result = self.report(self.columns + [(table, 'id', 1, 'bigint', 'NO', None)])
            self.assertFalse(result['checks']['exact_unapplied_v18_v19_v20_shape'])
        self.assertFalse(self.report(self.columns + [('users', 'profile_version', 2, 'bigint', 'NO', None)])['checks']['exact_unapplied_v18_v19_v20_shape'])

    def test_history_failure_duplicate_changed_checksum_or_missing_is_rejected(self):
        first = self.history[0]
        for history in (self.history[:-1], self.history + [first],
                        [(first[0], first[1], first[2] + 1, 1, 'SQL')] + self.history[1:],
                        [(first[0], first[1], first[2], 0, 'SQL')] + self.history[1:]):
            self.assertFalse(self.report(history=history)['checks']['exact_unapplied_v18_v19_v20_shape'])

    def test_missing_version_script_and_checksum_differences_are_separated(self):
        first = self.history[0]
        missing = self.report(history=self.history[1:])
        self.assertFalse(missing['checks']['v' + first[0] + '.history_present'])
        changed = self.report(history=[(first[0], 'different.sql', first[2], 1, 'SQL')] + self.history[1:])
        self.assertTrue(changed['checks']['v' + first[0] + '.history_present'])
        self.assertFalse(changed['checks']['v' + first[0] + '.script_matches'])
        self.assertTrue(changed['checks']['v' + first[0] + '.checksum_matches'])
        changed = self.report(history=[(first[0], first[1], first[2] + 1, 1, 'SQL')] + self.history[1:])
        self.assertTrue(changed['checks']['v' + first[0] + '.script_matches'])
        self.assertFalse(changed['checks']['v' + first[0] + '.checksum_matches'])
        self.assertEqual((first[2] + 1) & 0xffffffff, changed['counts']['v' + first[0] + '.checksum_u32'])
        self.assertEqual(detail.digest(first[1].encode()), changed['hashes']['v' + first[0] + '.script'])
        self.assertEqual(changed, safe_report(json.dumps(changed)))

    def test_unknown_history_and_v17_schema_are_reported_without_row_values(self):
        result = self.report(self.columns + [('products', 'nutrition_basis_raw', 1, 'varchar(255)', 'YES', 255)],
                             self.history + [('123', 'SYNTHETIC_PRIVATE_SCRIPT', 99, 1, 'SQL')])
        self.assertEqual(1, result['counts']['history_unknown_versions'])
        self.assertTrue(result['checks']['products.nutrition_basis_raw_present'])
        self.assertFalse(result['checks']['products_staging.present'])
        self.assertNotIn('SYNTHETIC_PRIVATE_SCRIPT', json.dumps(result))
        self.assertEqual(result, safe_report(json.dumps(result)))

    def test_signed_history_checksum_is_bounded_unsigned_metadata(self):
        first = self.history[0]
        result = self.report(history=[(first[0], first[1], -1, 1, 'SQL')] + self.history[1:])
        self.assertEqual(4294967295, result['counts']['v' + first[0] + '.checksum_u32'])
        self.assertEqual(result, safe_report(json.dumps(result)))
        with self.assertRaisesRegex(ValueError, 'HISTORY_CHECKSUM_RANGE'):
            self.report(history=[(first[0], first[1], 2**31, 1, 'SQL')] + self.history[1:])

    def test_metadata_limits_and_no_unknown_contract(self):
        with self.assertRaises(ValueError): self.report(self.columns * 2049)
        bad = dict(self.contract, migrations=self.contract['migrations'][:-1])
        with self.assertRaises(ValueError): detail.summarize(self.columns, [], self.history, bad)

    def test_at_most_one_successful_version_zero_baseline_is_allowed(self):
        baseline = ('0', 'baseline', None, 1, 'BASELINE')
        self.assertTrue(self.report(history=[baseline] + self.history)['checks']['history_valid'])
        self.assertFalse(self.report(history=[baseline, baseline] + self.history)['checks']['history_valid'])
        self.assertFalse(self.report(history=[('1', 'baseline', None, 1, 'BASELINE')] + self.history)['checks']['history_valid'])

    def test_query_uses_one_verified_tls_readonly_connection_and_rolls_back(self):
        connect = MagicMock(); conn = connect.return_value.__enter__.return_value
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchmany.side_effect = [self.columns, [], self.history]
        output = detail.query(connect, {'spring.datasource.username': 'synthetic',
                              'spring.datasource.password': 'NEVER_EXPORT_SYNTHETIC'}, self.contract)
        connect.assert_called_once()
        self.assertTrue(connect.call_args.kwargs['ssl_verify_identity'])
        self.assertTrue(connect.call_args.kwargs['ssl_verify_cert'])
        self.assertFalse(connect.call_args.kwargs['local_infile'])
        self.assertIn('START TRANSACTION READ ONLY', [c.args[0] for c in cur.execute.call_args_list])
        self.assertTrue(all(c.args[0].startswith(('SET SESSION ', 'START TRANSACTION READ ONLY', 'SELECT ')) for c in cur.execute.call_args_list))
        conn.rollback.assert_called_once()
        self.assertNotIn('NEVER_EXPORT_SYNTHETIC', json.dumps(output))

    def test_failure_rolls_back_and_does_not_retry(self):
        connect = MagicMock(); conn = connect.return_value.__enter__.return_value
        conn.cursor.return_value.__enter__.return_value.execute.side_effect = RuntimeError('synthetic failure')
        with self.assertRaises(RuntimeError): detail.query(connect, {'spring.datasource.username':'x', 'spring.datasource.password':'y'}, self.contract)
        connect.assert_called_once(); conn.rollback.assert_called_once()

    def test_document_is_fixed_approved_under_broad_scope_and_does_not_stage_files(self):
        plan = builder.plan(ROOT)
        self.assertTrue(plan['approved'])
        self.assertEqual('USER_BACKEND_CD_COMPLETION_20261110', plan['approval_id'])
        self.assertEqual({}, plan['document']['parameters'])
        self.assertLess(len(builder.canonical(plan['document'])), 60000)
        self.assertEqual(builder.canonical(plan) + b'\n',
                         (ROOT / 'ops/operations/plans' / builder.PLAN_NAME).read_bytes())
        script = plan['document']['mainSteps'][0]['inputs']['runCommand'][0]
        self.assertNotIn('mkdir(', script)
        self.assertNotIn('urlopen(', script)
        compile(script.split('\n', 1)[1].rsplit('\n', 1)[0], '<fixed-schema-document>', 'exec')


if __name__ == '__main__': unittest.main()
