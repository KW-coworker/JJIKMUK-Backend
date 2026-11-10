import json
from pathlib import Path
import unittest
from fulltext_precheck import summarize, PRIVILEGES
from fulltext_precheck_document import plan
from run import safe_report


class FulltextPrecheckTests(unittest.TestCase):
    def fixture(self, grant='GRANT ALL PRIVILEGES ON `jjikmuk`.* TO `fixture`@`%`', parser='ngram'):
        ddl = 'CREATE TABLE products (\n FULLTEXT KEY `ft_products_search_keywords` (`search_keywords`) /*!50100 WITH PARSER `' + parser + '` */\n) ENGINE=InnoDB'
        return summarize(ddl, [('ft_products_search_keywords', 1, 'search_keywords', 'FULLTEXT')],
                         (2, 1, '8.4.11', 0), [('products', 100, 30, 9999999, 7)], [(grant,)], 2)

    def test_exact_ngram_and_privileges(self):
        report = self.fixture()
        self.assertTrue(all(report['checks'].values()))
        self.assertEqual(report, safe_report(json.dumps(report)))
        self.assertEqual(report['counts']['schema_data_index_bytes'], 130)
        self.assertIn('DATA_FREE_IS_NOT_RDS_FREE_STORAGE', report['codes'])
        self.assertNotIn('fixture', json.dumps(report))
        self.assertNotIn('GRANT ', json.dumps(report))

    def test_missing_privileges_or_wrong_schema_cannot_pass(self):
        for grant in ('GRANT SELECT ON `jjikmuk`.* TO `x`@`%`',
                      'GRANT ALL PRIVILEGES ON `another`.* TO `x`@`%`',
                      'GRANT `rds_superuser_role`@`%` TO `x`@`%`'):
            self.assertFalse(self.fixture(grant)['checks']['all_required_direct_schema_privileges'])
        for missing in PRIVILEGES:
            grant = 'GRANT ' + ', '.join(p for p in PRIVILEGES if p != missing) + ' ON *.* TO `x`@`%`'
            self.assertFalse(self.fixture(grant)['checks']['all_required_direct_schema_privileges'])

    def test_different_parser_is_rejected(self):
        self.assertFalse(self.fixture(parser='mecab')['checks']['fulltext_exact_ngram_definition'])

    def test_partial_revoke_cannot_be_hidden_by_global_grant(self):
        report = summarize('CREATE TABLE products ()', [], (2, 1, '8.4.11', 0), [],
                           [('GRANT ALL PRIVILEGES ON *.* TO `x`@`%`',),
                            ('REVOKE ALTER ON `jjikmuk`.* FROM `x`@`%`',)], 0)
        self.assertFalse(report['checks']['no_partial_revoke_observed'])
        self.assertFalse(report['checks']['all_required_direct_schema_privileges'])
        self.assertFalse(report['checks']['privilege_alter'])

    def test_fixed_command_limits_and_no_mutating_sql(self):
        root = Path(__file__).resolve().parents[3]
        value = plan(root)
        self.assertEqual(value['operation'], 'inspect')
        self.assertEqual({}, value['document']['parameters'])
        self.assertLess(len(json.dumps(value).encode()), 60000)
        source = (root / 'ops/operations/fulltext_precheck.py').read_text()
        for command in ('cur.execute(\'ALTER ', 'cur.execute(\'DROP ', 'cur.execute(\'OPTIMIZE ', 'cur.execute(\'INSERT '):
            self.assertNotIn(command, source)


if __name__ == '__main__': unittest.main()
