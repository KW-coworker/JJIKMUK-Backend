import unittest
from bootstrap_document import document


class BootstrapDocumentTests(unittest.TestCase):
    def test_document_has_no_parameters_and_checks_independent_hashes(self):
        d=document('approved-bucket','backend-bootstrap/'+'a'*64+'/payload.zip','a'*64,'b'*64,'c'*64,'d'*40)
        self.assertEqual({},d['parameters'])
        self.assertEqual('aws:downloadContent',d['mainSteps'][1]['action'])
        source=d['mainSteps'][2]['inputs']['runCommand'][0]
        for digest in ('a'*64,'b'*64,'c'*64):self.assertIn(digest,source)
        self.assertNotIn('systemctl',source)
        for step in (d['mainSteps'][0],d['mainSteps'][2]):
            code=step['inputs']['runCommand'][0].split("<<'FIXED_CD_BOOTSTRAP'\n",1)[1].rsplit('\nFIXED_CD_BOOTSTRAP',1)[0]
            compile(code,'fixed_bootstrap','exec')

    def test_shell_injection_paths_and_other_key_are_refused(self):
        for bucket,key in [('bucket;bad','backend-bootstrap/'+'a'*64+'/payload.zip'),
                           ('approved-bucket','backend-bootstrap/'+'b'*64+'/payload.zip')]:
            with self.assertRaises(ValueError):document(bucket,key,'a'*64,'b'*64,'c'*64,'d'*40)
