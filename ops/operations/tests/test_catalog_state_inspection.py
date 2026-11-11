import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import catalog_state_inspection as inspection
from bootstrap import need
from connection import canonical, sha


def helpers():
    tree = ast.parse(inspection.HOST_SCRIPT)
    selected = [node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.ClassDef))]
    namespace = {'re':re,'sqlite3':sqlite3,'json':json,'require':need,'closing':closing}
    exec(compile(ast.Module(body=selected,type_ignores=[]),'<inspection-helpers>','exec'),namespace)
    return namespace


class StateInspectionTests(unittest.TestCase):
    def test_digit_bearing_migration_states_are_preserved_without_free_text(self):
        code=helpers()['state_code']
        for value in ('V21_VERIFIED','V21_FLYWAY_INTENT','RECOVERY_INTENT'):
            self.assertEqual(code('STATE_',value),'STATE_'+value)
        for value in ('password=secret','V21\nSECRET','x','A'*51):
            with self.assertRaisesRegex(ValueError,'STATE_INSPECTION_STATUS'):code('STATE_',value)

    def test_changed_receipt_and_hold_never_send(self):
        with self.assertRaisesRegex(ValueError,'RECEIPT_CHANGED'):
            inspection.document({'binding':{},'envelope':{}})
        for request,run,state in [('b'*32,inspection.RUN,'WORKING'),(inspection.REQUEST,'1','WORKING'),(inspection.REQUEST,inspection.RUN,'OPEN')]:
            with patch.object(inspection,'Gate') as gate,patch.object(inspection,'execute') as execute:
                gate.return_value.read.return_value=({'request_id':request,'run_id':run,'state':state},'etag')
                with self.assertRaisesRegex(ValueError,'STATE_INSPECTION_'):
                    inspection.inspect({'s3':Mock()},{'request_id':request})
                execute.assert_not_called()

    def test_fixed_document_compiles_without_mutation_commands(self):
        saved={'binding':{'archive_sha256':'a'*64},'envelope':{'files':{}}}
        with patch.object(inspection,'RECEIPT_SHA',sha(canonical(saved))):document=inspection.document(saved)
        script=document['mainSteps'][0]['inputs']['runCommand'][0].split('\n',1)[1].rsplit('\n',1)[0]
        compile(script,'<fixed-state-read>','exec')
        for forbidden in ('host.commit(', 'work.recover(', "systemctl','start", "systemctl','stop", 'UPDATE ', 'KILL CONNECTION', "open('w'"):
            self.assertNotIn(forbidden,script)
        self.assertIn('flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)',script)
        self.assertNotIn("work.state['status'] ==",script)
        self.assertEqual(document['mainSteps'][0]['inputs']['timeoutSeconds'],'360')

    def test_journal_reads_actual_producer_states_without_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'before.sqlite';binding={'dataset':'synthetic'}
            with closing(sqlite3.connect(path)) as db:
                db.executescript('CREATE TABLE metadata(key TEXT,value TEXT); CREATE TABLE baseline(id INTEGER); CREATE TABLE changes(status TEXT);')
                db.execute('INSERT INTO metadata VALUES (?,?)',('binding',json.dumps(binding)))
                db.executemany('INSERT INTO baseline VALUES (?)',[(1,),(2,),(3,)])
                db.executemany('INSERT INTO changes VALUES (?)',[(s,) for s in ('PREPARED','COMMITTED','RESTORED_OR_NOT_COMMITTED')])
                db.commit()
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            counts,codes=helpers()['journal_counts'](path,binding)
            self.assertEqual(counts['journal_rows'],3)
            self.assertEqual(counts['journal_restored_or_not_committed'],1)
            self.assertEqual(counts['journal_readable'],1)
            self.assertEqual(codes,[])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            with self.assertRaisesRegex(ValueError,'JOURNAL_BINDING'):
                helpers()['journal_counts'](path,{'dataset':'wrong'})

    def test_hot_journal_is_not_opened_or_repaired(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'before.sqlite';path.write_bytes(b'not a database')
            sidecar=Path(str(path)+'-journal');sidecar.write_bytes(b'preserve')
            with patch.object(sqlite3,'connect') as connect:
                counts,codes=helpers()['journal_counts'](path,{})
                connect.assert_not_called()
            self.assertEqual(counts['journal_readable'],0)
            self.assertEqual(codes,['SQLITE_SIDECAR_PRESERVED'])
            self.assertEqual(sidecar.read_bytes(),b'preserve')

    def test_wal_header_is_not_opened_even_without_sidecars(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'before.sqlite'
            raw=bytearray(100);raw[:16]=b'SQLite format 3\x00';raw[18:20]=b'\x02\x02';path.write_bytes(raw)
            with patch.object(sqlite3,'connect') as connect:
                counts,codes=helpers()['journal_counts'](path,{})
                connect.assert_not_called()
            self.assertEqual(codes,['SQLITE_FORMAT_REVIEW_REQUIRED'])
            self.assertEqual(path.read_bytes(),raw)

    def test_log_export_is_only_fixed_categories(self):
        secret='password=SECRET_VALUE jdbc:mysql://private/customer@example.com'
        result=helpers()['log_codes'](secret+' SchemaManagementException: wrong column type APPLICATION FAILED TO START')
        self.assertEqual(result,['STARTUP_FAILED','JPA_SCHEMA_VALIDATION','COLUMN_TYPE_MISMATCH'])
        self.assertNotIn('SECRET',json.dumps(result))
        self.assertEqual(helpers()['log_codes'](secret),[])
        self.assertIn('RUNTIME_TIMEOUT',helpers()['log_codes']('Runtime time limit exceeded. Failed with result \'timeout\'.'))

    @unittest.skipUnless(os.name=='posix','Linux signal deadline')
    def test_deadline_cannot_be_swallowed_by_exception_handlers(self):
        tree=ast.parse(inspection.HOST_SCRIPT)
        nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in ('deadline','InspectionDeadline')]
        code='import signal,time\n'+ast.unparse(ast.Module(body=nodes,type_ignores=[]))+'''
signal.signal(signal.SIGALRM,deadline);signal.alarm(1)
try:
 while True:
  try:time.sleep(0.1)
  except Exception:pass
except InspectionDeadline:print('DEADLINE')
'''
        result=subprocess.run([sys.executable,'-I','-S','-B','-c',code],capture_output=True,text=True,timeout=5)
        self.assertEqual((result.returncode,result.stdout.strip()),(0,'DEADLINE'))


if __name__=='__main__':unittest.main()
