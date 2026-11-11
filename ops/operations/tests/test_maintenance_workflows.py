from pathlib import Path
import re
import unittest


class MaintenanceWorkflowTests(unittest.TestCase):
    def test_mutating_workflows_share_non_cancelling_full_queue(self):
        root = Path(__file__).resolve().parents[3] / '.github/workflows'
        names = ['backend-cd.yml', 'server-maintenance.yml', 'server-operations.yml',
                 'backend-initial-db.yml', 'backend-initial-activation.yml']
        for name in names:
            with self.subTest(name=name):
                source = (root/name).read_text(encoding='utf-8')
                self.assertIn('concurrency:\n  group: backend-production-deployment\n  cancel-in-progress: false\n  queue: max\n', source)
                self.assertEqual(len(re.findall(r'^\s*queue:', source, re.M)), 1)

    def test_readonly_collection_and_resume_use_fixed_workflows_without_new_credentials(self):
        root = Path(__file__).resolve().parents[3]
        maintenance = (root/'.github/workflows/server-maintenance.yml').read_text(encoding='utf-8')
        self.assertIn('options: [apply, rehearse, finish, collect, catalog]', maintenance)
        self.assertIn('environment: production', maintenance)
        self.assertIn('role/JjikmukOperationsExecute', maintenance)
        self.assertNotIn('secrets.', maintenance)
