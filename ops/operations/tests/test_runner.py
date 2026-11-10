import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from connection import ACCOUNT,HOSTS,canonical,sha
from run import context,load_plan,safe_report,execute,collect,wait_result


class AwsError(Exception):
    def __init__(self,code):self.response={'Error':{'Code':code}}


def plan():
    return {'format':1,'component':'backend','operation':'verify','approval_id':'APPROVAL_TEST_001','approved':True,
        'document':{'schemaVersion':'2.2','parameters':{},'mainSteps':[{
            'name':'report','action':'aws:runShellScript','inputs':{'runCommand':['true']}}]}}


class RunnerTests(unittest.TestCase):
    def test_github_context_rejects_other_account_branch_main_and_rerun(self):
        env={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'KW-coworker/JJIKMUK-Backend','GITHUB_REPOSITORY_ID':'1300060655',
             'GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_SHA':'a'*40,
             'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1','OPERATIONS_CONFIRM':'true','OPERATIONS_REQUEST_ID':'c'*32}
        with patch.dict(os.environ,env,clear=True),patch('run.github',return_value={'object':{'sha':'a'*40}}):
            self.assertEqual('a'*40,context('a'*40,True)['commit'])
            for key,bad in [('GITHUB_REF','refs/heads/evil'),('GITHUB_REPOSITORY_ID','1'),
                            ('GITHUB_RUN_ATTEMPT','2'),('OPERATIONS_CONFIRM','false')]:
                with patch.dict(os.environ,{key:bad}),self.assertRaises(ValueError):context('a'*40,True)
        with patch.dict(os.environ,env,clear=True),patch('run.github',return_value={'object':{'sha':'b'*40}}),self.assertRaises(ValueError):
            context('a'*40,True)

    def test_exact_plan_scope_and_sha(self):
        with tempfile.TemporaryDirectory() as td:
            old=Path.cwd();os.chdir(td)
            try:
                p=Path('ops/operations/plans/test.json');p.parent.mkdir(parents=True)
                raw=canonical(plan());p.write_bytes(raw)
                self.assertEqual(HOSTS['backend'],load_plan(str(p).replace('\\','/'),sha(raw))[1])
                with self.assertRaises(ValueError):load_plan('../outside.json',sha(raw))
                with self.assertRaises(ValueError):load_plan(p.as_posix(),'b'*64)
                bad=plan();bad['approved']=False;p.write_bytes(canonical(bad))
                with self.assertRaises(ValueError):load_plan(p.as_posix(),sha(canonical(bad)))
                bad=plan();bad['component']='other';p.write_bytes(canonical(bad))
                with self.assertRaises(ValueError):load_plan(p.as_posix(),sha(canonical(bad)))
            finally:os.chdir(old)

    def test_report_refuses_free_text_and_credentials(self):
        good={'status':'VERIFIED','checks':{'healthy':True},'hashes':{'jar':'a'*64},'counts':{'restarts':0}}
        self.assertEqual(good,safe_report(json.dumps(good)))
        for value in ({'status':'OK','password':'SENTINEL'}, {'status':'OK','checks':{'x':'SENTINEL'}},
                      {'status':'OK','counts':{'x':True}}, {'status':'OK','codes':['SENTINEL=secret']}):
            with self.assertRaises(ValueError):safe_report(json.dumps(value))

    def test_lost_send_response_is_not_sent_again(self):
        api={'ssm':MagicMock(),'s3':MagicMock()};records={}
        def put(**k):
            if k['Key'] in records:raise AwsError('PreconditionFailed')
            records[k['Key']]=k['Body']
        api['s3'].put_object.side_effect=put
        doc=plan()['document'];api['ssm'].describe_document.return_value={'Document':{'Owner':ACCOUNT,'LatestVersion':'1','Hash':'a'*64}}
        api['ssm'].get_document.return_value={'Content':json.dumps(doc)}
        api['ssm'].send_command.side_effect=TimeoutError('outcome unknown')
        with patch('run.save_local'):
            with self.assertRaises(TimeoutError):execute(api,{'commit':'a'*40,'request_id':'c'*32},plan(),'b'*64,HOSTS['backend'])
            with self.assertRaises(AwsError):execute(api,{'commit':'a'*40,'request_id':'c'*32},plan(),'b'*64,HOSTS['backend'])
        self.assertEqual(1,api['ssm'].send_command.call_count)
        self.assertEqual(1,len(records))

    def test_collect_reconciles_lost_response_without_send(self):
        op='a'*64;api={'ssm':MagicMock(),'s3':MagicMock()};intent={'target':HOSTS['backend'],'document':'JjikmukOperationsApproved-'+'b'*64}
        api['ssm'].list_commands.return_value={'Commands':[{'CommandId':'existing','Comment':'jjikmuk-ops:'+op,'DocumentName':intent['document']}]}
        with patch('run.read_object',side_effect=[intent,AwsError('NoSuchKey')]),patch('run.wait_result',return_value={'status':'Success'}),patch('run.save_local'):
            self.assertEqual('COLLECTED_NO_RESEND',collect(api,op)['status'])
        api['ssm'].send_command.assert_not_called();api['s3'].put_object.assert_not_called()

    def test_failed_earlier_plugin_cannot_be_reported_as_success(self):
        ssm=MagicMock();ssm.list_command_invocations.return_value={'CommandInvocations':[{
            'Status':'Failed','CommandPlugins':[{'Name':'prepare','ResponseCode':1},{'Name':'report','ResponseCode':0}]}]}
        r=wait_result(ssm,'command',HOSTS['backend'],'JjikmukOperationsApproved-'+'a'*64,lambda _:None)
        self.assertEqual('Failed',r['status']);ssm.get_command_invocation.assert_not_called()

    def test_failed_report_or_stderr_is_not_exposed(self):
        ssm=MagicMock();ssm.list_command_invocations.return_value={'CommandInvocations':[{'Status':'Success'}]}
        ssm.get_command_invocation.return_value={'CommandId':'c','InstanceId':HOSTS['backend'],
            'DocumentName':'doc','Status':'Success','ResponseCode':0,'StandardErrorContent':'SENTINEL','StandardOutputContent':'secret'}
        result=wait_result(ssm,'c',HOSTS['backend'],'doc',lambda _:None)
        self.assertNotIn('SENTINEL',str(result));self.assertNotIn('secret',str(result));self.assertNotIn('report',result)


if __name__=='__main__':unittest.main()
