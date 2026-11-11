from unittest.mock import Mock, patch
import unittest
import chatbot_under_hold as flow
from connection import HOSTS


class ChatbotHoldTests(unittest.TestCase):
    def setUp(self):
        self.state = {'request_id': flow.REQUEST, 'state': 'VERIFIED', 'run_id': '43041472793'}
        self.ctx = {'request_id': flow.REQUEST}
        self.plan = {'component': 'chatbot', 'operation': 'install', 'approval_id': 'USER_RESUME_BACKEND_AND_CHATBOT_20261112'}
        self.gate = Mock(); self.gate.read.return_value = (self.state, 'etag')
        self.api = {'s3': Mock(), 'ssm': Mock()}

    def run_flow(self):
        with patch.object(flow, 'Gate', return_value=self.gate), patch.object(flow, 'load_plan', return_value=(self.plan, HOSTS['backend'])), patch.object(flow, 'drained', return_value=True), patch.object(flow, 'execute', return_value={'success': True}) as execute:
            result = flow.perform(self.api, self.ctx, 'fixed-plan', 'a'*64)
            self.assertEqual(execute.call_count, 1)
            self.gate.write.assert_not_called()
            return result

    def test_chatbot_execution_preserves_partial_image_hold(self):
        self.assertTrue(self.run_flow()['image_work_remains_paused'])

    def test_different_operation_scope_cannot_reuse_this_approval(self):
        for field, value in [('component', 'db'), ('approval_id', 'USER_SINGLE_PRODUCT_IMAGE_20261112'), ('operation', 'rollback')]:
            previous = self.plan[field]; self.plan[field] = value
            with self.assertRaisesRegex(ValueError, 'APPROVAL'):
                self.run_flow()
            self.plan[field] = previous

    def test_changed_hold_owner_is_rejected(self):
        self.state['request_id'] = 'b'*32
        with self.assertRaisesRegex(ValueError, 'HOLD_CHANGED'):
            self.run_flow()
