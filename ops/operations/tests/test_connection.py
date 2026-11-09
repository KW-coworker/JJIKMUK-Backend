import json
import unittest
from connection import template, permissions, automatic_backend_permissions, HOSTS, ACCOUNT, DEPLOY_DOCUMENT


class ConnectionTests(unittest.TestCase):
    def test_no_root_password_or_static_access_key_is_created(self):
        t = template(); kinds = {x['Type'] for x in t['Resources'].values()}
        self.assertFalse(kinds & {'AWS::IAM::User', 'AWS::IAM::AccessKey', 'AWS::EC2::Instance'})
        self.assertEqual(4, sum(x['Type']=='AWS::IAM::Role' for x in t['Resources'].values()))
        for name in ('Read', 'Execute', 'BackendAuto', 'ChatbotAuto'):
            role = t['Resources'][name+'Role']['Properties']
            self.assertEqual(role['PermissionsBoundary'], role['ManagedPolicyArns'][0])
            trust = role['AssumeRolePolicyDocument']['Statement'][0]
            self.assertEqual('sts:AssumeRoleWithWebIdentity', trust['Action'])
            sub = trust['Condition']['StringEquals']['token.actions.githubusercontent.com:sub']
            self.assertNotIn('*', sub)

    def test_automatic_role_cannot_run_operations_or_touch_ocr(self):
        p=automatic_backend_permissions()
        sends=[s for s in p['Statement'] if s['Action']=='ssm:SendCommand']
        self.assertEqual(1,len(sends))
        self.assertEqual({f'arn:aws:ssm:ap-northeast-2:{ACCOUNT}:document/{DEPLOY_DOCUMENT}',
            f'arn:aws:ec2:ap-northeast-2:{ACCOUNT}:instance/{HOSTS["backend"]}'},set(sends[0]['Resource']))
        actions={a for s in p['Statement'] for a in ([s['Action']] if isinstance(s['Action'],str) else s['Action'])}
        self.assertFalse(actions & {'ssm:CreateDocument','rds:CreateDBSnapshot','iam:PassRole','ssm:StartSession'})
        self.assertFalse(any('Delete' in a for a in actions))
        text=json.dumps(p)
        self.assertNotIn(HOSTS['ocr'],text);self.assertNotIn('/operations/*',text)
        subject=template()['Resources']['BackendAutoRole']['Properties']['AssumeRolePolicyDocument']['Statement'][0]['Condition']['StringEquals']['token.actions.githubusercontent.com:sub']
        self.assertTrue(subject.endswith(':environment:backend-production'))

    def test_chatbot_role_has_separate_subject_document_and_artifact_prefix(self):
        text=json.dumps(automatic_backend_permissions('chatbot'))
        self.assertIn('Jjikmuk-ChatbotDeploy-v1',text)
        self.assertIn('/artifacts/chatbot/*',text)
        self.assertNotIn('/artifacts/backend/',text);self.assertNotIn(HOSTS['ocr'],text)
        t=template()['Resources']['ChatbotAutoRole']['Properties']['AssumeRolePolicyDocument']
        self.assertIn('repo:Alphrit/jjikmuk-CO-WORKER-:environment:chatbot-production',json.dumps(t))

    def test_execute_is_limited_to_named_hosts_and_operations(self):
        for write in (False, True):
            p = permissions(write)
            sends = [s for s in p['Statement'] if s['Action']=='ssm:SendCommand']
            instances = {r for s in sends for r in s['Resource'] if ':instance/' in r}
            self.assertEqual({f'arn:aws:ec2:ap-northeast-2:{ACCOUNT}:instance/{x}' for x in HOSTS.values()}, instances)
            actions = {a for s in p['Statement'] for a in ([s['Action']] if isinstance(s['Action'],str) else s['Action'])}
            self.assertFalse(any(a.startswith(('iam:', 'secretsmanager:', 'kms:')) for a in actions))
            self.assertFalse(any('Delete' in a or a=='ssm:StartSession' for a in actions))
            if not write:self.assertNotIn('ssm:CreateDocument', actions)

    def test_no_application_command_during_stack_creation(self):
        t = template(); text = json.dumps(t)
        self.assertNotIn('Custom::', text)
        self.assertNotIn('AWS::SSM::Association', text)
        self.assertEqual(['JjikmukMigrationHost'], t['Resources']['HostArtifactRead']['Properties']['Roles'])
        bucket=t['Resources']['OperationsBucket']
        self.assertEqual('Retain',bucket['DeletionPolicy'])
        self.assertTrue(all(bucket['Properties']['PublicAccessBlockConfiguration'].values()))
        parameters=t['Resources']['InspectDocument']['Properties']['Content']['parameters']
        self.assertEqual({'HostKind'},set(parameters))
        self.assertEqual(['backend','ocr'],parameters['HostKind']['allowedValues'])
        self.assertEqual('ENV_VAR',parameters['HostKind']['interpolationType'])


if __name__ == '__main__':unittest.main()
