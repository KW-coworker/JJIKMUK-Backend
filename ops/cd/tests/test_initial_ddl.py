import unittest
from unittest.mock import MagicMock, patch
from initial_ddl import guarded_sql, settle_owned

SQL='OPTIMIZE TABLE products'


class InitialDdlTests(unittest.TestCase):
    def control(self, rows):
        connection=MagicMock()
        cursor=connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect=rows
        return MagicMock(return_value=connection),cursor

    def test_no_kill_for_unknown_session(self):
        open_control,cur=self.control([[(9,'another_database',SQL,1,'Query')]])
        with self.assertRaisesRegex(ValueError,'SESSION_UNCERTAIN'):
            settle_owned(open_control,9,SQL,MagicMock(),cancel=True)
        self.assertFalse(any(c.args[0].startswith('KILL') for c in cur.execute.call_args_list))

    def test_lost_cancel_response_is_not_repeated(self):
        open_control,cur=self.control([[(9,'jjikmuk',SQL,1,'Query')],[(9,'jjikmuk',SQL,1,'Query')],[]])
        def execute(sql,*args):
            if sql.startswith('KILL'):raise OSError('synthetic lost response')
        cur.execute.side_effect=execute
        with patch('initial_ddl.time.sleep'):
            settle_owned(open_control,9,SQL,MagicMock(),cancel=True)
        self.assertEqual(sum(c.args[0].startswith('KILL') for c in cur.execute.call_args_list),1)

    def test_worker_connection_failure_still_observes_owned_server_session(self):
        conn=MagicMock();conn.thread_id.return_value=9
        conn.cursor.return_value.__enter__.return_value.execute.side_effect=OSError('synthetic connection loss')
        open_control,cur=self.control([[(9,'jjikmuk',None,1,'Sleep')]])
        records=[]
        with self.assertRaisesRegex(ValueError,'DDL_STOPPED'):
            guarded_sql(conn,open_control,SQL,lambda:None,records.append)
        self.assertTrue(any(r['status']=='OWNED_QUERY_ENDED' for r in records))
        self.assertFalse(any(c.args[0].startswith('KILL') for c in cur.execute.call_args_list))

    def test_success_checks_server_and_optimize_result(self):
        conn=MagicMock();conn.thread_id.return_value=9
        conn.cursor.return_value.__enter__.return_value.fetchall.return_value=(('jjikmuk.products','optimize','status','OK'),)
        open_control,cur=self.control([[(9,'jjikmuk',None,1,'Sleep')]])
        guarded_sql(conn,open_control,SQL,lambda:None,MagicMock())
        cur.fetchall.assert_called_once()


if __name__ == '__main__':unittest.main()
