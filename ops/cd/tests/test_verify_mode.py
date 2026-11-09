import io
import json
import os
import unittest
from unittest.mock import patch
from release import guard


class VerifyModeTests(unittest.TestCase):
    def env(self, mode='verify'):
        return {'GITHUB_REPOSITORY':'KW-coworker/JJIKMUK-Backend',
                'GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'workflow_dispatch',
                'GITHUB_SHA':'a'*40,'EXPECTED_SHA':'a'*40,
                'GITHUB_RUN_ID':'1','GITHUB_RUN_ATTEMPT':'1','CD_MODE':mode}

    def test_verify_builds_with_cd_disabled_without_aws(self):
        with patch.dict(os.environ,self.env(),clear=True), patch('release.aws') as aws, \
             patch('release.urllib.request.urlopen') as url:
            url.return_value.__enter__.return_value=io.StringIO(json.dumps({'object':{'sha':'a'*40}}))
            guard(deployment=False)
            aws.assert_not_called()

    def test_verify_cannot_dispatch(self):
        with patch.dict(os.environ,self.env(),clear=True),self.assertRaisesRegex(ValueError,'DEPLOYMENT_NOT_APPROVED'):
            guard()

    def test_deploy_requires_both_switch_and_approval_even_for_packaging(self):
        for changes in ({},{'CONFIRM_DEPLOY':'true'},{'CD_ENABLED':'true'}):
            with self.subTest(changes=changes),patch.dict(os.environ,{**self.env('deploy'),**changes},clear=True),self.assertRaises(ValueError):
                guard(deployment=False)

    def test_verify_rejects_changed_main(self):
        with patch.dict(os.environ,self.env(),clear=True),patch('release.urllib.request.urlopen') as url:
            url.return_value.__enter__.return_value=io.StringIO(json.dumps({'object':{'sha':'b'*40}}))
            with self.assertRaisesRegex(ValueError,'MAIN_MOVED'):guard(deployment=False)
