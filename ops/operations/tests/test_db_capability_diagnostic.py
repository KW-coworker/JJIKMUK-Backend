import ast,json,unittest
from pathlib import Path
from db_capability_diagnostic import summarize
from run import safe_report


class CapabilityTests(unittest.TestCase):
    def test_schema_privileges_do_not_falsely_become_global(self):
        r=summarize(['GRANT PROCESS ON *.* TO `private-user`@`private-host`',
            'GRANT SELECT, TRIGGER, EVENT ON `jjikmuk`.* TO `private-user`@`private-host`'],'NONE','OFF')
        c=r['checks'];self.assertTrue(c['global_process']);self.assertFalse(c['global_trigger'])
        self.assertTrue(c['schema_trigger'] and c['schema_event'] and c['event_scheduler_off'])
        self.assertNotIn('private-',json.dumps(r));self.assertNotIn('SELECT',json.dumps(r))
        self.assertEqual(safe_report(json.dumps(r)),r)

    def test_revokes_and_active_scheduler_remain_visible(self):
        r=summarize(['GRANT ALL PRIVILEGES ON *.* TO `private-user`@`private-host`',
            'REVOKE EVENT ON `jjikmuk`.* FROM `private-user`@`private-host`'],'`rds_superuser_role`@`%`','ON')
        self.assertTrue(r['checks']['partial_revoke_present'] and r['checks']['role_known_rds'])
        self.assertFalse(r['checks']['event_scheduler_off'])

    def test_fixed_plan_executes_only_three_read_queries(self):
        root=Path(__file__).resolve().parents[3]
        plan=json.loads((root/'ops/operations/plans/db-observation-capabilities.json').read_bytes())
        self.assertEqual(plan['document']['parameters'],{})
        shell=plan['document']['mainSteps'][0]['inputs']['runCommand'][0]
        source=shell.split("<<'FIXED_CAPABILITIES'\n",1)[1].rsplit('\nFIXED_CAPABILITIES',1)[0]
        tree=ast.parse(source);compile(tree,'fixed-diagnostic','exec')
        queries=[node.args[0] for node in ast.walk(tree) if isinstance(node,ast.Call)
                 and isinstance(node.func,ast.Attribute) and node.func.attr=='execute']
        self.assertEqual(len(queries),3)
        text=[n.value for q in queries for n in ast.walk(q) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
        self.assertEqual(set(text),{'SELECT CURRENT_ROLE()','NONE','SHOW GRANTS FOR CURRENT_USER',
            'SHOW GRANTS FOR CURRENT_USER USING `rds_superuser_role`@`%`','SELECT @@GLOBAL.event_scheduler'})
        embedded=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='summarize')
        original=ast.parse((root/'ops/operations/db_capability_diagnostic.py').read_text()).body[-1]
        self.assertEqual(ast.dump(embedded),ast.dump(original))


if __name__=='__main__':unittest.main()
