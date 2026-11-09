import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from connection import canonical,sha
from control import dispatch,approve_environment


class ControlTests(unittest.TestCase):
    def test_dispatch_requires_exact_approval_and_preserves_lost_response_intent(self):
        api=MagicMock();api.call.return_value={'object':{'sha':'a'*40}}
        inputs={'mode':'inspect','expected_sha':'a'*40,'request_id':'b'*32}
        request={'workflow':'server-operations.yml','inputs':inputs,'approval':{'status':'APPROVED','input_sha256':sha(canonical(inputs))}}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'intent.json';api.call.side_effect=[{'object':{'sha':'a'*40}},TimeoutError(),{'object':{'sha':'a'*40}}]
            with self.assertRaises(TimeoutError):dispatch(api,request,p)
            self.assertTrue(p.exists())
            with self.assertRaisesRegex(ValueError,'DISPATCH_INTENT_EXISTS'):dispatch(api,request,p)
            self.assertEqual(1,len([c for c in api.call.call_args_list if len(c.args)>1 and c.args[1]=='POST']))

    def test_unapproved_dispatch_does_not_write(self):
        api=MagicMock();api.call.return_value={'object':{'sha':'a'*40}}
        request={'workflow':'server-operations.yml','inputs':{'mode':'execute','expected_sha':'a'*40,'request_id':'b'*32,'confirm':True},
                 'approval':{'status':'PENDING','input_sha256':'x'}}
        with tempfile.TemporaryDirectory() as td,self.assertRaisesRegex(ValueError,'EXACT_USER_APPROVAL_REQUIRED'):
            dispatch(api,request,Path(td)/'intent.json')
        self.assertEqual(1,api.call.call_count)

    def test_environment_approval_matches_exact_request(self):
        api=MagicMock();approval={'status':'APPROVED','run_id':'123','expected_sha':'a'*40,'request_id':'b'*32}
        run={'path':'.github/workflows/server-operations.yml','head_branch':'main','head_sha':'a'*40,
             'display_title':'Server operations execute at '+'a'*40+' ['+'c'*32+']'}
        api.call.return_value=run
        with self.assertRaisesRegex(ValueError,'APPROVED_REQUEST_MISMATCH'):approve_environment(api,'123',approval)
        self.assertEqual(1,api.call.call_count)


if __name__=='__main__':unittest.main()
