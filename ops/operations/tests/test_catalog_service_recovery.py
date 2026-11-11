import ast
import copy
import json
import unittest
from unittest.mock import Mock,patch
import catalog_service_recovery as recovery
from connection import canonical,sha
from bootstrap import need


class ServiceRecoveryTests(unittest.TestCase):
    def test_exact_receipt_and_run_required(self):
        with self.assertRaisesRegex(ValueError,'RECEIPT_CHANGED'):
            recovery.document({'binding':{},'envelope':{}},'123')
        saved={'binding':{},'envelope':{}}
        with patch.object(recovery,'RECEIPT_SHA',sha(canonical(saved))):
            for run in ('0','../123','1\n2','1'*21):
                with self.assertRaisesRegex(ValueError,'RECOVERY_RUN'):recovery.document(saved,run)
            doc=recovery.document(saved,'123')
        command=doc['mainSteps'][0]['inputs']['runCommand'][0]
        compile(command.split('\n',1)[1].rsplit('\n',1)[0],'<fixed-recovery>','exec')
        self.assertEqual(doc['mainSteps'][0]['inputs']['timeoutSeconds'],'720')
        self.assertEqual(doc['mainSteps'][0]['name'],'report')

    def test_common_collector_accepts_success_and_preserves_failure(self):
        from run import wait_result,operation_succeeded
        from connection import DOCUMENT_PREFIX
        document=DOCUMENT_PREFIX+'a'*64
        for success in (True,False):
            report=({'status':'VERIFIED','checks':{'backend_healthy_60_seconds':True,'no_product_writes':True},
                     'counts':{'directory_mode':493,'recorded_restored_products':618578},'hashes':{'source_state_sha256':recovery.STATE_SHA}}
                    if success else {'status':'STOPPED','codes':['SERVICE_RECOVERY_PROTECTED']})
            status='Success' if success else 'Failed'
            ssm=Mock();ssm.list_command_invocations.return_value={'CommandInvocations':[{'Status':status,'CommandPlugins':[{'Name':'report'}]}]}
            ssm.get_command_invocation.return_value={'CommandId':'command','InstanceId':'host','DocumentName':document,
                'Status':status,'ResponseCode':0 if success else 1,'StandardOutputContent':json.dumps(report),'StandardErrorContent':''}
            result=wait_result(ssm,'command','host',document,sleep=lambda _:None)
            self.assertEqual(operation_succeeded(result),success)
            ssm.get_command_invocation.assert_called_once_with(CommandId='command',InstanceId='host',PluginName='report')
            if not success:self.assertEqual(result['diagnostic']['codes'],report['codes'])

    def test_changed_gate_cannot_send(self):
        for request,run,state in [('f'*32,recovery.RUN,'WORKING'),(recovery.REQUEST,'1','WORKING'),(recovery.REQUEST,recovery.RUN,'OPEN')]:
            with patch.object(recovery,'Gate') as gate,patch.object(recovery,'execute') as execute:
                gate.return_value.read.return_value=({'request_id':request,'run_id':run,'state':state},'etag')
                with self.assertRaisesRegex(ValueError,'SERVICE_RECOVERY_'):
                    recovery.restore({'s3':Mock()},{'request_id':request,'run_id':'123'})
                execute.assert_not_called()

    def test_incomplete_product_restoration_is_rejected(self):
        tree=ast.parse(recovery.HOST_SCRIPT)
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_restored_state')
        namespace={'require':need}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<recovery-proof>','exec'),namespace)
        validate=namespace['validate_restored_state']
        state={'status':'APP_SWITCH_INTENT','recovery_counts':{'restored':618578,'never_committed':500},
               'recovery_verification':{'products':1348425,'original_values_restored':True}}
        validate(state)
        for field,key,value in [('status',None,'RECOVERY_INTENT'),('recovery_counts','restored',618577),
                                ('recovery_verification','products',1348424),('recovery_verification','original_values_restored',False)]:
            changed=copy.deepcopy(state)
            if key is None:changed[field]=value
            else:changed[field][key]=value
            with self.assertRaisesRegex(ValueError,'DATA_PROOF'):validate(changed)

    def test_existing_records_and_db_are_not_written(self):
        source=recovery.HOST_SCRIPT
        for forbidden in ('Writer(','.recover(','.apply(',"atomic_json(stage/'state.json'",'UPDATE ','ALTER TABLE','chmod(stage',"systemctl('stop','food-chatbot"):
            self.assertNotIn(forbidden,source)
        self.assertEqual(source.count('os.chmod('),1)
        self.assertIn('os.chmod(folder,0o755)',source)
        self.assertLess(source.index("coordinator.record('MUTATION_INTENT')"),source.index('os.chmod('))
        self.assertLess(source.index('work.host.verify('),source.index('work.host.commit('))
        self.assertIn('recovery_sha256=coord_sha',source)
        self.assertIn("coordinator.record('ROLLED_BACK')",source)


if __name__=='__main__':unittest.main()
