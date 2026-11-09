"""Permanent, bounded GitHub OIDC connection. Generates a template; never calls AWS."""
import hashlib
import json
from pathlib import Path

ACCOUNT = '076767081522'
REGION = 'ap-northeast-2'
REPO = 'KW-coworker/JJIKMUK-Backend'
REPO_ID = 1300060655
HOSTS = {'backend': 'i-06350403fe0400e1b', 'ocr': 'i-0feac4ca32779b098'}
HOST_ROLE = 'JjikmukMigrationHost'
BUCKET = 'jjikmuk-operations-076767081522-apne2'
STACK = 'Jjikmuk-ServerOperations'
READ_ROLE = 'JjikmukOperationsRead'
WRITE_ROLE = 'JjikmukOperationsExecute'
AUTO_ROLE = 'JjikmukBackendAutoDeploy'
CHATBOT_REPO = 'KW-coworker/PRE_REPO'
CHATBOT_REPO_ID = 1206944262
CHATBOT_OWNER_ID = 304766488
CHATBOT_OIDC_PREFIX = (f'repo:{CHATBOT_REPO.split("/")[0]}@{CHATBOT_OWNER_ID}/'
                       f'{CHATBOT_REPO.split("/")[1]}@{CHATBOT_REPO_ID}')
CHATBOT_OIDC_SUBJECT = CHATBOT_OIDC_PREFIX + ':environment:chatbot-production'
CHATBOT_ROLE = 'JjikmukChatbotAutoDeploy'
CHATBOT_DOCUMENT = 'Jjikmuk-ChatbotDeploy-v1'
READ_DOCUMENT = 'JjikmukOperationsInspect-v1'
DEPLOY_DOCUMENT = 'Jjikmuk-BackendDeploy-v1'
DOCUMENT_PREFIX = 'JjikmukOperationsApproved-'
PREFIX = 'repo:' + REPO


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def allow(actions, resources, **extra):
    return dict(Effect='Allow', Action=actions, Resource=resources, **extra)


def policy(statements):
    return {'Version': '2012-10-17', 'Statement': statements}


def trust(subject):
    return policy([{'Effect': 'Allow', 'Principal': {'Federated': {'Fn::If': [
        'CreateProvider', {'Ref': 'GitHubProvider'},
        f'arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com']}},
        'Action': 'sts:AssumeRoleWithWebIdentity', 'Condition': {'StringEquals': {
            'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
            'token.actions.githubusercontent.com:sub': subject}}}])


def permissions(write=False):
    instances = [f'arn:aws:ec2:{REGION}:{ACCOUNT}:instance/{x}' for x in HOSTS.values()]
    docs = f'arn:aws:ssm:{REGION}:{ACCOUNT}:document/'
    regional = {'StringEquals': {'aws:RequestedRegion': REGION}}
    statements = [
        allow(['sts:GetCallerIdentity'], '*'),
        allow(['ec2:DescribeInstances', 'ec2:DescribeInstanceStatus', 'ec2:DescribeSecurityGroups',
               'ec2:DescribeVolumes', 'ssm:DescribeInstanceInformation', 'ssm:GetCommandInvocation',
               'ssm:ListCommands', 'ssm:ListCommandInvocations', 'rds:DescribeDBInstances',
               'rds:DescribeDBSnapshots', 'cloudformation:DescribeStacks',
               'cloudformation:DescribeStackEvents', 'cloudformation:ListStackResources'],
              '*', Condition=regional),
        allow(['s3:GetBucketVersioning', 's3:GetEncryptionConfiguration', 's3:GetBucketPublicAccessBlock'],
              f'arn:aws:s3:::{BUCKET}'),
        allow(['s3:GetObject', 's3:GetObjectVersion'], [f'arn:aws:s3:::{BUCKET}/connection/*',
                                                     f'arn:aws:s3:::{BUCKET}/receipts/*']),
        allow(['ssm:GetDocument', 'ssm:DescribeDocument'], docs + READ_DOCUMENT, Condition=regional),
        allow('ssm:SendCommand', [docs + READ_DOCUMENT, *instances], Condition=regional),
    ]
    if write:
        statements += [
            allow(['s3:PutObject', 's3:GetObject', 's3:GetObjectVersion'],
                  [f'arn:aws:s3:::{BUCKET}/{p}/*' for p in ('operations', 'artifacts', 'receipts')]),
            allow('s3:ListBucket', f'arn:aws:s3:::{BUCKET}', Condition={
                'StringLike': {'s3:prefix': ['operations/*', 'artifacts/*', 'receipts/*']}}),
            allow(['ssm:CreateDocument', 'ssm:GetDocument', 'ssm:DescribeDocument'],
                  docs + DOCUMENT_PREFIX + '*', Condition=regional),
            allow('ssm:SendCommand', [docs + DOCUMENT_PREFIX + '*', *instances], Condition=regional),
            allow(['ssm:GetDocument', 'ssm:DescribeDocument'], docs + DEPLOY_DOCUMENT, Condition=regional),
            allow('ssm:SendCommand', [docs + DEPLOY_DOCUMENT,
                  f'arn:aws:ec2:{REGION}:{ACCOUNT}:instance/{HOSTS["backend"]}'], Condition=regional),
            allow('rds:CreateDBSnapshot',
                  [f'arn:aws:rds:{REGION}:{ACCOUNT}:db:jjikmuk-dev-db',
                   f'arn:aws:rds:{REGION}:{ACCOUNT}:snapshot:jjikmuk-ops-*'], Condition=regional),
            allow('rds:AddTagsToResource', f'arn:aws:rds:{REGION}:{ACCOUNT}:snapshot:jjikmuk-ops-*', Condition=regional),
        ]
    # This managed policy is also the role's permissions boundary. No IAM writes,
    # EC2 lifecycle/network changes, data API, secret retrieval or resource deletion.
    return policy(statements)


