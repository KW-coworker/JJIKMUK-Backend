import base64
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
import upload_private
from upload_ticket import seal,headers,object_key
from connection import REPO,sha


class API:
    token='offline-fixture'
    def __init__(self):self.approved=False;self.dispatches=0
    def call(self,path,method='GET',payload=None):
        if path.endswith('/git/ref/heads/main'):return {'object':{'sha':'b'*40}}
        if path.endswith('/dispatches'):
            self.dispatches+=1;self.binding=json.loads(base64.b64decode(payload['inputs']['binding']));return None
        if '/runs?event=' in path:return {'workflow_runs':[dict(id=12,head_sha='b'*40,head_branch='main',run_attempt=1,
            path='.github/workflows/server-private-upload.yml',display_title='Private upload at '+'b'*40+' ['+self.binding['request_id']+']',
            status='completed' if self.approved else 'in_progress',conclusion='success' if self.approved else None)]}
        if path.endswith('/pending_deployments'):
            if method=='POST':self.approved=True;return {}
            return [] if self.approved else [{'environment':{'id':1,'name':'production'},'current_user_can_approve':True}]
        if path.endswith('/artifacts'):return {'artifacts':[{'id':1,'name':'encrypted-upload-12-1','expired':False}]}
        raise AssertionError(path)
    def ciphertext(self,_):
        ticket={'url':'https://jjikmuk-operations-076767081522-apne2.s3.ap-northeast-2.amazonaws.com/'+object_key(self.binding)+
            '?X-Amz-SignedHeaders=content-length;content-type;host;if-none-match;x-amz-checksum-sha256;x-amz-expected-bucket-owner;x-amz-server-side-encryption',
            'headers':headers(self.binding),'expires':int(time.time())+900,'run_id':'12','attempt':'1'}
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:z.writestr('ticket.json',json.dumps(seal(self.binding,ticket)))
        return stream.getvalue()


class Response:
    status=200
    headers={'x-amz-version-id':'version1'}
    def __enter__(self):return self
    def __exit__(self,*args):pass


class UploadClientTests(unittest.TestCase):
    def fixture(self,root):
        path=root/'private.zip';path.write_bytes(b'private bytes never on GitHub')
        return path,dict(status='APPROVED',sha256=sha(path.read_bytes()),bytes=path.stat().st_size,commit='b'*40,expires=int(time.time())+1800)
    def test_user_approval_drives_github_review_then_direct_private_upload(self):
        api=API();sent=[]
        class Opener:
            def open(self,request,timeout):sent.append(request.data.read());return Response()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,approval=self.fixture(root)
            with patch('notify.GitHub.artifact',side_effect=api.ciphertext),patch('upload_private.urllib.request.build_opener',return_value=Opener()):
                result=upload_private.run(api,path,approval,root/'journal.json',lambda _:None)
            self.assertEqual(sent,[path.read_bytes()]);self.assertTrue(api.approved);self.assertEqual(api.dispatches,1)
            self.assertEqual(result['version'],'version1')
            journal=(root/'journal.json').read_text()
            self.assertNotIn('PRIVATE KEY',journal);self.assertNotIn('X-Amz-Signature',journal);self.assertNotIn('private bytes',journal)
    def test_wrong_approval_stops_before_dispatch(self):
        api=API()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,approval=self.fixture(root);approval['sha256']='0'*64
            with self.assertRaises(ValueError):upload_private.run(api,path,approval,root/'journal.json')
            self.assertEqual(api.dispatches,0)
    def test_lost_put_response_preserves_intent_and_blocks_replay(self):
        api=API()
        class Opener:
            def open(self,*args,**kwargs):raise TimeoutError()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path,approval=self.fixture(root);journal=root/'journal.json'
            with patch('notify.GitHub.artifact',side_effect=api.ciphertext),patch('upload_private.urllib.request.build_opener',return_value=Opener()):
                with self.assertRaises(TimeoutError):upload_private.run(api,path,approval,journal,lambda _:None)
            self.assertEqual(json.loads(journal.read_text())['status'],'PUT_INTENT')
            with self.assertRaisesRegex(ValueError,'NO_REPLAY'):upload_private.run(api,path,approval,journal)
            self.assertEqual(api.dispatches,1)
