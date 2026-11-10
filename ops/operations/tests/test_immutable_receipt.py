import io,unittest
from unittest.mock import MagicMock
from botocore.exceptions import ClientError,ConnectionClosedError
from immutable_receipt import put_once
from connection import canonical

def closed():return ConnectionClosedError(endpoint_url='https://example.invalid')
def error(code):return ClientError({'Error':{'Code':code}},'PutObject')

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.s3=MagicMock();self.value={'request_id':'a'*32,'status':'intent'}
        self.body=canonical(self.value)
        self.s3.get_object.return_value={'ContentLength':len(self.body),'Body':io.BytesIO(self.body)}

    def write(self):return put_once(self.s3,'receipts/fixed/intent.json',self.value,sleep=lambda _:None)

    def test_lost_response_reads_exact_saved_receipt_without_rewriting(self):
        self.s3.put_object.side_effect=closed()
        self.assertTrue(self.write()['confirmed_after_transport_error'])
        self.s3.put_object.assert_called_once();self.s3.get_object.assert_called_once()

    def test_missing_receipt_retries_only_same_conditional_object(self):
        self.s3.put_object.side_effect=[closed(),{'VersionId':'safe'}]
        self.s3.get_object.side_effect=error('NoSuchKey')
        self.assertEqual(self.write(),{'VersionId':'safe'})
        first,second=self.s3.put_object.call_args_list
        self.assertEqual(first,second);self.assertEqual(first.kwargs['IfNoneMatch'],'*')

    def test_late_first_write_conflict_requires_identical_content(self):
        self.s3.put_object.side_effect=[closed(),error('PreconditionFailed')]
        self.s3.get_object.side_effect=[error('NoSuchKey'),{'ContentLength':len(self.body),'Body':io.BytesIO(self.body)}]
        self.assertTrue(self.write()['confirmed_after_transport_error'])

    def test_existing_intent_always_blocks_fresh_execution(self):
        self.s3.put_object.side_effect=error('PreconditionFailed')
        with self.assertRaises(ClientError):self.write()
        self.s3.get_object.assert_not_called()

    def test_conflicting_saved_content_and_denied_access_never_retry(self):
        self.s3.put_object.side_effect=closed()
        self.s3.get_object.return_value={'ContentLength':len(self.body),'Body':io.BytesIO(b'x'*len(self.body))}
        with self.assertRaisesRegex(ValueError,'CHANGED'):self.write()
        self.assertEqual(self.s3.put_object.call_count,1)
        self.s3.reset_mock();self.s3.put_object.side_effect=error('AccessDenied')
        with self.assertRaises(ClientError):self.write()
        self.s3.get_object.assert_not_called()

    def test_continuous_transport_failure_is_bounded_without_server_command(self):
        self.s3.put_object.side_effect=closed();self.s3.get_object.side_effect=closed()
        with self.assertRaisesRegex(ValueError,'UNCONFIRMED'):self.write()
        self.assertEqual(self.s3.put_object.call_count,3);self.assertEqual(self.s3.get_object.call_count,3)
        self.assertEqual({c[0] for c in self.s3.mock_calls},{'put_object','get_object'})

if __name__=='__main__':unittest.main()
