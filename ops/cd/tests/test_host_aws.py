import json,unittest
from unittest.mock import patch,Mock
import host_aws


class HostIdentityTests(unittest.TestCase):
    def test_local_credentials_and_alternate_endpoints_are_excluded(self):
        inherited={'AWS_ACCESS_KEY_ID':'synthetic','AWS_SECRET_ACCESS_KEY':'synthetic',
            'AWS_WEB_IDENTITY_TOKEN_FILE':'/fake','AWS_PROFILE':'admin','AWS_ENDPOINT_URL':'https://fake',
            'AWS_CONTAINER_CREDENTIALS_FULL_URI':'http://fake','AWS_EC2_METADATA_SERVICE_ENDPOINT':'http://fake',
            'AWS_CONFIG_FILE':'/fake','BOTO_CONFIG':'/fake','PATH':'/usr/bin'}
        with patch.dict(host_aws.os.environ,inherited,clear=True),patch.object(host_aws.subprocess,'run',return_value=Mock(returncode=0,stdout='{}')) as call:
            host_aws.command(['fixed-aws','sts','get-caller-identity'])
        env=call.call_args.kwargs['env']
        for key in inherited:
            if key.startswith('AWS_') and key!='AWS_CONFIG_FILE':self.assertNotIn(key,env)
        self.assertEqual(env['AWS_CONFIG_FILE'],'/dev/null')
        self.assertEqual(env['AWS_SHARED_CREDENTIALS_FILE'],'/dev/null')
        self.assertEqual(env['BOTO_CONFIG'],'/dev/null')
        self.assertEqual(env['AWS_EC2_METADATA_V1_DISABLED'],'true')

    def test_unexpected_role_is_rejected(self):
        for arn in (host_aws.HOST_ARN,'arn:aws:iam::076767081522:root'):
            with patch.object(host_aws,'command',return_value=json.dumps({'Account':'076767081522','Arn':arn})):
                if arn==host_aws.HOST_ARN:host_aws.require_identity('fixed-aws','ap-northeast-2')
                else:
                    with self.assertRaisesRegex(ValueError,'IDENTITY_CHANGED'):host_aws.require_identity('fixed-aws','ap-northeast-2')


if __name__=='__main__':unittest.main()
