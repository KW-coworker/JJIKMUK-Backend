import unittest
from unittest.mock import patch
import inspect_host
from run import operation_succeeded


class TerminalResults(unittest.TestCase):
    def test_recovered_or_failed_deployment_never_reports_success(self):
        for state in ('FAILED','STOPPED','MANUAL_RECOVERY_REQUIRED','ROLLED_BACK','PREFLIGHT_FAILED'):
            with self.subTest(state=state):
                self.assertFalse(operation_succeeded({'status':'Success','response_code':0,'report':{'status':state}}))
        self.assertFalse(operation_succeeded({'status':'Failed','response_code':1,'report':{'status':'SUCCEEDED'}}))
        self.assertTrue(operation_succeeded({'status':'Success','response_code':0,'report':{'status':'VERIFIED'}}))

    def test_backend_inspection_uses_actual_chatbot_unit_and_keeps_inactive_state(self):
        with patch.object(inspect_host,'unit',return_value='inactive') as query:
            result=inspect_host.inspect('backend')
        self.assertIn('food-chatbot-team.service',result['checks'])
        self.assertNotIn('docker.service',result['checks'])
        self.assertFalse(any(result['checks'].values()))
        self.assertEqual(query.call_count,3)

    def test_ocr_does_not_require_backend_services(self):
        with patch.object(inspect_host,'unit',return_value='active'):
            self.assertEqual(inspect_host.inspect('ocr')['checks'],{'docker.service':True})

    def test_unknown_host_rejected(self):
        with self.assertRaises(ValueError): inspect_host.inspect('arbitrary')
