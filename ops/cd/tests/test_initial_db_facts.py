import copy
import unittest
from unittest.mock import MagicMock
from initial_db_facts import verify_logical, history_bound, quiescent


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

    def test_any_remaining_writer_or_transaction_blocks(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        for values in (((1,),(0,)),((0,),(1,))):
            cur.fetchone.side_effect=values
            with self.assertRaisesRegex(ValueError,'NOT_QUIESCENT'):quiescent(conn)
        cur.fetchone.side_effect=((0,),(0,))
        quiescent(conn)


if __name__ == '__main__':unittest.main()
