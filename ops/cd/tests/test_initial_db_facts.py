import copy
import unittest
from unittest.mock import MagicMock,patch
from initial_db_facts import verify_logical, history_bound, project_idle,project_events_clear,require_observation_privileges


class InitialDbFactsTests(unittest.TestCase):
    def test_original_collation_comment_counter_and_column_attributes_preserved(self):
        before={'tables':[['products','utf8mb4_unicode_ci','dataset-marker','',90]],
                'columns':[['products','name','utf8mb4','utf8mb4_unicode_ci','','original']],
                'triggers_sha256':'a'*64}
        after=copy.deepcopy(before)
        after['columns'].append(['products','nutrition_basis_raw','utf8mb4','utf8mb4_unicode_ci','',''])
        verify_logical(before,after)
        for path,value in [('table_comment','changed'),('counter',89),('collation','utf8mb4_bin'),('trigger','b'*64)]:
            bad=copy.deepcopy(after)
            if path=='table_comment':bad['tables'][0][2]=value
            if path=='counter':bad['tables'][0][4]=value
            if path=='collation':bad['columns'][0][3]=value
            if path=='trigger':bad['triggers_sha256']=value
            with self.subTest(path=path),self.assertRaises(ValueError):verify_logical(before,bad)

    def test_history_rank_not_assumed_equal_to_count(self):
        conn=MagicMock();conn.cursor.return_value.__enter__.return_value.fetchone.return_value=(21,17)
        self.assertEqual(history_bound(conn),21)

    def test_project_event_or_same_account_session_blocks_without_global_queries(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        with patch('initial_db_facts.require_observation_privileges'):
            cur.fetchone.side_effect=((1,),)
            with self.assertRaisesRegex(ValueError,'SCHEDULED_EVENT'):project_idle(conn,timeout=0)
            cur.fetchone.side_effect=((0,),(1,))
            with self.assertRaisesRegex(ValueError,'CONNECTIONS_REMAIN'):project_idle(conn,timeout=0)
            cur.fetchone.side_effect=((0,),(0,))
            project_idle(conn,timeout=0)
        process_sql = [c.args[0] for c in cur.execute.call_args_list if 'PROCESSLIST' in c.args[0]]
        self.assertTrue(all('DB=' not in sql for sql in process_sql))
        self.assertTrue(all('USER=SUBSTRING_INDEX(CURRENT_USER()' in sql for sql in process_sql))
        self.assertFalse(any('INNODB_TRX' in c.args[0] for c in cur.execute.call_args_list))

    def test_disconnecting_pool_gets_bounded_drain_with_guard(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect=((0,),(2,),(0,),(0,))
        guard=MagicMock()
        with patch('initial_db_facts.require_observation_privileges'),patch('initial_db_facts.time.sleep') as sleep:
            project_idle(conn,guard=guard)
        self.assertEqual(guard.call_count,2);sleep.assert_called_once_with(1)

    def test_hidden_or_revoked_metadata_privileges_are_rejected(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value=('NONE',)
        for grants in ([('GRANT SELECT ON *.* TO x',)],
                       [('GRANT ALL PRIVILEGES ON `another`.* TO x',)],
                       [('GRANT EVENT ON `jjikmuk`.* TO x',)],
                       [('GRANT ALL PRIVILEGES ON *.* TO x',),('REVOKE EVENT ON `other`.* FROM x',)]):
            cur.fetchmany.return_value=grants
            with self.assertRaises(ValueError):require_observation_privileges(conn)
        cur.fetchmany.return_value=[('GRANT PROCESS, EVENT, TRIGGER ON *.* TO x',)]
        require_observation_privileges(conn)
        cur.fetchmany.return_value=[('GRANT USAGE ON *.* TO x',),('GRANT ALL PRIVILEGES ON `jjikmuk`.* TO x',)]
        require_observation_privileges(conn)
        cur.fetchone.return_value=('`rds_superuser_role`@`%`',)
        require_observation_privileges(conn)
        self.assertIn('USING `rds_superuser_role`',cur.execute.call_args.args[0])


if __name__ == '__main__':unittest.main()
