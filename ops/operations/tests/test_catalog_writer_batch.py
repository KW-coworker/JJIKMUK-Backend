import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from catalog_writer import Writer


class BatchTests(unittest.TestCase):
    def writer(self):
        writer = Writer.__new__(Writer)
        writer.connection = MagicMock()
        return writer

    def test_repeated_reset_recreates_only_temporary_table_with_primary_key(self):
        writer = self.writer()
        writer.reset_batch()
        writer.reset_batch()
        queries = [c.args[0] for c in writer.connection.cursor().__enter__().execute.call_args_list]
        self.assertEqual(len(queries), 4)
        self.assertEqual(queries[0], 'DROP TEMPORARY TABLE IF EXISTS jjikmuk_catalog_batch')
        self.assertEqual(queries[:2], queries[2:])
        self.assertTrue(queries[1].startswith('CREATE TEMPORARY TABLE jjikmuk_catalog_batch (PRIMARY KEY(product_id))'))
        self.assertTrue(queries[1].endswith('FROM products WHERE 1=0'))
        writer.connection.commit.assert_not_called()
        writer.connection.begin.assert_not_called()

    def test_reset_failure_stops_apply_before_transaction_or_product_writes(self):
        writer = self.writer()
        writer.setup = Mock()
        writer.guard = Mock()
        writer.reset_batch = Mock(side_effect=RuntimeError('TEMP_RESET_FAILED'))
        with self.assertRaisesRegex(RuntimeError, 'TEMP_RESET_FAILED'):
            writer.run()
        writer.guard.assert_called_once()
        writer.reset_batch.assert_called_once()
        writer.connection.begin.assert_not_called()
        writer.connection.cursor.assert_not_called()

    def test_reset_failure_stops_recovery_before_transaction_or_product_writes(self):
        writer = self.writer()
        writer.journal = SimpleNamespace(db=MagicMock())
        writer.journal.db.execute().fetchall.return_value = [(1,)]
        writer.guard = Mock()
        writer.reset_batch = Mock(side_effect=RuntimeError('TEMP_RESET_FAILED'))
        with self.assertRaisesRegex(RuntimeError, 'TEMP_RESET_FAILED'):
            writer.recover()
        writer.guard.assert_called_once()
        writer.reset_batch.assert_called_once()
        writer.connection.begin.assert_not_called()
        writer.connection.cursor.assert_not_called()


if __name__ == '__main__':
    unittest.main()
