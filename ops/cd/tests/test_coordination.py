import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import coordination as c


@unittest.skipUnless(os.name=='posix','Linux host lock and durable fsync semantics')
class SharedCoordination(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'coordinator'
        with patch.object(c,'secure'):
            c.initialize(self.root)
        self.owner=os.geteuid()

    def tearDown(self): self.tmp.cleanup()

    def test_all_components_contend_for_same_lock(self):
        with c.locked('backend','1'*64,root=self.root,owner=self.owner) as guard:
            script='''import sys;sys.path.insert(0,sys.argv[1]);import coordination as c
try:
    with c.locked('chatbot','2'*64,root=sys.argv[2],owner=int(sys.argv[3])):pass
except ValueError as e:
    assert str(e)=='HOST_OPERATION_BUSY';sys.exit(0)
sys.exit(2)
'''
            child=subprocess.run([sys.executable,'-B','-c',script,str(Path(c.__file__).parent),str(self.root),str(self.owner)],capture_output=True)
            self.assertEqual(child.returncode,0,child.stderr)
            guard.record('SUCCEEDED')

    def test_crash_after_mutation_blocks_other_component(self):
        with self.assertRaises(RuntimeError):
            with c.locked('db','3'*64,root=self.root,owner=self.owner) as guard:
                guard.record('MUTATION_INTENT');raise RuntimeError('lost worker')
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_HOST_OPERATION'):
            with c.locked('chatbot','4'*64,root=self.root,owner=self.owner):pass
        raw=(self.root/'state.json').read_bytes()
        with c.locked('db','5'*64,root=self.root,owner=self.owner,recovery_sha256=hashlib.sha256(raw).hexdigest()) as guard:
            guard.record('VERIFIED')

    def test_preflight_refusal_allows_new_operation_but_not_replay(self):
        with self.assertRaises(ValueError):
            with c.locked('chatbot','6'*64,root=self.root,owner=self.owner):raise ValueError('schema')
        self.assertEqual(json.loads((self.root/'state.json').read_text())['status'],'REJECTED')
        with self.assertRaisesRegex(ValueError,'NO_REPLAY'):
            with c.locked('chatbot','6'*64,root=self.root,owner=self.owner):pass
        with c.locked('backend','7'*64,root=self.root,owner=self.owner) as guard:guard.record('SUCCEEDED')

    def test_missing_completion_does_not_turn_green(self):
        with self.assertRaisesRegex(ValueError,'COMPLETION'):
            with c.locked('ocr','8'*64,root=self.root,owner=self.owner):pass

    def test_failed_recovery_never_clears_original_hold(self):
        with self.assertRaises(RuntimeError):
            with c.locked('db','9'*64,root=self.root,owner=self.owner) as g:
                g.record('MUTATION_INTENT');raise RuntimeError('interrupted')
        old=hashlib.sha256((self.root/'state.json').read_bytes()).hexdigest()
        with self.assertRaises(RuntimeError):
            with c.locked('db','a'*64,root=self.root,owner=self.owner,recovery_sha256=old):
                raise RuntimeError('recovery preflight failed')
        state=json.loads((self.root/'state.json').read_text())
        self.assertEqual(state['recovery_of'],old)
        self.assertEqual(state['status'],'MANUAL_RECOVERY_REQUIRED')
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_HOST_OPERATION'):
            with c.locked('backend','b'*64,root=self.root,owner=self.owner):pass
