import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from bootstrap import create_connection,check_github
from connection import canonical,sha,REPO_ID
from connection import template
from build_bootstrap import build


class BootstrapTests(unittest.TestCase):
    def test_single_file_has_identical_template_and_does_not_execute_on_import(self):
        source=build(Path(__file__).resolve().parents[1]);namespace={'__name__':'offline_check'}
        exec(compile(source,'connect_once.py','exec'),namespace)
        self.assertEqual(template(),namespace['template']())
        self.assertNotIn('aws_access_key_id',source)
        self.assertNotIn('export_session',source)

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
            'environments/production':{'can_admins_bypass':False,
                'deployment_branch_policy':{'protected_branches':False,'custom_branch_policies':True},
                'protection_rules':[{'type':'required_reviewers',
                'prevent_self_review':False,'reviewers':[{'reviewer':{'id':166599710}}]}]},
            'environments/production/deployment-branch-policies':{'branch_policies':[{'name':'main','type':'branch'}]},
            'environments/backend-production':{'deployment_branch_policy':{'protected_branches':False,'custom_branch_policies':True},
                'protection_rules':[{'type':'branch_policy'}]},
            'environments/backend-production/deployment-branch-policies':{'branch_policies':[{'name':'main','type':'branch'}]},
            'actions/workflows/server-operations.yml/runs?event=workflow_dispatch&per_page=30':{'workflow_runs':[{
                'id':123,'head_sha':'a'*40,'conclusion':'success','display_title':'Server operations precheck at '+'a'*40+' [test]'}]},
            'actions/runs/123/jobs':{'jobs':[{'name':'precheck','conclusion':'success','steps':[{
                'name':'Verify actual OIDC identity without AWS','conclusion':'success'}]},
                {'name':'backend-auto-precheck','conclusion':'success','steps':[{
                'name':'Verify automatic backend OIDC without AWS','conclusion':'success'}]}]}}
        with patch('bootstrap.github',side_effect=lambda x:responses[x]):
            self.assertTrue(check_github('a'*40)['production_reviewers_configured'])
            auto=responses['environments/backend-production']
            for rule in ({'type':'required_reviewers','reviewers':[{}]}, {'type':'wait_timer','wait_timer':5}, {'type':'custom'}):
                auto['protection_rules']=[rule]
                with self.assertRaisesRegex(ValueError,'AUTOMATIC_BACKEND_MUST_NOT_WAIT_FOR_APPROVAL'):check_github('a'*40)
            auto['protection_rules']=[]
            self.assertTrue(check_github('a'*40)['backend_automatic_without_reviewers'])
            responses['environments/production']['deployment_branch_policy']['custom_branch_policies']=False
            with self.assertRaisesRegex(ValueError,'PRODUCTION_BRANCH_POLICY_NOT_ACTIVE'):check_github('a'*40)
            responses['environments/production']['deployment_branch_policy']['custom_branch_policies']=True
            runs=responses['actions/workflows/server-operations.yml/runs?event=workflow_dispatch&per_page=30']['workflow_runs']
            runs[0]['conclusion']='failure'
            with self.assertRaisesRegex(ValueError,'REAL_GITHUB_PRECHECK_REQUIRED_BEFORE_CLOUDSHELL'):check_github('a'*40)
            runs[0]['conclusion']='success'
            responses['environments/production']['protection_rules']=[]
            with self.assertRaisesRegex(ValueError,'PRODUCTION_REVIEWER_REQUIRED'):check_github('a'*40)


if __name__=='__main__':unittest.main()
