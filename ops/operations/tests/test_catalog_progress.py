import io,json,tempfile,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import Mock,patch
from catalog_progress import Progress,valid,identity,safe_error,read_fixed
from catalog_progress_reader import Reader,document
from catalog_progress_github import Reporter
from connection import ACCOUNT,HOSTS


def binding():return {'run_id':'123456789','commit':'a'*40,'archive_sha256':'b'*64,'request_id':'c'*32}


class ProgressTests(unittest.TestCase):
    def test_counts_are_throttled_and_activity_is_not_progress(self):
        with tempfile.TemporaryDirectory() as root:
            clock=[1000];p=Progress(root,binding(),'freeze',clock=lambda:clock[0])
            p.update('BASELINE',0,100);clock[0]=1001;p.update('BASELINE',10,100)
            self.assertEqual(json.loads(p.path.read_bytes())['done'],0)
            clock[0]=1011;p.update();value=json.loads(p.path.read_bytes())
            self.assertEqual((value['done'],value['written_epoch'],value['advanced_epoch']),(10,1011,1001))
            valid(value,identity(binding(),'freeze'))
            for bad in (dict(value,secret='never output'),dict(value,run_id='999'),dict(value,done=101),dict(value,error_code='password=secret')):
                with self.assertRaises(ValueError):valid(bad,identity(binding(),'freeze'))

    def test_progress_write_failure_does_not_break_work(self):
        with tempfile.TemporaryDirectory() as root,patch('catalog_progress.os.replace',side_effect=OSError('synthetic')):
            p=Progress(root,binding(),'apply');p.update('PRODUCT_APPLY',500,1000)
            self.assertTrue(p.failed)

    def test_private_path_and_errors_are_bounded(self):
        with self.assertRaisesRegex(ValueError,'PROGRESS_PATH'):read_fixed('/etc/passwd',identity(binding(),'freeze'))
        self.assertEqual(safe_error(ValueError('SNAPSHOT_WAIT_LIMIT_NO_RECREATE')),'SNAPSHOT_WAIT_LIMIT_NO_RECREATE')
        self.assertEqual(safe_error(ValueError('secret password=fixture')),'VALUEERROR')
        error=RuntimeError('secret');error.response={'Error':{'Code':'AccessDenied','Message':'secret'}}
        self.assertEqual(safe_error(error),'AWS_ACCESSDENIED')

    def test_fixed_reader_document_compiles_and_uses_only_bound_file(self):
        doc=document(binding(),'freeze');script=doc['mainSteps'][0]['inputs']['runCommand'][0]
        code=script.split('\n',1)[1].rsplit('JJIKMUK_PROGRESS_READ',1)[0]
        compile(code,'fixed-progress-reader','exec')
        self.assertIn('/opt/jjikmuk-catalog-'+('b'*16),code)
        self.assertIn('"progress":read_fixed(',code)
        self.assertNotIn('from coordination',code);self.assertNotIn('pymysql',code)

    def reader(self,root):
        ssm=Mock();reporter=Mock(folder=Path(root));clock=[1000]
        reader=Reader(ssm,binding(),'freeze',reporter,clock=lambda:clock[0])
        ssm.describe_document.return_value={'Document':{'Owner':ACCOUNT,'LatestVersion':'1','Hash':'d'*64}}
        ssm.get_document.return_value={'Content':json.dumps(reader.doc)}
        ssm.send_command.return_value={'Command':{'CommandId':'read-one'}}
        return reader,ssm,reporter,clock

    def test_one_inflight_observation_and_no_retry_of_ambiguous_send(self):
        with tempfile.TemporaryDirectory() as root:
            reader,ssm,reporter,clock=self.reader(root)
            reader();clock[0]+=100
            ssm.list_command_invocations.return_value={'CommandInvocations':[{'Status':'InProgress'}]}
            reader();reader();self.assertEqual(ssm.send_command.call_count,1)
        with tempfile.TemporaryDirectory() as root:
            reader,ssm,reporter,clock=self.reader(root);ssm.send_command.side_effect=TimeoutError('secret')
            reader();clock[0]+=100;reader();self.assertEqual(ssm.send_command.call_count,1)
            self.assertTrue(reader.disabled)

    def test_pending_reader_close_does_not_consume_snapshot_or_recovery_budget(self):
        with tempfile.TemporaryDirectory() as root:
            reader,ssm,reporter,clock=self.reader(root);reader()
            p=Progress(root,binding(),'freeze');p.update('BASELINE',50,100)
            ssm.list_command_invocations.return_value={'CommandInvocations':[{'Status':'Success'}]}
            ssm.get_command_invocation.return_value={'CommandId':'read-one','InstanceId':HOSTS['backend'],'DocumentName':reader.name,
                'Status':'Success','ResponseCode':0,'StandardErrorContent':'','StandardOutputContent':json.dumps({'progress':p.value})}
            reader();self.assertIsNone(reader.pending)
            self.assertEqual(reporter.emit.call_args.kwargs['done'],50)
            clock[0]+=60;reader();self.assertIsNotNone(reader.pending)
            ssm.list_command_invocations.return_value={'CommandInvocations':[{'Status':'InProgress'}]}
            before=clock[0];reader.sleep=Mock(side_effect=AssertionError('display must not wait'))
            calls=len(ssm.mock_calls);reader.close();reader()
            self.assertEqual(clock[0],before);self.assertEqual(len(ssm.mock_calls),calls)
            reader.sleep.assert_not_called();self.assertTrue(reader.closed)

    def test_display_exception_does_not_turn_successful_command_into_failure(self):
        from run import wait_result,DOCUMENT_PREFIX
        ssm=Mock();name=DOCUMENT_PREFIX+'d'*64
        ssm.list_command_invocations.return_value={'CommandInvocations':[{'Status':'Success','CommandPlugins':[{'Name':'report','ResponseCode':0}]}]}
        ssm.get_command_invocation.return_value={'CommandId':'work','InstanceId':HOSTS['backend'],'DocumentName':name,
            'Status':'Success','ResponseCode':0,'StandardErrorContent':'','StandardOutputContent':json.dumps({'status':'VERIFIED','checks':{'fixture':True}})}
        with patch('builtins.print'):
            result=wait_result(ssm,'work',HOSTS['backend'],name,observer=Mock(side_effect=OSError('display')))
        self.assertEqual(result['status'],'Success')

    def test_snapshot_100_percent_still_waits_for_available(self):
        import initial_db_runner as runner
        ctx={'run_id':'123456789','commit':'a'*40,'request_id':'c'*32};now=datetime.now(timezone.utc)
        row={'DBSnapshotIdentifier':'jjikmuk-ops-initial-db-'+ctx['run_id'],'DBInstanceIdentifier':runner.DB,
             'Encrypted':True,'SnapshotType':'manual','PercentProgress':100,'DBSnapshotArn':'arn:fixture','SnapshotCreateTime':now}
        rds=Mock();rds.describe_db_snapshots.side_effect=[{'DBSnapshots':[dict(row,Status='creating')]},{'DBSnapshots':[dict(row,Status='available')]}]
        progress=Mock()
        with patch.object(runner,'put_once'),patch.object(runner,'save_local'),patch('auto_context.check_snapshot'):
            runner.snapshot(rds,{'s3':Mock()},ctx,sleep=lambda _:None,frozen_epoch=int(now.timestamp())-1,progress=progress)
        self.assertEqual([c.args[0] for c in progress.call_args_list],['SNAPSHOT_WAIT','SNAPSHOT_READY'])
        rds.create_db_snapshot.assert_called_once()


