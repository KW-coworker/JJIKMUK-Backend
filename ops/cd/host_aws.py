"""Use only the existing EC2 role, never local AWS profiles or exported keys."""
import json,os,subprocess
from manifest import require

HOST_ARN='arn:aws:sts::076767081522:assumed-role/JjikmukMigrationHost/i-06350403fe0400e1b'


def command(args,timeout=30):
    env={k:v for k,v in os.environ.items() if not k.startswith('AWS_') and k!='BOTO_CONFIG'}
    env.update(AWS_CONFIG_FILE='/dev/null',AWS_SHARED_CREDENTIALS_FILE='/dev/null',BOTO_CONFIG='/dev/null',
        AWS_EC2_METADATA_V1_DISABLED='true',AWS_EC2_METADATA_DISABLED='false',AWS_MAX_ATTEMPTS='1',AWS_PAGER='')
    result=subprocess.run(args,capture_output=True,text=True,timeout=timeout,check=False,env=env)
    require(result.returncode==0,'HOST_AWS_COMMAND_FAILED')
    return result.stdout.strip()


def require_identity(executable,region):
    value=json.loads(command([executable,'sts','get-caller-identity','--region',region,'--output','json']))
    require(value.get('Account')=='076767081522' and value.get('Arn')==HOST_ARN,'HOST_ROLE_IDENTITY_CHANGED')