def automatic_backend_permissions(component='backend'):
    if component not in ('backend','chatbot'):raise ValueError('AUTOMATIC_COMPONENT')
    regional = {'StringEquals': {'aws:RequestedRegion': REGION}}
    doc = f'arn:aws:ssm:{REGION}:{ACCOUNT}:document/' + (DEPLOY_DOCUMENT if component=='backend' else CHATBOT_DOCUMENT)
    return policy([
        allow('sts:GetCallerIdentity', '*'),
        allow(['rds:DescribeDBSnapshots', 'ssm:GetCommandInvocation', 'ssm:ListCommands'], '*', Condition=regional),
        allow('s3:GetBucketVersioning', f'arn:aws:s3:::{BUCKET}'),
        allow(['s3:GetObject', 's3:GetObjectVersion', 's3:PutObject'],
              [f'arn:aws:s3:::{BUCKET}/artifacts/{component}/*', f'arn:aws:s3:::{BUCKET}/receipts/{component}-cd/*']),
        allow('s3:ListBucket', f'arn:aws:s3:::{BUCKET}', Condition={
            'StringLike': {'s3:prefix': [f'receipts/{component}-cd/*']}}),
        allow('ssm:SendCommand', [doc, f'arn:aws:ec2:{REGION}:{ACCOUNT}:instance/{HOSTS["backend"]}'], Condition=regional),
    ])


