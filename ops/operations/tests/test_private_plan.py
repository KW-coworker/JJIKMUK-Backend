import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
import zipfile
from private_plan import plan,validate
from private_runner import unpack


class PrivatePlanTests(unittest.TestCase):
    def envelope(self):return dict(format=1,component='db',operation='deploy',approval_id='APPROVAL_123',request_id='a'*32,
        sha256='b'*64,bytes=123,version='version1',expires=int(time.time())+3600,recovery_sha256=None)
    def test_plan_contains_only_envelope_and_fixed_runner(self):
        p=plan(self.envelope())
        self.assertEqual(p['component'],'db');self.assertEqual(p['document']['parameters'],{})
        text=json.dumps(p)
        self.assertNotIn('ALTER TABLE',text);self.assertNotIn('DROP TABLE',text)
        self.assertIn('private_runner.py',text)
    def test_expired_unbounded_or_arbitrary_scope_rejected(self):
        for values in [{'expires':1},{'component':'iam'},{'version':'x;evil'},{'bytes':9*1024**3},{'recovery_sha256':'unsafe'}]:
            with self.assertRaises(ValueError):validate(dict(self.envelope(),**values))
    def test_archive_hash_and_paths_are_checked_before_execution(self):
        for name in ['operation.py','../escape']:
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);archive=root/'package.zip';body=b'pass'
                files={'operation.py':{'sha256':hashlib.sha256(body).hexdigest(),'bytes':4}}
                if name!='operation.py':files[name]=files['operation.py']
                with zipfile.ZipFile(archive,'w') as z:
                    z.writestr('package.json',json.dumps({'format':1,'entrypoint':'operation.py','files':files}))
                    for member in files:z.writestr(member,body)
                if name=='operation.py':self.assertEqual(unpack(archive,root/'payload').read_bytes(),body)
                else:
                    with self.assertRaises(ValueError):unpack(archive,root/'payload')
                    self.assertFalse((root/'payload').exists())
