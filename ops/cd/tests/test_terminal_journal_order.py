from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from host import Host,read_host_state,atomic_json


class JournalOrdering(unittest.TestCase):
    def test_large_protected_baseline_and_transition_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp,patch('host.secure'):
            path=Path(temp)/'state.json'
            baseline={'protected':{f'/fixed/distribution/library/{i}/module.py':[0,0,33188,'a'*64] for i in range(7600)}}
            atomic_json(path,baseline)
            self.assertGreater(path.stat().st_size,128*1024)
            self.assertEqual(read_host_state(path),baseline)
            transition={'status':'SWITCH_INTENT','transition':{'previous':baseline,'candidate':baseline}}
            atomic_json(path,transition);self.assertEqual(read_host_state(path),transition)
    def test_terminal_component_write_failure_preserves_global_hold(self):
        with tempfile.TemporaryDirectory() as temp:
            host=object.__new__(Host);host.root=Path(temp);host.transition={};host.coordinator=Mock()
            with patch('host.atomic_json',side_effect=OSError('disk failed')):
                with self.assertRaises(OSError):host.record({'run_key':'1-1'},'SUCCEEDED')
            host.coordinator.record.assert_not_called()
    def test_mutation_intent_precedes_component_write(self):
        host=object.__new__(Host);host.root=Path('unused');host.transition={};host.coordinator=Mock()
        with patch('host.atomic_json',side_effect=OSError('disk failed')):
            with self.assertRaises(OSError):host.record({'run_key':'1-1'},'SWITCH_INTENT')
        host.coordinator.record.assert_called_once_with('SWITCH_INTENT')
