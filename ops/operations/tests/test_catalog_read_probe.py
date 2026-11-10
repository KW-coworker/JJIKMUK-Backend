import ast
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from catalog_read_probe import compare_connection, product_query, retire, query_columns, PROVENANCE_COLUMNS, FieldSummary, field_differences
from catalog_read_document import document, LAUNCHER

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'cd'))
import test_catalog_compare as fixtures
from catalog_compare import Comparison
COLUMNS = fixtures.COLUMNS
row = fixtures.row


class Cursor:
    def __init__(self,conn,stream=False):
        self.connection=conn;self.owner=conn;self.stream=stream;self.rows=[];self.closed=False
        self._result=type('Result',(),{'unbuffered_active':True})()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def execute(self,sql,parameters=None):
        self.owner.queries.append(sql)
        if sql.startswith('SELECT DATABASE'):
            self.rows=[('jjikmuk','8.4.11',self.owner.readonly,'REPEATABLE-READ')]
        elif 'FROM flyway_schema_history' in sql:
            self.rows=[('1','V1.sql',123,1,'SQL')]
        elif 'FROM information_schema.STATISTICS' in sql:
            self.rows=[('PRIMARY','BTREE',1,'barcode'),('ft','FULLTEXT',1,'raw_materials')]
        elif 'FROM information_schema.COLUMNS' in sql:
            self.rows=list(COLUMNS)+list(self.owner.extra_columns.items())
        elif 'FROM `products`' in sql:
            self.rows=[tuple(self.owner.product[n] for n,_ in COLUMNS)+(self.owner.product.get('ingested_content_revision_sha256'),)]
    def fetchone(self):return self.rows.pop(0)
    def fetchmany(self,n):
        if self.stream and self.owner.fail_stream:raise TimeoutError('synthetic')
        result=self.rows[:n];self.rows=self.rows[n:];return result
    def close(self):self.closed=True


class Connection:
    def __init__(self):
        self.queries=[];self.closed=False;self.rolled_back=False;self.readonly=1
        self.product=row(image_url=None,nutrition_basis_raw=None);self.fail_stream=False
        self.stream=None
        self.extra_columns=dict(PROVENANCE_COLUMNS)
    def cursor(self,kind=None):
        c=Cursor(self,kind is not None)
        if kind is not None:self.stream=c
        return c
    def close(self):self.closed=True
    def rollback(self):self.rolled_back=True


