import json
import time
import unittest
from unittest.mock import Mock
from upload_ticket import issue,open_ticket,object_key,headers,seal,validate_ticket

class UploadTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        public=self.key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        self.binding=dict(request_id='a'*32,commit='b'*40,sha256='c'*64,bytes=12,public_key=public,expires=int(time.time())+1800)
        self.ticket={'url':'https://jjikmuk-operations-076767081522-apne2.s3.ap-northeast-2.amazonaws.com/'+object_key(self.binding)+
            '?X-Amz-SignedHeaders=content-length;content-type;host;if-none-match;x-amz-checksum-sha256;x-amz-expected-bucket-owner;x-amz-server-side-encryption',
            'headers':headers(self.binding),'expires':int(time.time())+900,'run_id':'10','attempt':'1'}
    def test_ciphertext_has_no_url_or_credentials_and_requires_private_key(self):
        sealed=seal(self.binding,self.ticket)
        self.assertNotIn('amazonaws.com',json.dumps(sealed))
        self.assertEqual(open_ticket(self.key,self.binding,sealed),self.ticket)
        changed=dict(self.binding,request_id='d'*32)
        with self.assertRaises(ValueError):open_ticket(self.key,changed,sealed)
        sealed['ciphertext']=sealed['ciphertext'][:-4]+'AAAA'
        with self.assertRaises(Exception):open_ticket(self.key,self.binding,sealed)
    def test_presign_is_one_object_conditional_and_checksum_bound(self):
        s3=Mock();s3.generate_presigned_url.return_value=self.ticket['url']
        issue(s3,self.binding,'10','1')
        params=s3.generate_presigned_url.call_args.kwargs['Params']
        self.assertEqual(params['IfNoneMatch'],'*');self.assertEqual(params['ContentLength'],12)
        self.assertEqual(params['Key'],object_key(self.binding));self.assertIn('ChecksumSHA256',params)

    def test_real_sdk_presign_is_regional_sigv4_and_never_calls_aws(self):
        import boto3
        from run import regional_s3
        sdk=boto3.Session(region_name='ap-northeast-2',aws_access_key_id='offline-fixture',
            aws_secret_access_key='offline-fixture',aws_session_token='offline-fixture')
        client=regional_s3(sdk)
        envelope=issue(client,self.binding,'10','1')
        ticket=open_ticket(self.key,self.binding,envelope)
        self.assertIn('.s3.ap-northeast-2.amazonaws.com/',ticket['url'])
    def test_redirect_wrong_bucket_unsigned_size_and_replay_are_rejected(self):
        for url in [self.ticket['url'].replace('amazonaws.com','attacker.example'),self.ticket['url'].replace('content-length;','')]:
            with self.assertRaises(ValueError):validate_ticket(self.binding,dict(self.ticket,url=url))
        with self.assertRaises(ValueError):issue(Mock(),self.binding,'10','2')