class FakeReporter(Reporter):
    def call(self,path,method='GET',value=None):
        self.calls.append((path,method,value))
        return {'id':123,'external_id':self.external,'head_sha':self.ctx['commit'],'name':self.name,'app':{'slug':'github-actions'}}


class GithubProgressTests(unittest.TestCase):
    def test_wrong_check_identity_cannot_be_updated_after_initialization_failure(self):
        for field,bad in [('external_id','different'),('head_sha','d'*40),('app',{'slug':'different-app'})]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as root:
                reporter=FakeReporter.__new__(FakeReporter);reporter.calls=[]
                original=FakeReporter.call
                def call(path,method='GET',value=None):
                    result=original(reporter,path,method,value)
                    if method=='GET':result[field]=bad
                    return result
                with patch.object(reporter,'call',side_effect=call),patch('builtins.print'):
                    reporter.__init__(binding(),'recover',folder=root)
                    reporter.emit('RECOVERY',force=True)
                self.assertFalse(reporter.ready);self.assertIsNone(reporter.check)
                self.assertFalse(any(method=='PATCH' for _,method,_ in reporter.calls))

    def test_one_check_reused_across_phases_and_no_product_values(self):
        with tempfile.TemporaryDirectory() as root:
            ctx=binding();first=FakeReporter.__new__(FakeReporter);first.calls=[]
            with patch('builtins.print'):
                first.__init__(ctx,'freeze',folder=root,clock=lambda:1100)
                first.emit('BASELINE',done=50,total=100,written=1090,advanced=1080,force=True)
                second=FakeReporter.__new__(FakeReporter);second.calls=[]
                second.__init__(ctx,'apply',folder=root,clock=lambda:1200)
            self.assertTrue(first.ready and second.ready)
            self.assertEqual(sum(method=='POST' for _,method,_ in first.calls+second.calls),1)
            patch_payload=[value for _,method,value in first.calls if method=='PATCH'][0]
            self.assertIn('50.0%',patch_payload['output']['summary'])
            self.assertNotIn('barcode',json.dumps(patch_payload))
            self.assertNotIn('password',json.dumps(patch_payload))
            with patch('builtins.print'):
                first.emit('FAILED',error_code='secret=fixture',force=True)
            self.assertEqual(sum(method=='PATCH' for _,method,_ in first.calls),1)


if __name__=='__main__':unittest.main()
