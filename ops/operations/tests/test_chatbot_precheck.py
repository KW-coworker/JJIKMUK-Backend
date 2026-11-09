import copy
import unittest
from unittest.mock import patch
from bootstrap import check_chatbot
from connection import CHATBOT_REPO_ID
from oidc_precheck import validate_claims


class ChatbotPrecheck(unittest.TestCase):
    def claims(self):
        return {'iss':'https://token.actions.githubusercontent.com','aud':'sts.amazonaws.com',
            'sub':'repo:KW-coworker@304766488/PRE_REPO@1206944262:environment:chatbot-production',
            'repository':'KW-coworker/PRE_REPO','repository_owner_id':'304766488',
            'repository_id':CHATBOT_REPO_ID,'ref':'refs/heads/chatbot','sha':'a'*40,'run_id':'3'}

    def test_exact_chatbot_subject_cannot_use_backend_identity(self):
        claims=self.claims()
        env={'OIDC_ENVIRONMENT':'chatbot-production','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'3'}
        self.assertEqual(validate_claims(claims,env)['repository_id'],CHATBOT_REPO_ID)
        with self.assertRaises(ValueError):validate_claims(dict(claims,ref='refs/heads/main'),env)

    def test_recycled_names_wrong_ids_and_legacy_subjects_are_rejected(self):
        claims=self.claims();env={'OIDC_ENVIRONMENT':'chatbot-production','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'3'}
        cases=[{'sub':'repo:Alphrit/jjikmuk-CO-WORKER-:environment:chatbot-production'},
            {'sub':'repo:KW-coworker/PRE_REPO:environment:chatbot-production'},
            {'sub':claims['sub'].replace('304766488','999')},
            {'sub':claims['sub'].replace('1206944262','999')},
            {'repository':'Alphrit/jjikmuk-CO-WORKER-'},{'repository_owner_id':'999'},
            {'repository_id':'999'},{'sha':'b'*40},{'run_id':'4'},
            {'sub':claims['sub'].replace('chatbot-production','backend-production')}]
        for changed in cases:
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                validate_claims(claims|changed,env)

    def fixture(self):
        return {'':{'id':CHATBOT_REPO_ID,'default_branch':'main','full_name':'KW-coworker/PRE_REPO','owner':{'id':304766488}},
            'branches/chatbot':{'protected':True,'commit':{'sha':'a'*40}},
            'actions/oidc/customization/sub':{'use_default':True,'use_immutable_subject':True,
                'sub_claim_prefix':'repo:KW-coworker@304766488/PRE_REPO@1206944262'},
            'environments/chatbot-production':{'protection_rules':[],'deployment_branch_policy':{'protected_branches':False,'custom_branch_policies':True}},
            'environments/chatbot-production/deployment-branch-policies':{'branch_policies':[{'name':'chatbot','type':'branch'}]},
            'actions/workflows/chatbot-precheck.yml/runs?event=workflow_dispatch&per_page=30':{'workflow_runs':[]}}

    def check(self,values):
        def read(path,repo):
            self.assertEqual(repo,'KW-coworker/PRE_REPO')
            return values[path]
        with patch('bootstrap.github',side_effect=read):return check_chatbot()

    def test_missing_real_precheck_blocks_cloudshell(self):
        values=self.fixture()
        with patch('bootstrap.github',side_effect=lambda path,repo:values[path]):
            with self.assertRaisesRegex(ValueError,'REAL_CHATBOT_PRECHECK'):check_chatbot()
            values['branches/chatbot']['protected']=False
            with self.assertRaisesRegex(ValueError,'CHATBOT_BRANCH_PROTECTION'):check_chatbot()

    def test_setup_accepts_new_identity_only_after_real_precheck(self):
        values=self.fixture()
        values['actions/workflows/chatbot-precheck.yml/runs?event=workflow_dispatch&per_page=30']['workflow_runs']=[
            {'id':5,'head_sha':'a'*40,'head_branch':'chatbot','conclusion':'success'}]
        values['actions/runs/5/jobs']={'jobs':[{'conclusion':'success','steps':[
            {'name':'Verify actual chatbot OIDC without AWS','conclusion':'success'}]}]}
        self.assertEqual(self.check(values)['precheck_run_id'],5)
        for field,value in [('full_name','Alphrit/jjikmuk-CO-WORKER-'),('id',999),('owner',{'id':999})]:
            bad=copy.deepcopy(values);bad[''][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'CHATBOT_REPOSITORY_CHANGED'):self.check(bad)
        for field,value in [('use_default',False),('use_immutable_subject',False),('sub_claim_prefix','repo:KW-coworker/PRE_REPO')]:
            bad=copy.deepcopy(values);bad['actions/oidc/customization/sub'][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'CHATBOT_OIDC_SUBJECT_CHANGED'):self.check(bad)