class ReadProbeTest(unittest.TestCase):
    setUp = fixtures.CatalogComparisonTest.setUp
    tearDown = fixtures.CatalogComparisonTest.tearDown
    sidecar = fixtures.CatalogComparisonTest.sidecar
    def probe(self,conn):
        path,_=self.sidecar([row()]);c=Comparison(path)
        try:return compare_connection(conn,c,object,[{'version':'1','script':'V1.sql','checksum':123}])
        finally:c.close()

    def test_readonly_snapshot_and_only_product_or_schema_queries(self):
        conn=Connection();result=self.probe(conn)
        self.assertEqual(result['counts']['db_writes'],0)
        self.assertEqual(result['counts']['image_fill_category_candidate'],1)
        self.assertTrue(conn.rolled_back and conn.closed)
        self.assertTrue(all(q.startswith(('SET SESSION ','START TRANSACTION ','SELECT ')) for q in conn.queries))
        self.assertIn('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY',conn.queries)
        self.assertNotIn('DO_NOT_EXPORT',json.dumps(result))

    def test_writable_transaction_rejected_before_product_read(self):
        conn=Connection();conn.readonly=0
        with self.assertRaisesRegex(ValueError,'READONLY_DATABASE_IDENTITY'):self.probe(conn)
        self.assertFalse(any('FROM `products`' in q for q in conn.queries))
        self.assertTrue(conn.closed)

    def test_stream_timeout_closes_without_drain(self):
        conn=Connection();conn.fail_stream=True
        with self.assertRaises(TimeoutError):self.probe(conn)
        self.assertTrue(conn.closed)
        self.assertFalse(conn.stream.closed)
        self.assertIsNone(conn.stream.connection)
        self.assertFalse(conn.stream._result.unbuffered_active)

    def test_schema_change_stops_before_comparison(self):
        conn=Connection()
        with patch('catalog_read_probe.query_columns',side_effect=ValueError('PRODUCT_SCHEMA_CHANGED')):
            with self.assertRaisesRegex(ValueError,'PRODUCT_SCHEMA_CHANGED'):self.probe(conn)
        self.assertIsNone(conn.stream)

    def test_observed_provenance_columns_are_preserved_and_binding_counted(self):
        conn=Connection();conn.product['ingested_content_revision_sha256']='f'*64
        result=self.probe(conn)
        self.assertEqual(result['counts']['recognized_ai_columns'],10)
        self.assertEqual(result['counts']['existing_ingestion_binding_rows'],1)
        self.assertEqual(result['counts']['basis_fill_with_ingestion_binding'],1)
        self.assertEqual(result['counts']['image_fill_with_ingestion_binding'],1)
        self.assertNotIn('f'*64,json.dumps(result))

    def test_unknown_missing_and_changed_provenance_are_rejected(self):
        for kind in ('unknown','missing','type'):
            conn=Connection()
            if kind=='unknown':conn.extra_columns['unexpected']='text'
            elif kind=='missing':del conn.extra_columns['label_source_id']
            else:conn.extra_columns['label_source_id']='text'
            with self.assertRaises(ValueError):query_columns(conn,COLUMNS)

    def test_field_summaries_identify_changed_field_without_values(self):
        columns=[('barcode','varchar(255)'),('product_id','bigint'),('name','text'),('flag','bit(1)')]
        a={'barcode':'sample','product_id':1,'name':'PRIVATE_TEXT','flag':1}
        left=FieldSummary(columns);left.consume(a)
        right=FieldSummary(columns);right.consume(dict(a,name='CHANGED',flag=b'\x01'))
        self.assertEqual(field_differences(left.finish(),right.finish()),['name'])
        self.assertNotIn('PRIVATE_TEXT',json.dumps(left.finish()))
        self.assertNotIn('sample',json.dumps(left.finish()))

    def test_field_hashes_are_never_compared_when_key_order_differs(self):
        columns=[('barcode','text'),('product_id','bigint'),('name','text')]
        a={'barcode':'a','product_id':1,'name':'x'};b={'barcode':'b','product_id':2,'name':'y'}
        left=FieldSummary(columns);right=FieldSummary(columns)
        for row in (a,b):left.consume(row)
        for row in (b,a):right.consume(row)
        with self.assertRaisesRegex(ValueError,'KEYS_OR_ORDER_CHANGED'):field_differences(left.finish(),right.finish())

    def test_field_summary_mode_is_readonly_and_not_an_update_candidate_report(self):
        path,_=self.sidecar([row()]);c=Comparison(path);conn=Connection()
        try:r=compare_connection(conn,c,object,[{'version':'1','script':'V1.sql','checksum':123}],fields_only=True)
        finally:c.close()
        self.assertEqual(r['counts']['operating_rows'],1)
        self.assertNotIn('basis_fill_candidate',r['counts'])
        self.assertNotIn('basis_fill_with_ingestion_binding',r['counts'])
        self.assertTrue(r['checks']['per_column_fingerprints_only'])
        self.assertTrue(conn.closed and conn.rolled_back)

    def test_identifier_injection_is_rejected(self):
        with self.assertRaises(ValueError):product_query(['barcode` FROM users;--'])

    def test_document_is_fixed_and_syntactically_valid(self):
        binding={'key':'operations/private/'+'a'*32+'/'+'b'*64+'.zip',
                 'version':'fixture-version','bytes':1024,'sha256':'b'*64,'source_sha256':'c'*64}
        doc=document(binding)
        self.assertEqual(doc['parameters'],{})
        self.assertLess(len(json.dumps(doc)),60000)
        compile('BINDING='+repr(binding)+'\n'+LAUNCHER,'fixed-launcher','exec')
        for changed in [dict(binding,version='null'),dict(binding,key='wrong'),dict(binding,bytes=0)]:
            with self.assertRaises(ValueError):document(changed)

    def test_launcher_never_imports_missing_installed_run_module(self):
        tree=ast.parse(LAUNCHER)
        imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
        self.assertNotIn('run',imports)
        self.assertIn('host',imports)
        self.assertNotIn('systemctl restart',LAUNCHER)

    def test_document_binds_reviewed_probe_and_uses_distinct_stage(self):
        binding={'key':'operations/private/'+'a'*32+'/'+'b'*64+'.zip',
                 'version':'fixture-version','bytes':1024,'sha256':'b'*64,'source_sha256':'c'*64}
        command=document(binding)['mainSteps'][0]['inputs']['runCommand'][0]
        tree=ast.parse('\n'.join(command.splitlines()[1:-1]))
        values={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body[:4]}
        self.assertNotEqual(values['STAGE_ID'],binding['sha256'][:20])
        self.assertEqual(hashlib.sha256(values['REVIEWED_PROBE'].encode()).hexdigest(),values['REVIEWED_PROBE_SHA'])
        self.assertIn('PROVENANCE_COLUMNS',values['REVIEWED_PROBE'])
        self.assertIn("stage/'catalog_read_probe_reviewed.py'",LAUNCHER)
        self.assertIn('str(probe_path)',LAUNCHER)

    def test_launcher_rejects_untrusted_diagnostic_text(self):
        # Extract just the pure validators, never execute the root launcher.
        tree=ast.parse(LAUNCHER)
        definitions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('need','safe_report')]
        namespace={'json':json,'re':__import__('re')}
        exec(compile(ast.Module(body=definitions,type_ignores=[]),'validators','exec'),namespace)
        validate=namespace['safe_report']
        self.assertEqual(validate('{"status":"STOPPED","codes":["SOURCE_HASH"]}')['codes'],['SOURCE_HASH'])
        for value in ({'status':'STOPPED','codes':['password=secret']},
                      {'status':'anything'}, {'status':'VERIFIED','counts':{'bad':-1}}):
            with self.assertRaises(ValueError):validate(json.dumps(value))


if __name__=='__main__':unittest.main()
