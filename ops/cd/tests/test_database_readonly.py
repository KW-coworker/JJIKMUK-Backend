import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock,patch
from database_probe import probe,load_vendor


class DatabaseReadOnlyTests(unittest.TestCase):
    def test_tls_readonly_transaction_and_sql_limit(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'app.properties'
            p.write_text('spring.datasource.url=jdbc:mysql://fixed:3306/db\nspring.datasource.username=u\nspring.datasource.password=SENTINEL')
            mysql=MagicMock();conn=mysql.connect.return_value.__enter__.return_value
            cur=conn.cursor.return_value.__enter__.return_value
            cur.fetchmany.return_value=[('1','V1__test.sql',123,1,'SQL')]
            with patch.dict('sys.modules',{'pymysql':mysql}):
                result=probe({'database':{'properties_file':str(p),'expected_jdbc_url':'jdbc:mysql://fixed:3306/db','host':'fixed','name':'db','ca_file':'fixed-ca'}})
            sql=[c.args[0] for c in cur.execute.call_args_list]
            self.assertEqual(['SET SESSION MAX_EXECUTION_TIME=10000','START TRANSACTION READ ONLY'],sql[:2])
            self.assertTrue(sql[2].startswith('SELECT ') and sql[2].endswith('LIMIT 102'))
            self.assertTrue(mysql.connect.call_args.kwargs['ssl_verify_identity'])
            self.assertTrue(mysql.connect.call_args.kwargs['ssl_verify_cert'])
            conn.rollback.assert_called_once()
            self.assertNotIn('SENTINEL',str(result))

    def test_nonisolated_import_never_uses_other_pymysql(self):
        # Exercise a genuinely non-isolated child even if this suite itself uses -I -S.
        code = """import sys
sys.path.insert(0, sys.argv[1])
from database_probe import load_vendor
try:
    load_vendor()
except ValueError as error:
    assert str(error) == 'ISOLATED_PROBE_REQUIRED'
else:
    raise AssertionError('non-isolated import was accepted')
"""
        subprocess.run([sys.executable, '-B', '-c', code, str(Path(__file__).resolve().parents[1])],
                       check=True, capture_output=True, text=True, timeout=10)
