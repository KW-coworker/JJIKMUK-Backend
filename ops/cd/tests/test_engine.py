import unittest
from engine import deploy


class FakeHost:
    def __init__(self):
        self.current = 'old'
        self.baseline = 'old'
        self.journal = {}
        self.restarts = 0
        self.failure = ''

    def existing(self, request):
        if self.journal:
            if self.journal['status'] == 'SUCCEEDED' and self.current == request: return self.journal
            raise ValueError('UNRESOLVED_OR_REPEATED_RUN')

    def prepare(self, request): return request
    def preflight(self, previous, candidate):
        if self.failure == 'preflight': raise ValueError('PREFLIGHT_FAILED')
    def identity(self): return str(self.restarts)
    def record(self, request, status): self.journal = {'request': request, 'status': status}
    def activate(self, release): self.current = release
    def restart(self):
        self.restarts += 1
        if self.failure == 'restart' and self.current == 'new': raise ValueError('RESTART_FAILED')
    def verify(self, release, old_identity):
        if self.failure == 'health' and release == 'new': raise ValueError('HEALTH_FAILED')
        if self.failure == 'rollback' and release == 'old': raise ValueError('ROLLBACK_FAILED')
        if self.failure == 'rollback' and release == 'new': raise ValueError('HEALTH_FAILED')
        assert self.current == release and self.identity() != old_identity
    def rollback_preflight(self, previous, candidate):
        if self.failure == 'db_changed': raise ValueError('DB_CHANGED')
    def commit(self, release): self.baseline = release


class EngineTests(unittest.TestCase):
    def test_success_and_same_run_do_not_restart_twice(self):
        h = FakeHost()
        self.assertEqual('SUCCEEDED', deploy(h, 'new')['status'])
        self.assertEqual('new', h.baseline)
        deploy(h, 'new')
        self.assertEqual(1, h.restarts)

    def test_preflight_failure_leaves_current_untouched(self):
        h = FakeHost(); h.failure = 'preflight'
        with self.assertRaises(ValueError): deploy(h, 'new')
        self.assertEqual(('old', 0), (h.current, h.restarts))

    def test_restart_and_health_failure_restore_old_release(self):
        for failure in ['restart', 'health']:
            h = FakeHost(); h.failure = failure
            self.assertEqual('ROLLED_BACK', deploy(h, 'new')['status'])
            self.assertEqual(('old', 'old', 2), (h.current, h.baseline, h.restarts))

    def test_failed_rollback_requires_human_recovery(self):
        h = FakeHost(); h.failure = 'rollback'
        self.assertEqual('MANUAL_RECOVERY_REQUIRED', deploy(h, 'new')['status'])

    def test_unknown_interrupted_run_is_not_replayed(self):
        h = FakeHost(); h.journal = {'request': 'earlier', 'status': 'SWITCH_INTENT'}
        with self.assertRaises(ValueError): deploy(h, 'new')
        self.assertEqual(0, h.restarts)


if __name__ == '__main__': unittest.main()
