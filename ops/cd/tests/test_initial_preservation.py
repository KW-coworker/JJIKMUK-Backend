import unittest
from unittest.mock import MagicMock
from initial_preservation import capture, projection, row_hash_sql, verify


class InitialPreservationTests(unittest.TestCase):
    def test_original_projection_ignores_new_schema_only_when_caller_uses_original(self):
        metadata={'columns':[['users','id'],['users','value']],
                  'indexes':[['users','PRIMARY',0,1,'id']]}
        old=projection(metadata)
        sql,args=row_hash_sql('users',old['users'],17)
        self.assertIn('CAST(`value` AS BINARY)',sql)
        self.assertIn("IS NULL,'N'",sql)
        self.assertNotIn('profile_version',sql)
        self.assertEqual(args,())
        with self.assertRaises(ValueError):row_hash_sql('users;DROP TABLE users',old['users'],17)
        with self.assertRaises(ValueError):projection(dict(metadata,indexes=[]))

    def test_original_history_rows_are_bounded(self):
        sql,args=row_hash_sql('flyway_schema_history',{'columns':['installed_rank','checksum'],
                                 'primary_key':['installed_rank']},17)
        self.assertIn('WHERE `installed_rank`<=%s',sql)
        self.assertEqual(args,(17,))

    def test_differences_and_missing_table_are_rejected(self):
        before={'users':{'rows':1,'sha256':'a'*64}}
        verify(before,dict(before))
        for after in ({},{'users':{'rows':1,'sha256':'b'*64}}, {'users':{'rows':2,'sha256':'a'*64}}):
            with self.assertRaises(ValueError):verify(before,after)

    def test_guard_failure_rolls_back_read_transaction(self):
        conn=MagicMock();guard=MagicMock(side_effect=ValueError('STALE_GUARD'))
        with self.assertRaisesRegex(ValueError,'STALE_GUARD'):
            capture(conn,{'users':{'columns':['id'],'primary_key':['id']}},17,guard,cursor_class=object)
        conn.rollback.assert_called_once()
        conn.cursor.return_value.__enter__.return_value.execute.assert_any_call('START TRANSACTION READ ONLY')

    def test_guard_failure_does_not_drain_streaming_rows(self):
        conn=MagicMock();stream=MagicMock()
        conn.cursor.side_effect=[MagicMock(),stream]
        stream.fetchmany.side_effect=[[('a'*64,)], [('b'*64,)]]
        guard=MagicMock(side_effect=[None,ValueError('STALE_GUARD')])
        with self.assertRaisesRegex(ValueError,'STALE_GUARD'):
            capture(conn,{'users':{'columns':['id'],'primary_key':['id']}},17,guard,cursor_class=object)
        conn.close.assert_called_once()
        conn.rollback.assert_not_called()
        stream.close.assert_not_called()
        self.assertEqual(stream.fetchmany.call_count,1)


if __name__ == '__main__':unittest.main()
