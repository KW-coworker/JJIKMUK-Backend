import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from package import manifest,compatible,unpack,sha

class PackageTests(unittest.TestCase):
    def fixture(self):return {'app/api/main.py':b'original','app/start.py':b'start','requirements.txt':b'fixed','migrations/1.sql':b'schema','app/knowledge/a.txt':b'facts'}
    def make(self,files):return manifest(files,'a'*40,'21','1')
    def test_code_allowed_but_schema_runtime_rag_rejected(self):
        before=self.make(self.fixture())
        for name in ['migrations/1.sql','requirements.txt','app/knowledge/a.txt','app/reference_sources/a.txt','app/infrastructure/rag.py']:
            files=self.fixture();files[name]=b'changed'
            with self.assertRaises(ValueError):compatible(before,self.make(files))
        files=self.fixture();files['app/api/main.py']=b'fix'
        compatible(before,self.make(files))
    def test_exact_archive_and_manifest_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'source.zip';files=self.fixture();m=self.make(files)
            with zipfile.ZipFile(path,'w') as z:
                for n,b in files.items():z.writestr(n,b)
            m.update(archive_sha256=sha(path.read_bytes()),archive_bytes=path.stat().st_size)
            unpack(path,m,root/'good');self.assertEqual((root/'good/app/api/main.py').read_bytes(),b'original')
            m['files']['app/api/main.py']['sha256']='0'*64
            with self.assertRaises(ValueError):unpack(path,m,root/'bad')
            self.assertFalse((root/'bad').exists())
    def test_secrets_symlinks_traversal_and_bytecode_not_packaged(self):
        for name in ['../escape','.env','app/.env','app/x.pyc','C:/file','app\\x.py']:
            files=self.fixture();files[name]=b'x'
            with self.assertRaises(ValueError):self.make(files)
