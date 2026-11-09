"""Service-compatible regex regression: Python and CFN lint miss Go repeat limits."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from connection import template


class SsmRegexTests(unittest.TestCase):
    def test_all_ssm_patterns_compile_in_go_and_keep_version_contract(self):
        root = Path(__file__).resolve().parents[3]
        documents = {name: item['Properties']['Content']
                     for name, item in template()['Resources'].items()
                     if item['Type'] == 'AWS::SSM::Document'}
        documents.update({str(p.relative_to(root)): json.loads(p.read_bytes())
                          for p in (root / 'ops').rglob('*.ssm.json')})
        patterns = []
        version_count = 0
        alphabet = 'Az09._~+/-'
        for name, document in documents.items():
            for parameter, spec in document.get('parameters', {}).items():
                if 'allowedPattern' not in spec:
                    continue
                samples = []
                if parameter.endswith('Version'):
                    version_count += 1
                    for size in (0, 1, 24, 999, 1000, 1001, 1023, 1024, 1025):
                        value = (alphabet * 103)[:size]
                        samples.append({'Value': value, 'Match': 1 <= size <= 1024})
                    for invalid in ('\n', '\r', ' ', '"', "'", '\\', '\x00', '한'):
                        samples.append({'Value': 'a' + invalid + 'b', 'Match': False})
                    for size in range(1027):
                        value = 'a' * size
                        self.assertEqual(bool(re.fullmatch('[A-Za-z0-9._~+/-]{1,1024}', value)),
                                         bool(re.fullmatch(spec['allowedPattern'], value)),
                                         (name, parameter, size))
                patterns.append({'Name': name + '/' + parameter,
                                 'Pattern': spec['allowedPattern'], 'Samples': samples})
        self.assertGreaterEqual(version_count, 6)
        go = os.environ.get('SSM_TEST_GO') or shutil.which('go')
        self.assertTrue(go, 'Go is required: do not skip native SSM regex validation')
        result = subprocess.run([go, 'run', str(Path(__file__).with_name('ssm_regex.go'))],
                                input=json.dumps(patterns), text=True, capture_output=True,
                                timeout=120, env={**os.environ, 'GO111MODULE': 'off',
                                                 'GOPROXY': 'off', 'GOTOOLCHAIN': 'local',
                                                 'GOTELEMETRY': 'off'})
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn('GO_SSM_PATTERNS_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
