import unittest
from unittest.mock import Mock, patch
from host import Host

class Clock:
    def __init__(self):self.now=0
    def time(self):return self.now
    def sleep(self,seconds):self.now+=seconds

class StabilityTests(unittest.TestCase):
    def host(self):
        host=Host.__new__(Host)
        host.config={'health_checks':[{'kind':'public'}]}
        host.identity=Mock(return_value='new')
        host.runtime=Mock();host.database=Mock()
        return host

    def test_one_healthy_probe_is_not_enough(self):
        host=self.host();clock=Clock()
        with patch('host.time.monotonic',side_effect=clock.time),patch('host.time.sleep',side_effect=clock.sleep),patch('host.http_check'):
            host.verify({'manifest':{}},'old')
        self.assertGreaterEqual(clock.now,60)
        self.assertGreaterEqual(host.runtime.call_count,13)

    def test_intermittent_failure_restarts_stability_window(self):
        host=self.host();clock=Clock()
        def check(_):
            if clock.now==30:raise ValueError('HTTP_STATUS')
        with patch('host.time.monotonic',side_effect=clock.time),patch('host.time.sleep',side_effect=clock.sleep),patch('host.http_check',side_effect=check):
            host.verify({'manifest':{}},'old')
        self.assertEqual(95,clock.now)

    def test_initial_success_then_failure_does_not_pass(self):
        host=self.host();clock=Clock()
        def check(_):
            if clock.now>=20:raise ValueError('HTTP_STATUS')
        with patch('host.time.monotonic',side_effect=clock.time),patch('host.time.sleep',side_effect=clock.sleep),patch('host.http_check',side_effect=check):
            with self.assertRaisesRegex(ValueError,'HEALTH_DEADLINE'):host.verify({'manifest':{}},'old')
        self.assertEqual(240,clock.now)

    def test_restart_during_stability_requires_a_new_window(self):
        host=self.host();clock=Clock()
        host.identity.side_effect=lambda:'new' if clock.now<30 else 'restarted'
        with patch('host.time.monotonic',side_effect=clock.time),patch('host.time.sleep',side_effect=clock.sleep),patch('host.http_check'):
            host.verify({'manifest':{}},'old')
        self.assertEqual(90,clock.now)

    def test_delayed_older_command_cannot_overwrite_newer_release(self):
        host=self.host()
        for run in ('8','9'):
            with self.subTest(run=run),self.assertRaisesRegex(ValueError,'STALE_RELEASE_RUN'):
                host.preflight({'manifest':{'run_id':'9'}},{'manifest':{'run_id':run}})
        host.runtime.assert_not_called();host.database.assert_not_called()

