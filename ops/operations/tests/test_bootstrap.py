import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from bootstrap import create_connection,check_github
from connection import canonical,sha,REPO_ID


class BootstrapTests(unittest.TestCase):
    def fixture(self):
        clients={'cloudformation':MagicMock(),'s3':MagicMock()}
        clients['cloudformation'].create_stack.return_value={'StackId':'known-stack'}
        clients['cloudformation'].describe_stacks.return_value={'Stacks':[{'StackStatus':'CREATE_COMPLETE'}]}
        raw=canonical({'fixture':True})
        return clients,raw

    def test_one_setup_has_no_session_export_and_receipt_is_automatically_available(self):
        clients,raw=self.fixture()
        with tempfile.TemporaryDirectory() as td,patch('bootstrap.preflight',return_value=(raw,False,{})):
            journal=Path(td)/'journal.json'
            result=create_connection(clients,'a'*40,sha(raw),journal,lambda _:'CONNECT JJIKMUK OPERATIONS ONCE',lambda _:None)
            self.assertFalse(result['credential_export']);self.assertEqual(1,clients['cloudformation'].create_stack.call_count)
            self.assertTrue(clients['cloudformation'].create_stack.call_args.kwargs['DisableRollback'])
            self.assertEqual('*',clients['s3'].put_object.call_args.kwargs['IfNoneMatch'])
            self.assertEqual('CONNECTION_CREATED',json.loads(journal.read_text())['status'])
            with self.assertRaisesRegex(ValueError,'KEEP_EXISTING_JOURNAL'):create_connection(clients,'a'*40,sha(raw),journal)
            self.assertEqual(1,clients['cloudformation'].create_stack.call_count)

    def test_missing_confirmation_or_hash_never_creates_resources(self):
        clients,raw=self.fixture()
        with tempfile.TemporaryDirectory() as td,patch('bootstrap.preflight',return_value=(raw,False,{})):
            journal=Path(td)/'journal.json'
            with self.assertRaises(ValueError):create_connection(clients,'a'*40,'b'*64,journal)
            with self.assertRaises(ValueError):create_connection(clients,'a'*40,sha(raw),journal,lambda _:'no')
            self.assertFalse(journal.exists());clients['cloudformation'].create_stack.assert_not_called()

    def test_partial_setup_failure_keeps_journal_and_never_recreates(self):
        clients,raw=self.fixture();clients['cloudformation'].describe_stacks.return_value={'Stacks':[{'StackStatus':'CREATE_FAILED'}]}
        with tempfile.TemporaryDirectory() as td,patch('bootstrap.preflight',return_value=(raw,False,{})):
            journal=Path(td)/'journal.json'
            with self.assertRaises(ValueError):create_connection(clients,'a'*40,sha(raw),journal,lambda _:'CONNECT JJIKMUK OPERATIONS ONCE',lambda _:None)
            self.assertEqual('STOPPED_KEEP_RECORDS_NO_RETRY',json.loads(journal.read_text())['status'])
            clients['s3'].put_object.assert_not_called()
            with self.assertRaises(ValueError):create_connection(clients,'a'*40,sha(raw),journal)
            self.assertEqual(1,clients['cloudformation'].create_stack.call_count)

    def test_github_protection_is_required_before_aws_setup(self):
        responses={'git/ref/heads/main':{'object':{'sha':'a'*40}},'':{'id':REPO_ID},
            'actions/oidc/customization/sub':{'use_default':True,'use_immutable_subject':False},
            'actions/workflows/server-operations.yml':{'state':'active'},
            'environments/production':{'can_admins_bypass':False,'protection_rules':[{'type':'required_reviewers','reviewers':[{'id':1}]}]},
            'environments/production/deployment-branch-policies':{'branch_policies':[{'name':'main','type':'branch'}]}}
        with patch('bootstrap.github',side_effect=lambda x:responses[x]):
            self.assertTrue(check_github('a'*40)['production_reviewers_configured'])
            responses['environments/production']['protection_rules']=[]
            with self.assertRaisesRegex(ValueError,'PRODUCTION_REVIEWER_REQUIRED'):check_github('a'*40)


if __name__=='__main__':unittest.main()
