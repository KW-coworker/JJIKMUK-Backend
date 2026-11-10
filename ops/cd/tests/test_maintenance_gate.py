import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch
from maintenance_gate import Gate, KEY
import test_release as release_tests
from test_release import release_fixture
from release import dispatch


class MemoryS3:
    def __init__(self):
        self.objects = {}; self.writes = []; self.lost = False

    def list_objects_v2(self, **args):
        return {'Contents': [{'Key': key} for key in self.objects if key.startswith(args['Prefix'])]}

    def get_object(self, **args):
        raw = self.objects[args['Key']]
        return {'Body': io.BytesIO(raw), 'ETag': hashlib.sha256(raw).hexdigest()}

    def put_object(self, **args):
        key = args['Key']; previous = self.objects.get(key)
        if args.get('IfNoneMatch') == '*' and previous is not None:
            raise ValueError('PRECONDITION_FAILED')
        if 'IfMatch' in args and (previous is None or hashlib.sha256(previous).hexdigest() != args['IfMatch']):
            raise ValueError('PRECONDITION_FAILED')
        self.objects[key] = args['Body']; self.writes.append(args)
        if self.lost:
            raise TimeoutError('lost reply')


class MaintenanceGateTests(unittest.TestCase):
    def setUp(self):
        self.s3 = MemoryS3(); self.gate = Gate(self.s3)

    def start(self, owner='a'*32):
        self.gate.start(owner, 'b'*40, '100', 'c'*64, 'd'*64)

    def test_success_keeps_hold_until_separate_finish(self):
        self.start()
        with self.assertRaisesRegex(ValueError, 'NOT_VERIFIED'):
            self.gate.admission('a'*32)
        self.gate.verified('a'*32, 'e'*64, 'f'*64)
        self.gate.deployed('a'*32, '1'*40)
        value, _ = self.gate.read()
        self.assertEqual(value['state'], 'VERIFIED')
        with self.assertRaisesRegex(ValueError, 'FINISH_PROOF'):
            self.gate.finish('a'*32, 'e'*64, '9'*64)
        self.gate.finish('a'*32, hashlib.sha256(('1'*40).encode()).hexdigest(), '9'*64)
        self.assertEqual(self.gate.read()[0]['state'], 'OPEN')

    def test_second_owner_cannot_acquire_or_finish(self):
        self.start()
        with self.assertRaisesRegex(ValueError, 'ALREADY_ACTIVE'):
            self.start('b'*32)
        with self.assertRaisesRegex(ValueError, 'OWNER_CHANGED'):
            self.gate.verified('b'*32, 'e'*64, 'f'*64)
        self.assertEqual(self.gate.read()[0]['state'], 'WORKING')

    def test_condition_rejects_stale_writer(self):
        self.start(); value, etag = self.gate.read()
        self.gate.verified('a'*32, 'e'*64, 'f'*64)
        with self.assertRaisesRegex(ValueError, 'WRITE_UNKNOWN'):
            self.gate.write(value, etag)

    def test_old_request_is_not_replayed_after_other_work(self):
        for owner in ['a'*32, 'b'*32]:
            self.start(owner); self.gate.verified(owner, 'e'*64, 'f'*64); self.gate.finish(owner, 'e'*64, '9'*64)
        with self.assertRaisesRegex(ValueError, 'PRECONDITION'):
            self.start('a'*32)
        self.assertEqual(self.gate.read()[0]['request_id'], 'b'*32)

    def test_lost_write_is_not_retried_or_reopened(self):
        self.start(); self.s3.lost = True
        self.gate.verified('a'*32, 'e'*64, 'f'*64)
        self.assertEqual(len(self.s3.writes), 3)
        self.assertEqual(self.gate.read()[0]['state'], 'VERIFIED')

    def test_open_write_reply_lost_is_collected_without_another_write(self):
        self.start(); self.gate.verified('a'*32, 'e'*64, 'f'*64); self.s3.lost = True
        self.gate.finish('a'*32, 'e'*64, '9'*64)
        self.assertEqual(self.gate.read()[0]['state'], 'OPEN')
        self.assertEqual(len(self.s3.writes), 4)

    def test_open_write_and_reads_lost_reports_unknown_not_hold(self):
        self.start(); self.gate.verified('a'*32, 'e'*64, 'f'*64)
        original = self.s3.get_object; calls = 0
        def unavailable(**args):
            nonlocal calls
            calls += 1
            if calls > 1: raise TimeoutError('read lost')
            return original(**args)
        self.s3.lost = True
        with patch.object(self.s3, 'get_object', side_effect=unavailable):
            with self.assertRaisesRegex(ValueError, 'WRITE_UNKNOWN_COLLECT_ONLY'):
                self.gate.finish('a'*32, 'e'*64, '9'*64)
        self.assertEqual(self.gate.read()[0]['state'], 'OPEN')
        self.assertEqual(len(self.s3.writes), 4)

    def test_generic_manual_work_cannot_bypass_hold(self):
        self.start()
        with self.assertRaisesRegex(ValueError, 'BLOCKS_OTHER'):
            self.gate.manual_admission('a'*32, 'repo/.github/workflows/server-operations.yml@refs/heads/main')
        self.gate.manual_admission('a'*32, 'repo/.github/workflows/server-maintenance.yml@refs/heads/main')

    def test_wrong_state_missing_proof_and_extra_fields_fail_closed(self):
        self.start(); value, _ = self.gate.read()
        for bad in [dict(value, state='VERIFIED'), dict(value, extra=True), dict(value, state='EXPIRED')]:
            self.s3.objects[KEY] = json.dumps(bad).encode()
            with self.assertRaises(ValueError): self.gate.read()

    def test_live_push_with_hold_sends_no_command_and_selects_no_backup(self):
        self.start()
        fixture = release_tests.ReleaseTests(); clients = fixture.setup_clients()
        clients['s3'] = self.s3
        with release_fixture(), patch('release.clients', return_value=clients), patch('release.select_snapshot') as snapshot:
            self.assertEqual(dispatch()['status'], 'DEFERRED_MAINTENANCE')
            snapshot.assert_not_called()
        clients['ssm'].send_command.assert_not_called()

    def test_resume_requires_verified_matching_owner_before_any_send(self):
        self.start()
        fixture = release_tests.ReleaseTests(); clients = fixture.setup_clients(); clients['s3'] = self.s3
        with release_fixture(), patch('release.clients', return_value=clients), patch('release.resume_id', return_value='a'*32):
            with self.assertRaisesRegex(ValueError, 'NOT_VERIFIED'): dispatch()
        clients['ssm'].send_command.assert_not_called()

    def test_sdk_accepts_the_exact_conditional_write_request(self):
        from botocore.session import Session
        from botocore.validate import validate_parameters
        model = Session().get_service_model('s3').operation_model('PutObject').input_shape
        self.start(); self.gate.verified('a'*32, 'e'*64, 'f'*64)
        for args in self.s3.writes:
            validate_parameters(args, model)