def template():
    probe = (Path(__file__).parent / 'inspect_host.py').read_text(encoding='utf-8')
    document = {'schemaVersion': '2.2', 'description': 'Fixed metadata inspection; no secrets or changes',
                'parameters': {'HostKind': {'type':'String','allowedValues':['backend','ocr'],
                    'interpolationType':'ENV_VAR'}}, 'mainSteps': [{'action': 'aws:runShellScript', 'name': 'inspectHost',
                    'inputs': {'timeoutSeconds': '60', 'runCommand': [
                        "python3 -I -S -B - <<'JJIKMUK_INSPECT'\n" + probe + '\nJJIKMUK_INSPECT']}}]}
    resources = {
        'GitHubProvider': {'Type': 'AWS::IAM::OIDCProvider', 'Condition': 'CreateProvider',
            'Properties': {'Url': 'https://token.actions.githubusercontent.com',
                           'ClientIdList': ['sts.amazonaws.com']}},
        'OperationsBucket': {'Type': 'AWS::S3::Bucket', 'DeletionPolicy': 'Retain',
            'UpdateReplacePolicy': 'Retain', 'Properties': {'BucketName': BUCKET,
                'VersioningConfiguration': {'Status': 'Enabled'},
                'BucketEncryption': {'ServerSideEncryptionConfiguration': [
                    {'ServerSideEncryptionByDefault': {'SSEAlgorithm': 'AES256'}}]},
                'OwnershipControls': {'Rules': [{'ObjectOwnership': 'BucketOwnerEnforced'}]},
                'PublicAccessBlockConfiguration': dict(BlockPublicAcls=True, IgnorePublicAcls=True,
                                                       BlockPublicPolicy=True, RestrictPublicBuckets=True)}},
        'BucketPolicy': {'Type': 'AWS::S3::BucketPolicy', 'Properties': {
            'Bucket': {'Ref': 'OperationsBucket'}, 'PolicyDocument': policy([{
                'Effect': 'Deny', 'Principal': '*', 'Action': 's3:*',
                'Resource': [f'arn:aws:s3:::{BUCKET}', f'arn:aws:s3:::{BUCKET}/*'],
                'Condition': {'Bool': {'aws:SecureTransport': 'false'}}}])}},
        'HostArtifactRead': {'Type': 'AWS::IAM::Policy', 'Properties': {
            'PolicyName': 'JjikmukOperationsArtifactRead', 'Roles': [HOST_ROLE],
            'PolicyDocument': policy([allow(['s3:GetObject', 's3:GetObjectVersion'],
                [f'arn:aws:s3:::{BUCKET}/operations/*', f'arn:aws:s3:::{BUCKET}/artifacts/*'])])}},
        'InspectDocument': {'Type': 'AWS::SSM::Document', 'Properties': {
            'Name': READ_DOCUMENT, 'DocumentType': 'Command', 'DocumentFormat': 'JSON', 'Content': document}},
        'BackendDeployDocument': {'Type': 'AWS::SSM::Document', 'Properties': {
            'Name': DEPLOY_DOCUMENT, 'DocumentType': 'Command', 'DocumentFormat': 'JSON',
            'Content': json.loads((Path(__file__).parent/'backend-deploy.ssm.json').read_bytes())}},
        'ChatbotDeployDocument': {'Type':'AWS::SSM::Document','Properties':{
            'Name':CHATBOT_DOCUMENT,'DocumentType':'Command','DocumentFormat':'JSON',
            'Content':chatbot_document()}},
    }
    for key, name, document_policy, subject in [
            ('Read', READ_ROLE, permissions(False), PREFIX + ':ref:refs/heads/main'),
            ('Execute', WRITE_ROLE, permissions(True), PREFIX + ':environment:production'),
            ('BackendAuto', AUTO_ROLE, automatic_backend_permissions(), PREFIX + ':environment:backend-production'),
            ('ChatbotAuto', CHATBOT_ROLE, automatic_backend_permissions('chatbot'), CHATBOT_OIDC_SUBJECT)]:
        resources[key+'Policy'] = {'Type': 'AWS::IAM::ManagedPolicy', 'Properties': {
            'ManagedPolicyName': name+'Policy', 'PolicyDocument': document_policy}}
        resources[key+'Role'] = {'Type': 'AWS::IAM::Role', 'Properties': {
            'RoleName': name, 'MaxSessionDuration': 3600, 'AssumeRolePolicyDocument': trust(subject),
            'ManagedPolicyArns': [{'Ref': key+'Policy'}], 'PermissionsBoundary': {'Ref': key+'Policy'}}}
    return {'AWSTemplateFormatVersion': '2010-09-09',
        'Description': 'Persistent project-scoped GitHub OIDC; no application installation or deployment',
        'Parameters': {'ExistingGitHubProvider': {'Type': 'String', 'AllowedValues': ['true', 'false']}},
        'Conditions': {'CreateProvider': {'Fn::Equals': [{'Ref': 'ExistingGitHubProvider'}, 'false']}},
        'Resources': resources, 'Outputs': {
            'ReadRoleArn': {'Value': {'Fn::GetAtt': ['ReadRole', 'Arn']}},
            'ExecuteRoleArn': {'Value': {'Fn::GetAtt': ['ExecuteRole', 'Arn']}},
            'BackendAutoRoleArn': {'Value': {'Fn::GetAtt': ['BackendAutoRole', 'Arn']}},
            'ChatbotAutoRoleArn': {'Value': {'Fn::GetAtt': ['ChatbotAutoRole', 'Arn']}},
            'Bucket': {'Value': {'Ref': 'OperationsBucket'}}}}


def chatbot_document():
    fields={'ReleaseCommit':'[a-f0-9]{40}','RunId':'[1-9][0-9]{0,19}','RunAttempt':'[1-9][0-9]{0,3}',
        'ArchiveSha256':'[a-f0-9]{64}','ArchiveVersion':'[A-Za-z0-9._~+/-]{1,1024}','ManifestVersion':'[A-Za-z0-9._~+/-]{1,1024}'}
    return {'schemaVersion':'2.2','description':'Fixed reviewed chatbot code deployment',
        'parameters':{k:{'type':'String','allowedPattern':v,'interpolationType':'ENV_VAR'} for k,v in fields.items()},
        'mainSteps':[{'action':'aws:runShellScript','name':'deployChatbot','inputs':{
            'timeoutSeconds':'1800','runCommand':['/usr/bin/python3 -B /opt/jjikmuk-chatbot/bin/deploy_chatbot.py']}}]}


if __name__ == '__main__':
    print(json.dumps(template(), indent=2))
