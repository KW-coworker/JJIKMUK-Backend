import json
from pathlib import Path
import unittest
from v17_compatibility import summarize
from v17_compatibility_document import plan
from run import safe_report


class V17CompatibilityTests(unittest.TestCase):
    def fixture(self, *, fulltext=False, parent_type='bigint', parent_key=True):
        tables = [[t, 'InnoDB', 'Dynamic'] for t in ('products', 'products_rollback', 'users', 'family_profiles')]
        columns = [[t, 'id', parent_type, 'NO'] for t in ('users', 'family_profiles')]
        indexes = [[t, 'PRIMARY', 0, 1, 'id', None, 'BTREE'] for t in ('users', 'family_profiles')] if parent_key else []
        if fulltext: indexes.append(['products', 'ft_products_search_keywords', 1, 1, 'search_keywords', None, 'FULLTEXT'])
        return summarize('8.4.11', tables, columns, indexes)

    def test_fulltext_blocks_unchanged_instant_sql(self):
        self.assertFalse(self.fixture()['checks']['v17_blocked_by_existing_structure'])
        report = self.fixture(fulltext=True)
        self.assertTrue(report['checks']['products.fulltext_present'])
        self.assertTrue(report['checks']['v17_blocked_by_existing_structure'])
        self.assertEqual(report, safe_report(json.dumps(report)))

    def test_missing_or_incompatible_parent_key_is_reported(self):
        self.assertTrue(self.fixture()['checks']['users.fk_parent_compatible'])
        self.assertFalse(self.fixture(parent_type='bigint unsigned')['checks']['users.fk_parent_compatible'])
        self.assertFalse(self.fixture(parent_type='varchar(20)')['checks']['users.fk_parent_compatible'])
        self.assertFalse(self.fixture(parent_key=False)['checks']['users.fk_parent_compatible'])

    def test_metadata_limits_and_version_are_checked(self):
        with self.assertRaises(ValueError): summarize('not a version', [], [], [])
        with self.assertRaises(ValueError): summarize('8.4.11', [], [], [[]] * 257)

    def test_fixed_read_document_has_no_install_or_mutation_commands(self):
        value = plan(Path(__file__).resolve().parents[3])
        self.assertEqual({}, value['document']['parameters'])
        self.assertLess(len(json.dumps(value).encode()), 60000)
        self.assertNotIn('downloadContent', json.dumps(value))


if __name__ == '__main__': unittest.main()
