import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,Mock,patch
import catalog_preservation as preservation


class PreservationTests(unittest.TestCase):
    def capture(self,rows,bound):
        connection=MagicMock();connection.open=True
        connection.close.side_effect=lambda:setattr(connection,'open',False)
        queries=[]
        class Stream:
            def execute(self,sql,params):
                queries.append((sql,params));self.left=rows if 'product_attribute_snapshots' in sql else 0
            def fetchmany(self,size):
                n=min(self.left,size);self.left-=n
                return [('a'*64,)]*n
            def close(self):pass
        stream=Stream()
        connection.cursor.side_effect=lambda *args:stream if args else MagicMock()
        shapes={'products':{'columns':['product_id'],'primary_key':['product_id']},
                'product_attribute_snapshots':{'columns':['id'],'primary_key':['id']}}
        with patch.object(preservation,'projection',return_value=shapes):
            result=preservation.capture(connection,{}, {'snapshot_id':bound,'history_rank':22},Mock(),object())
        return result,connection,queries

    def test_all_history_over_three_million_is_hashed_through_frozen_id(self):
        rows=3_000_001
        result,connection,queries=self.capture(rows,rows+100)
        expected=hashlib.sha256()
        for offset in range(0,rows,2048):expected.update(b'a'*64*min(2048,rows-offset))
        self.assertEqual(result['product_attribute_snapshots'],{'rows':rows,'sha256':expected.hexdigest()})
        self.assertIn(' WHERE `id`<=%s ORDER BY ',queries[0][0]);self.assertEqual(queries[0][1],(rows+100,))
        connection.close.assert_not_called();connection.rollback.assert_called_once()

    def test_history_outside_saved_pk_count_bound_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError,'ROW_BOUND'):self.capture(3,2)

    def test_empty_history_and_other_table_limits_remain_bounded(self):
        result,unused,queries=self.capture(0,0)
        self.assertEqual(result['product_attribute_snapshots']['rows'],0)
        self.assertEqual(preservation.row_limit('products',{}),3_000_000)
        for bound in (-1,True,2**63,'3000001'):
            with self.assertRaisesRegex(ValueError,'HISTORY_BOUND'):
                preservation.row_limit('product_attribute_snapshots',{'snapshot_id':bound})

    def test_already_disconnected_stream_does_not_hide_original_error(self):
        connection=MagicMock();connection.open=False
        connection.close.side_effect=RuntimeError('Already closed')
        stream=Mock();stream.fetchmany.side_effect=ValueError('CATALOG_TEST_ORIGINAL_FAILURE')
        connection.cursor.side_effect=lambda *args:stream if args else MagicMock()
        shapes={'products':{'columns':['product_id'],'primary_key':['product_id']}}
        with patch.object(preservation,'projection',return_value=shapes),\
             self.assertRaisesRegex(ValueError,'CATALOG_TEST_ORIGINAL_FAILURE'):
            preservation.capture(connection,{}, {'snapshot_id':0,'history_rank':22},Mock(),object())
        connection.close.assert_not_called();connection.rollback.assert_not_called()


if __name__=='__main__':unittest.main()
