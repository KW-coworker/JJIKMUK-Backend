import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import zipfile

from backend_initial_document import plan
import backend_initial_observe as observe
from initial_contract import config, ENV_FILES, OLD_SHA
from run import load_plan, safe_report

ROOT = Path(__file__).resolve().parents[3]


class InitialObservationTests(unittest.TestCase):
    def test_plan_is_fixed_and_bounded(self):
        value = plan(ROOT)
        self.assertTrue(value['approved'])
        self.assertEqual({}, value['document']['parameters'])
        self.assertLess(len(json.dumps(value).encode()), 60000)
        text = json.dumps(value)
        self.assertNotIn('restart', value['document']['description'])
        self.assertNotIn('send_command', text)

    def run_observation(self, *, env_files=None, change=False, failing_health=False):
        h = MagicMock()
        h.protected.side_effect = [{'protected': [0, 0, 384, 'a' * 64]},
                                    {'changed': []} if change else {'protected': [0, 0, 384, 'a' * 64]}]
        h.unit.return_value = ' '.join(p + ' (ignore_errors=no)' for p in (ENV_FILES if env_files is None else env_files))
        h.environment.return_value = 'b' * 64
        inputs = (('42', b'args', b'1'), b'private-env', b'private-props', {}, {})
        old = {'migrations': [], 'configuration': {'BOOT-INF/classes/application.properties': 'c' * 64}}
        with patch.object(observe.Host, '__new__', return_value=h), \
             patch.object(observe.probe, 'database_inputs', return_value=inputs), \
             patch.object(observe.probe, 'jar_digest', return_value=OLD_SHA), \
             patch.object(observe.probe, 'unchanged'), \
             patch.object(observe, 'content_profile', return_value=old), \
             patch.object(observe, 'http_check', side_effect=ValueError('HTTP_STATUS') if failing_health else None):
            return observe.observe(old)

    def test_private_values_are_not_reported(self):
        report = self.run_observation()
        self.assertTrue(report['checks']['observation_stable'])
        self.assertEqual(report, safe_report(json.dumps(report)))
        self.assertNotIn('private-', json.dumps(report))

    def test_changed_reference_or_input_stops(self):
        with self.assertRaisesRegex(ValueError, 'ENV_FILE_SET_CHANGED'):
            self.run_observation(env_files=ENV_FILES[:-1])
        with self.assertRaisesRegex(ValueError, 'OBSERVATION_CHANGED'):
            self.run_observation(change=True)

    def test_health_failures_are_visible_without_raw_error(self):
        report = self.run_observation(failing_health=True)
        self.assertFalse(report['checks']['health_public'])
        self.assertNotIn('HTTP_STATUS', json.dumps(report))

    def test_config_is_disabled_and_independent(self):
        a = config()
        a['database']['expected_jdbc_url'] = 'private'
        self.assertFalse(a['enabled'])
        self.assertEqual('HOST_ONLY_EXISTING_JDBC', config()['database']['expected_jdbc_url'])


if __name__ == '__main__':
    unittest.main()
