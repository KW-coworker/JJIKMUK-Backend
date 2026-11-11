import copy
import ast,os,subprocess,sys
import unittest
from unittest.mock import Mock,patch
import catalog_recovery_inspection as inspection
from connection import canonical,sha


class InspectionTests(unittest.TestCase):
    def fixture(self):
        return {'binding':{'archive_sha256':'a'*64},'envelope':{'files':{}}}

    def test_fixed_receipt_rejects_altered_data(self):
        with self.assertRaisesRegex(ValueError,'RECEIPT_CHANGED'):
            inspection.document(self.fixture())

    def test_read_document_compiles_and_keeps_recovery_stopped(self):
        saved=self.fixture()
        with patch.object(inspection,'RECEIPT_SHA',sha(canonical(saved))):doc=inspection.document(saved)
        text=doc['mainSteps'][0]['inputs']['runCommand'][0]
        compile(text.split('\n',1)[1].rsplit('\n',1)[0],'<fixed-read>','exec')
        self.assertIn("state_coord.get('status')=='MANUAL_RECOVERY_REQUIRED'",text)
        self.assertIn("mode=ro",text)
        self.assertIn("work.host.verify(work.state['previous'],'')",text)
        self.assertNotIn('host.commit(',text)
        self.assertNotIn("systemctl('start'",text)
        self.assertNotIn("systemctl('stop'",text)
        self.assertNotIn('UPDATE ',text)

    def test_wrong_gate_or_request_never_sends_command(self):
        api={'s3':Mock()}
        for request,state in [('b'*32,'WORKING'),(inspection.REQUEST,'OPEN')]:
            with patch.object(inspection,'Gate') as gate,patch.object(inspection,'execute') as execute:
                gate.return_value.read.return_value=({'request_id':inspection.REQUEST,'run_id':inspection.RUN,'state':state},'etag')
                with self.assertRaisesRegex(ValueError,'CATALOG_INSPECTION_'):
                    inspection.inspect(api,{'request_id':request})
                execute.assert_not_called()

    def test_exact_request_checks_receipt_before_execute(self):
        api={'s3':Mock()};ctx={'request_id':inspection.REQUEST,'commit':'c'*40}
        with patch.object(inspection,'Gate') as gate,patch.object(inspection,'execute') as execute,patch.object(inspection,'read_object',return_value=self.fixture()):
            gate.return_value.read.return_value=({'request_id':inspection.REQUEST,'run_id':inspection.RUN,'state':'WORKING'},'etag')
            with self.assertRaisesRegex(ValueError,'RECEIPT_CHANGED'):inspection.inspect(api,ctx)
            execute.assert_not_called()

    @unittest.skipUnless(os.name=='posix','Linux alarm boundary')
    def test_outer_deadline_escapes_repeated_health_exception_handling(self):
        saved=self.fixture()
        with patch.object(inspection,'RECEIPT_SHA',sha(canonical(saved))):doc=inspection.document(saved)
        text=doc['mainSteps'][0]['inputs']['runCommand'][0].split('\n',1)[1].rsplit('\n',1)[0]
        tree=ast.parse(text)
        definitions=[node for node in tree.body if isinstance(node,(ast.ClassDef,ast.FunctionDef))]
        prefix=ast.unparse(ast.Module(body=definitions,type_ignores=[]))
        code='import signal,time\n'+prefix+'''\nsignal.signal(signal.SIGALRM,deadline)
signal.alarm(1)
try:
 while True:
  try:time.sleep(0.1);raise ValueError('unhealthy')
  except Exception:pass
except InspectionDeadline:print('SAFE_DEADLINE_REPORTED')
'''
        run=subprocess.run([sys.executable,'-I','-S','-B','-c',code],capture_output=True,text=True,timeout=5)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(run.stdout.strip(),'SAFE_DEADLINE_REPORTED')
        self.assertGreater(int(doc['mainSteps'][0]['inputs']['timeoutSeconds']),420)


if __name__=='__main__':unittest.main()
