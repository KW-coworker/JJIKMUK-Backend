import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from install_disabled import install,inspect_payload


def payload(root,change=None):
    config={'enabled':False,'root':'/opt/jjikmuk-cd','service':'jjikmuk-backend.service'}
    files={'config.json':json.dumps(config).encode(),'bin/example.py':b'pass\n','vendor/pinned.whl':b'fake'}
    if change:change(files)
    m={'format':1,'repository':'KW-coworker/JJIKMUK-Backend','commit':'a'*40,'source_ref':'refs/heads/main',
       'files':[{'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'executable':False} for name,data in files.items()]}
    raw=json.dumps(m).encode();dest=root/'payload.zip'
    with zipfile.ZipFile(dest,'w') as z:
        z.writestr('install-manifest.json',raw)
        for n,data in files.items():z.writestr(n,data)
    return dest,hashlib.sha256(raw).hexdigest()


class InstallTests(unittest.TestCase):
    def test_disk_reserve_before_any_write(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);archive,sha=payload(p)
            from types import SimpleNamespace
            with patch('install_disabled.shutil.disk_usage',return_value=SimpleNamespace(free=0)),self.assertRaisesRegex(ValueError,'INSTALL_DISK_RESERVE_REQUIRED'):
                install(archive,sha,'a'*40,p/'cd',p/'settings',lambda _:None)
            self.assertFalse((p/'cd').exists())

    def test_install_is_disabled_exclusive_and_has_no_service_calls(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);archive,sha=payload(p);root=p/'cd';settings=p/'settings'
            result=install(archive,sha,'a'*40,root,settings,lambda _:None)
            self.assertEqual('INSTALLED_DISABLED',result['status'])
            self.assertFalse(json.loads((settings/'config.json').read_text())['enabled'])
            self.assertFalse((root/'current').exists());self.assertFalse((root/'baseline.json').exists())
            with self.assertRaisesRegex(ValueError,'INSTALL_TARGET_EXISTS'):install(archive,sha,'a'*40,root,settings,lambda _:None)

    def test_hash_traversal_hook_and_wrong_main_stop_before_creating_paths(self):
        for change in (lambda f:f.update({'../escape':b'x'}),lambda f:f.update({'vendor/evil.pth':b'x'}),
                       lambda f:f.update({'config.json':b'{"enabled":true,"root":"/opt/jjikmuk-cd","service":"jjikmuk-backend.service"}'})):
            with tempfile.TemporaryDirectory() as td:
                p=Path(td);archive,sha=payload(p,change)
                with self.assertRaises(ValueError):install(archive,sha,'a'*40,p/'cd',p/'settings',lambda _:None)
                self.assertFalse((p/'cd').exists())

    def test_partial_failure_preserves_journal_and_blocks_retry(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);archive,sha=payload(p);original=Path.open
            def fail(path,*a,**k):
                if path.name=='example.py' and a and a[0]=='xb':raise OSError('injected')
                return original(path,*a,**k)
            with patch.object(Path,'open',fail),self.assertRaises(OSError):install(archive,sha,'a'*40,p/'cd',p/'settings',lambda _:None)
            self.assertEqual('STOPPED_KEEP_FILES_NO_RETRY',json.loads((p/'cd/install-journal.json').read_text())['status'])
            with self.assertRaisesRegex(ValueError,'INSTALL_TARGET_EXISTS'):install(archive,sha,'a'*40,p/'cd',p/'settings',lambda _:None)
