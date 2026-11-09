import json
import unittest
from connection import template, permissions, HOSTS, ACCOUNT


class ConnectionTests(unittest.TestCase):
    def test_no_root_password_or_static_access_key_is_created(self):
        t = template(); kinds = {x['Type'] for x in t['Resources'].values()}
        self.assertFalse(kinds & {'AWS::IAM::User', 'AWS::IAM::AccessKey', 'AWS::EC2::Instance'})
        self.assertEqual(2, sum(x['Type']=='AWS::IAM::Role' for x in t['Resources'].values()))
        for name in ('Read', 'Execute'):
            role = t['Resources'][name+'Role']['Properties']
            self.assertEqual(role['PermissionsBoundary'], role['ManagedPolicyArns'][0])
            trust = role['AssumeRolePolicyDocument']['Statement'][0]
            self.assertEqual('sts:AssumeRoleWithWebIdentity', trust['Action'])
            sub = trust['Condition']['StringEquals']['token.actions.githubusercontent.com:sub']
            self.assertNotIn('*', sub)

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
        self.assertEqual({},t['Resources']['InspectDocument']['Properties']['Content']['parameters'])


if __name__ == '__main__':unittest.main()
