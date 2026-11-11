import ast
import copy
import hashlib
import json
import re
import unittest
from unittest.mock import MagicMock, patch
import catalog_preservation_read as read
from bootstrap import need


class PreservationReadTests(unittest.TestCase):
    def sample(self):
        return {'binding': {'run_id':read.RUN,'commit':read.COMMIT,'request_id':read.REQUEST,
                            'archive_sha256':'a'*64},'envelope':{'files':{}}}

    def test_document_is_fixed_to_one_receipt_and_compiles(self):
        saved=self.sample();digest=read.sha(read.canonical(saved))
        with patch.object(read,'RECEIPT',digest):
            doc=read.document(saved)
            changed=copy.deepcopy(saved);changed['binding']['commit']='b'*40
            with self.assertRaisesRegex(ValueError,'RECEIPT'):read.document(changed)
        command=doc['mainSteps'][0]['inputs']['runCommand'][0]
        compile(command.split('\n',1)[1].rsplit('\nJJIKMUK_PRESERVATION_READ',1)[0],'<probe>','exec')
        self.assertEqual(doc['parameters'],{})
        self.assertEqual(doc['mainSteps'][0]['inputs']['timeoutSeconds'],'120')

    def test_wrong_run_remains_rejected_even_with_matching_hash(self):
        saved=self.sample();saved['binding']['run_id']='123'
        with patch.object(read,'RECEIPT',read.sha(read.canonical(saved))),self.assertRaisesRegex(ValueError,'BINDING'):
            read.document(saved)

    def reader(self):
        tree=ast.parse(read.HOST_SCRIPT)
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='history_counts')
        env={'require':need}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'<read>','exec'),env)
        return env['history_counts']

    def test_coordinator_uses_host_phase_id_and_exact_freeze_state(self):
        function=next(n for n in ast.parse(read.HOST_SCRIPT).body if isinstance(n,ast.FunctionDef) and n.name=='expected_coordinator')
        env={'hashlib':hashlib,'json':json}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'<coordinator>','exec'),env)
        value=env['expected_coordinator'](self.sample()['binding'])
        self.assertEqual(value['operation_id'],'6830d6df296c92e9c8480208257b5a021541df4aa4431cd01705c5c431e881ab')
        self.assertNotEqual(value['operation_id'],read.RECOVERY)
        freeze={'status':'MUTATION_INTENT','component':'db','operation_id':hashlib.sha256((read.REQUEST+':'+read.RUN+':freeze').encode()).hexdigest()}
        self.assertEqual(value,{'status':'ROLLED_BACK','component':'db','operation_id':value['operation_id'],
                               'recovery_of':hashlib.sha256(json.dumps(freeze,sort_keys=True).encode()).hexdigest()})

    def test_read_is_bounded_to_saved_id_and_returns_only_aggregates(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value=(3000001,1,4000000)
        self.assertEqual(self.reader()(conn,4000000),(3000001,1,4000000))
        self.assertEqual([c.args for c in cur.execute.call_args_list],[
            ('SET SESSION MAX_EXECUTION_TIME=60000',),('START TRANSACTION READ ONLY',),
            ('SELECT COUNT(*),COALESCE(MIN(id),0),COALESCE(MAX(id),0) FROM product_attribute_snapshots FORCE INDEX (idx_attribute_product) WHERE id<=%s',(4000000,))])
        conn.rollback.assert_called_once();conn.commit.assert_not_called();conn.close.assert_not_called()

    def test_bad_counts_and_out_of_bound_ids_are_rejected(self):
        for result in [(-1,0,0),(1,0,1),(1,1,11),(True,1,1),(0,1,1)]:
            conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=result
            with self.subTest(result=result),self.assertRaisesRegex(ValueError,'COUNT'):self.reader()(conn,10)

    def test_empty_history_is_valid_and_invalid_bound_never_queries(self):
        conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=(0,0,0)
        self.assertEqual(self.reader()(conn,10),(0,0,0))
        conn.reset_mock()
        for bound in (0,-1,True,'10',2**63):
            with self.assertRaisesRegex(ValueError,'HISTORY_BOUND'):self.reader()(conn,bound)
        conn.cursor.assert_not_called()

    def test_failure_keeps_numeric_mysql_code_and_stage_but_never_message(self):
        function=next(n for n in ast.parse(read.HOST_SCRIPT).body if isinstance(n,ast.FunctionDef) and n.name=='error_codes')
        env={'require':need,'re':re}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'<errors>','exec'),env)
        Error=type('OperationalError',(Exception,),{'__module__':'pymysql.err'})
        result=env['error_codes'](Error(3024,'PRIVATE SQL PASSWORD'),'HISTORY_COUNT')
        self.assertEqual(result,['READ_STAGE_HISTORY_COUNT','OPERATIONALERROR','MYSQL_3024'])
        self.assertNotIn('PRIVATE',json.dumps(result))
        for args in [('PRIVATE',),(True,),(0,),(65536,)]:
            self.assertEqual(len(env['error_codes'](Error(*args),'CONNECT')),2)
        with self.assertRaisesRegex(ValueError,'ERROR_STAGE'):env['error_codes'](Error(3024),'PRIVATE')

    def test_changed_gate_or_recovery_prevents_ssm_execution(self):
        ctx={'request_id':read.REQUEST};api={'s3':MagicMock()}
        gate={'state':'WORKING','request_id':read.REQUEST,'run_id':read.RUN,'commit':read.COMMIT}
        for changed in (dict(gate,run_id='1'),dict(gate,state='OPEN')):
            with patch.object(read,'Gate') as gate_class,patch.object(read,'execute') as execute:
                gate_class.return_value.read.return_value=(changed,'etag')
                with self.assertRaisesRegex(ValueError,'GATE'):read.inspect(api,ctx)
                execute.assert_not_called()
        with patch.object(read,'Gate') as gate_class,patch.object(read,'read_object',return_value={}),patch.object(read,'execute') as execute:
            gate_class.return_value.read.return_value=(gate,'etag')
            with self.assertRaisesRegex(ValueError,'RECOVERY'):read.inspect(api,ctx)
            execute.assert_not_called()


if __name__=='__main__':unittest.main()
