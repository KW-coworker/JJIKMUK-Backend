import unittest
from unittest.mock import patch
from bootstrap import check_chatbot
from connection import CHATBOT_REPO_ID
from oidc_precheck import validate_claims


class ChatbotPrecheck(unittest.TestCase):
    def test_exact_chatbot_subject_cannot_use_backend_identity(self):
        claims={'iss':'https://token.actions.githubusercontent.com','aud':'sts.amazonaws.com',
            'sub':'repo:Alphrit/jjikmuk-CO-WORKER-:environment:chatbot-production','repository_id':CHATBOT_REPO_ID,
            'ref':'refs/heads/chatbot','sha':'a'*40,'run_id':'3'}
        env={'OIDC_ENVIRONMENT':'chatbot-production','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'3'}
        self.assertEqual(validate_claims(claims,env)['repository_id'],CHATBOT_REPO_ID)
        with self.assertRaises(ValueError):validate_claims(dict(claims,ref='refs/heads/main'),env)
    def test_missing_real_precheck_blocks_cloudshell(self):
        values={'':{'id':CHATBOT_REPO_ID,'default_branch':'main'},'branches/chatbot':{'protected':True,'commit':{'sha':'a'*40}},
            'actions/oidc/customization/sub':{'use_default':True,'use_immutable_subject':False},
            'environments/chatbot-production':{'protection_rules':[],'deployment_branch_policy':{'protected_branches':False,'custom_branch_policies':True}},
            'environments/chatbot-production/deployment-branch-policies':{'branch_policies':[{'name':'chatbot','type':'branch'}]},
            'actions/workflows/chatbot-precheck.yml/runs?event=workflow_dispatch&per_page=30':{'workflow_runs':[]}}
        with patch('bootstrap.github',side_effect=lambda path,repo:values[path]):
            with self.assertRaisesRegex(ValueError,'REAL_CHATBOT_PRECHECK'):check_chatbot()
            values['branches/chatbot']['protected']=False
            with self.assertRaisesRegex(ValueError,'CHATBOT_BRANCH_PROTECTION'):check_chatbot()
