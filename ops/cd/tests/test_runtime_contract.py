import unittest
from runtime_contract import validate_overrides


class RuntimeContractTests(unittest.TestCase):
    def test_mail_preserved_and_both_observed_flyway_modes_supported(self):
        for state in (True,False):
            env={'SPRING_MAIL_PASSWORD':'SENTINEL_SECRET','SPRING_MAIL_USERNAME':'mail',
                 'SPRING_FLYWAY_ENABLED':str(state).lower(),'SPRING_SQL_INIT_MODE':'never'}
            before=env.copy()
            result=validate_overrides(env,{},dict(flyway_enabled=state,sql_init_mode='never'))
            self.assertNotIn('SENTINEL_SECRET',str(result))
            self.assertEqual(before,env)

    def test_unknown_alias_ddl_and_sql_are_not_blanket_allowed(self):
        expected=dict(flyway_enabled=True,sql_init_mode='never')
        for change in ({'SPRING_DATASOURCE_URL':'wrong'}, {'spring.flyway.enabled':'false'},
                       {'SPRING_SQL_INIT_MODE':'always'}, {'SPRING_FLYWAY_ENABLED':'false'},
                       {'SPRING_CONFIG_IMPORT':'optional:remote'}, {'SPRING_JPA_HIBERNATE_DDL_AUTO':'create'},
                       {'SPRING_JPA_HIBERNATE_DDL_AUTO':'validate','SPRING_JPA_HIBERNATE_DDLAUTO':'validate'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_overrides({'SPRING_SQL_INIT_MODE':'never',**change},{},expected)

    def test_unobserved_contract_or_absent_sql_override_stops(self):
        for expected in (None,{},dict(flyway_enabled='REQUIRES_OBSERVATION',sql_init_mode='never')):
            with self.assertRaisesRegex(ValueError,'UNREVIEWED_RUNTIME_CONTRACT'):
                validate_overrides({}, {}, expected)
        with self.assertRaisesRegex(ValueError,'SQL_INITIALIZATION_NOT_DISABLED'):
            validate_overrides({}, {},dict(flyway_enabled=True,sql_init_mode='never'))
