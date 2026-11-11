import contextlib,io,json,types,unittest
from unittest.mock import Mock,MagicMock,patch
from catalog_live_sql import classify,collect


class LiveSqlTests(unittest.TestCase):
    def test_statement_values_are_reduced_to_fixed_categories(self):
        self.assertEqual(classify("UPDATE products p JOIN jjikmuk_catalog_batch b ON p.product_id=b.product_id SET p.image_url='PRIVATE'"),'PRODUCT_UPDATE')
        self.assertEqual(classify('SELECT password FROM secret_accounts'),'OTHER')
        self.assertEqual(classify('SELECT product_name FROM products WHERE product_id>100 ORDER BY product_id LIMIT 500 FOR UPDATE'),'PRODUCT_SCAN')

    def test_five_small_metadata_observations_export_no_raw_statement(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        values=[]
        for i in range(5):values.extend([[{'TIME':i,'INFO':'PRIVATE SELECT'}],[{'Variable_name':'Innodb_data_reads','Value':str(10+i)}]])
        cur.fetchall.side_effect=values;sleep=Mock();result=collect(conn,sleep)
        self.assertEqual(result,{'samples_OTHER':5,'seconds_OTHER':4,'delta_Innodb_data_reads':4,'observations':5})
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertEqual(sleep.call_count,4)
        conn.rollback.assert_called_once();conn.commit.assert_not_called()
        for call in cur.execute.call_args_list:
            query=call.args[0]
            self.assertTrue(query.startswith(('SET TRANSACTION READ ONLY','SELECT TIME,INFO FROM information_schema.PROCESSLIST','SHOW GLOBAL STATUS')))
        self.assertEqual(cur.execute.call_count,11)

    def test_invalid_numeric_metadata_is_rejected(self):
        conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchall.return_value=[{'TIME':-1,'INFO':'COMMIT'}]
        with self.assertRaises(AssertionError):collect(conn,Mock())

    def test_document_rejects_another_active_run_and_script_compiles(self):
        import catalog_live_diagnostic as live
        from test_catalog_reapply import binding
        value=binding();value.update(run_id=live.RUN,commit=live.COMMIT)
        saved={'binding':value,'envelope':{'files':{'bin/catalog_host.py':{'bytes':1,'sha256':'a'*64}}}}
        digest=live.sha(live.canonical(saved))
        doc=live.document(saved,digest);command=doc['mainSteps'][0]['inputs']['runCommand'][0]
        compile(command.split('\n',1)[1].rsplit('\nJJIKMUK_LIVE_SQL',1)[0],'<fixed-read>','exec')
        self.assertEqual(doc['mainSteps'][0]['inputs']['timeoutSeconds'],'50')
        value['run_id']='987654321'
        with self.assertRaisesRegex(ValueError,'LIVE_DIAGNOSTIC_RECEIPT_CHANGED'):live.document(saved,digest)
        with self.assertRaisesRegex(ValueError,'LIVE_DIAGNOSTIC_BINDING'):live.document(saved,live.sha(live.canonical(saved)))

    def test_generated_script_emits_valid_json_for_success_and_failure(self):
        import catalog_live_diagnostic as live
        from test_catalog_reapply import binding
        from bootstrap import need
        value=binding();value.update(run_id=live.RUN,commit=live.COMMIT)
        saved={'binding':value,'envelope':{'files':{'bin/catalog_host.py':{'bytes':1,'sha256':'a'*64}}}}
        command=live.document(saved,live.sha(live.canonical(saved)))['mainSteps'][0]['inputs']['runCommand'][0]
        code=command.split('\n',1)[1].rsplit('\nJJIKMUK_LIVE_SQL',1)[0]
        original_flags=__import__('sys').flags
        flags=types.SimpleNamespace(**{k:getattr(original_flags,k) for k in dir(original_flags) if not k.startswith('_')})
        flags.isolated=True;flags.no_site=True
        for failed in (False,True):
            work=Mock();conn=MagicMock();work.return_value.connect.return_value=conn
            conn.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchall.return_value=[]
            if failed:work.return_value.connect.side_effect=RuntimeError('PRIVATE DETAILS')
            mods={'host':types.SimpleNamespace(secure=lambda p:None),
                  'manifest':types.SimpleNamespace(require=need,digest=lambda p:'a'*64),
                  'catalog_host':types.SimpleNamespace(Work=work)}
            output=io.StringIO()
            with patch.dict('sys.modules',mods),patch('sys.path',list(__import__('sys').path)),patch('sys.dont_write_bytecode',True),\
                 patch('sys.flags',flags),patch('os.geteuid',return_value=0,create=True),\
                 patch('pathlib.Path.stat',return_value=types.SimpleNamespace(st_size=1)),patch('signal.signal'),patch('signal.alarm',create=True),\
                 patch('signal.SIGALRM',14,create=True),patch('time.sleep'),contextlib.redirect_stdout(output):
                if failed:
                    with self.assertRaises(SystemExit):exec(code,{})
                else:exec(code,{})
            report=json.loads(output.getvalue());self.assertEqual(report['status'],'STOPPED' if failed else 'VERIFIED')
            self.assertNotIn('PRIVATE',output.getvalue())


if __name__=='__main__':unittest.main()
