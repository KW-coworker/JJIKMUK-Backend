import copy,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import MagicMock,Mock,patch
import catalog_reapply_contract as contract
from catalog_document import document


def binding():
    return {'request_id':contract.REQUEST,'run_id':'987654321','commit':'a'*40,'previous_commit':contract.PREVIOUS,
        'source_sha256':contract.SOURCE_SHA,'source_bytes':contract.SOURCE_BYTES,'required_bytes':contract.RDS_RESERVE_BYTES,
        'archive_sha256':'b'*64,'reapply':{'previous_run':contract.OLD_RUN,'service_run':contract.SERVICE_RUN,
        'previous_archive':contract.OLD_ARCHIVE,'previous_state_sha256':contract.OLD_STATE,'previous_journal_sha256':contract.OLD_JOURNAL}}


class ContractTests(unittest.TestCase):
    def test_fresh_dataset_and_rollback_capacity_are_independent(self):
        b=binding();contract.validate_binding(b)
        self.assertNotEqual(contract.dataset(b['request_id'],b['run_id']),'catalog-handoff-'+b['request_id'])
        self.assertNotEqual(contract.dataset(b['request_id'],b['run_id']),contract.dataset(b['request_id'],'987654322'))
        self.assertEqual(contract.lease_binding(b,'apply')['required_bytes'],10*1024**3)
        self.assertEqual(contract.lease_binding(b,'recover')['required_bytes'],5*1024**3)
        self.assertGreaterEqual(contract.RDS_START_BYTES,contract.LEASE_BYTES['apply']+5*1024**3)
        self.assertEqual(b['required_bytes'],5*1024**3)

    def test_consumed_runs_source_baseline_and_recovery_records_fail_closed(self):
        for key,value in [('run_id',contract.OLD_RUN),('run_id',contract.SERVICE_RUN),('previous_commit','0'*40),
                          ('source_sha256','0'*64),('required_bytes',1),('request_id','0'*32)]:
            with self.subTest(key=key),self.assertRaises(ValueError):contract.validate_binding(dict(binding(),**{key:value}))
        b=binding();b['reapply']['previous_journal_sha256']='0'*64
        with self.assertRaises(ValueError):contract.validate_binding(b)

    def test_document_uses_new_entrypoint_and_bounded_runtime(self):
        for phase in ('freeze','apply','recover'):
            doc=document(binding(),{'files':{}},phase)
            step=doc['mainSteps'][0]
            self.assertEqual(step['name'],'report')
            script=step['inputs']['runCommand'][0].split('\n',1)[1].rsplit('\nJJIKMUK_CATALOG_FIXED',1)[0]
            compile(script,'reapply-fixed','exec')
            self.assertIn('bin/catalog_reapply_host.py',script)
            self.assertIn('from catalog_reapply_previous import link_source',script)
            self.assertIn('RuntimeMaxSec='+str(contract.PHASE_SECONDS[phase]),script)
            self.assertLessEqual(int(step['inputs']['timeoutSeconds']),7350)

    def test_remaining_budget_rejects_before_send_command(self):
        import catalog_reapply_runner as runner
        runtime=runner.Runtime.__new__(runner.Runtime)
        runtime.phase='recover';runtime.budget=Mock();runtime.budget.admit.side_effect=ValueError('NO_TIME')
        with patch.object(runner,'execute') as execute,self.assertRaisesRegex(ValueError,'NO_TIME'):
            runtime.command(binding(),{})
        execute.assert_not_called()

    def test_long_command_reaches_real_executor_and_waiter_once(self):
        import run
        from connection import ACCOUNT,HOSTS,sha,canonical
        b=binding();doc=document(b,{'files':{}},'apply')
        plan={'format':1,'component':'db','operation':'deploy','approved':True,'document':doc}
        api={'ssm':Mock(),'s3':Mock()};ssm=api['ssm']
        ssm.describe_document.return_value={'Document':{'Owner':ACCOUNT,'LatestVersion':'1','Hash':'d'*64}}
        ssm.get_document.return_value={'Content':json.dumps(doc)}
        ssm.send_command.return_value={'Command':{'CommandId':'command'}}
        name=run.DOCUMENT_PREFIX+sha(canonical(doc))
        ssm.list_command_invocations.return_value={'CommandInvocations':[{'Status':'Success','CommandPlugins':[{'Name':'report','ResponseCode':0}]}]}
        ssm.get_command_invocation.return_value={'CommandId':'command','InstanceId':HOSTS['backend'],'DocumentName':name,
            'Status':'Success','ResponseCode':0,'StandardErrorContent':'','StandardOutputContent':json.dumps({'status':'SUCCEEDED'})}
        with patch.dict(os.environ,GITHUB_ACTIONS='false'),patch.object(run,'put_once'),patch.object(run,'save_local'):
            result=run.execute(api,{'commit':b['commit'],'request_id':b['request_id']},plan,sha(canonical(plan)),
                               HOSTS['backend'],output_prefix='apply-',max_polls=1500)
        self.assertTrue(result['success']);ssm.send_command.assert_called_once();ssm.get_command_invocation.assert_called_once()

    def test_monitor_cannot_extend_lease_after_deadline(self):
        import initial_monitor
        monitor=initial_monitor.Monitor(Mock(),Mock(),dict(binding(),required_bytes=10*1024**3),10*1024**3,
                                        budget_check=Mock(side_effect=ValueError('EXPIRED')))
        with patch.object(initial_monitor,'observe') as observe,self.assertRaisesRegex(ValueError,'EXPIRED'):monitor.publish()
        observe.assert_not_called();monitor.s3.put_object.assert_not_called()

    def test_runtime_shares_renewable_session_with_every_long_lived_client(self):
        import catalog_reapply_runner as runner
        shared=Mock();shared.client.side_effect=lambda name,**kw:Mock(name=name)
        budget=Mock();ctx={'request_id':contract.REQUEST,'run_id':'987654321'}
        with patch.dict(os.environ,MAINTENANCE_MODE='catalog-reapply'),patch.object(runner,'session',return_value=(shared,budget)),\
             patch.object(runner,'clients',return_value={}) as clients:
            runtime=runner.Runtime(ctx,'apply')
        clients.assert_called_once_with(True,session=shared)
        self.assertEqual([c.args[0] for c in shared.client.call_args_list],['rds','cloudwatch'])
        self.assertIs(runtime.budget,budget)

    def test_capacity_blocks_before_any_server_work_when_space_or_pending_change_differs(self):
        import catalog_reapply_runner as runner
        runtime=Mock();good={'AllocatedStorage':30,'StorageType':'gp3','DBInstanceStatus':'available','PendingModifiedValues':{}}
        metric={'counts':{'window_minimum_bytes':15*1024**3}}
        with patch.object(runner,'check_database'),patch.object(runner,'save_local'),patch.object(runner,'observe',return_value=metric):
            for changes in ({'AllocatedStorage':20},{'PendingModifiedValues':{'EngineVersion':'other'}},{'DBInstanceStatus':'storage-optimization'}):
                runtime.rds.describe_db_instances.return_value={'DBInstances':[dict(good,**changes)]}
                with self.assertRaisesRegex(ValueError,'STORAGE_EXPANSION'):runner.capacity(runtime)
            runtime.rds.describe_db_instances.return_value={'DBInstances':[good]}
            runner.capacity(runtime)
            metric['counts']['window_minimum_bytes']=15*1024**3-1
            with self.assertRaisesRegex(ValueError,'STARTING_SPACE'):runner.capacity(runtime)

    def test_old_gate_or_service_proof_cannot_rebind(self):
        import catalog_reapply_runner as runner
        with patch.object(runner,'Gate') as gate,patch.object(runner,'read_object') as read:
            gate.return_value.read.return_value=({'state':'OPEN'},'etag')
            with self.assertRaisesRegex(ValueError,'GATE_CHANGED'):runner.previous_gate({'s3':Mock()},{},'c'*64,'d'*64)
            read.assert_not_called()
            previous={'state':'WORKING','request_id':contract.REQUEST,'run_id':contract.OLD_RUN,'commit':contract.PREVIOUS,
                      'work_sha256':'c'*64,'verify_sha256':'d'*64}
            gate.return_value.read.return_value=(previous,'etag');read.return_value={}
            with self.assertRaisesRegex(ValueError,'PROOF_CHANGED'):runner.previous_gate({'s3':Mock()},{},'c'*64,'d'*64)

    def test_initial_read_result_is_saved_by_actual_entrypoint(self):
        import runpy,maintenance,catalog_capacity
        result={'status':'CATALOG_CAPACITY_OBSERVED'}
        with patch.dict(os.environ,MAINTENANCE_MODE='catalog-capacity'),patch('run.clients'),\
             patch('run.save_local') as save,patch.object(catalog_capacity,'inspect',return_value=result),\
             patch('builtins.print'),patch.dict(os.environ,{
                 'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':maintenance.REPO,'GITHUB_REPOSITORY_ID':str(maintenance.REPO_ID),
                 'GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1',
                 'OPERATIONS_CONFIRM':'true','GITHUB_RUN_ID':'123','GITHUB_SHA':'a'*40,'EXPECTED_SHA':'a'*40,
                 'GITHUB_WORKFLOW_REF':maintenance.REPO+'/.github/workflows/server-maintenance.yml@refs/heads/main',
                 'OPERATIONS_REQUEST_ID':'b'*32,'OPERATIONS_DISPATCH_ID':'c'*32}):
            runpy.run_path(maintenance.__file__,run_name='__main__')
        save.assert_called_once_with('maintenance-result.json',result)


@unittest.skipUnless(os.name=='posix','Linux host runtime')
class HostTests(unittest.TestCase):
    def work(self,path,status):
        import catalog_reapply_host as host
        work=host.Reapply.__new__(host.Reapply);work.stage=Path(path);work.state_path=work.stage/'state.json';work.state_path.touch()
        work.binding=binding();work.phase='recover';work.dataset=contract.dataset(contract.REQUEST,work.binding['run_id'])
        work.journal_binding={};work.require_lease=True;work.source=Mock()
        work.state={'status':status,'previous':{'manifest':{'commit':contract.PREVIOUS}},'old_identity':'old','chatbot':{},
                    'schema':{'already':'V21'},'preservation':{'before':'hash'}}
        work.host=Mock();work.load=Mock();work.guard=Mock();work.resources=Mock();work.verify_schema=Mock()
        work.connect=MagicMock();work.codec=Mock();work.preservation=Mock(return_value=work.state['preservation'])
        work.record=lambda value:work.state.update(status=value)
        return host,work

    def test_unchanged_v21_schema_still_restores_products_and_verifies_all_rows(self):
        with tempfile.TemporaryDirectory() as root:
            host,work=self.work(root,'PRODUCT_APPLY_INTENT')
            with patch.object(host,'systemctl'),patch.object(host,'Journal'),patch.object(host,'Writer') as writer,\
                 patch.object(host,'verify_recovered',return_value={'products':1348425}) as verify,\
                 patch.object(host,'start_and_enroll') as start:
                result=work.recover(True)
            writer.return_value.recover.assert_called_once();verify.assert_called_once()
            self.assertEqual(start.call_args.args[1],work.state['previous'])
            self.assertEqual(work.state['status'],'RECOVERED');self.assertEqual(result['status'],'VERIFIED')

    def test_product_phase_without_monitor_never_writes_or_restarts(self):
        with tempfile.TemporaryDirectory() as root:
            host,work=self.work(root,'PRODUCT_APPLY_INTENT')
            with patch.object(host,'systemctl'),patch.object(host,'Writer') as writer,patch.object(host,'start_and_enroll') as start:
                with self.assertRaisesRegex(ValueError,'WRITES_REQUIRE_MONITOR'):work.recover(False)
            writer.assert_not_called();start.assert_not_called()

    def test_before_write_recovery_needs_no_source_and_unknown_status_is_rejected(self):
        for status in ('FREEZE_INTENT','SERVICES_FROZEN','FROZEN_WITH_BASELINE','SNAPSHOT_VERIFIED','V21_VERIFIED'):
            with tempfile.TemporaryDirectory() as root:
                host,work=self.work(root,status)
                with patch.object(host,'systemctl'),patch.object(host,'Writer') as writer,patch.object(host,'start_and_enroll'):
                    self.assertEqual(work.recover(False)['status'],'VERIFIED')
                work.resources.assert_not_called();writer.assert_not_called()
        for status in ('SUCCEEDED','RECOVERED','RECOVERY_INTENT','NEW_UNKNOWN'):
            with tempfile.TemporaryDirectory() as root:
                host,work=self.work(root,status)
                with patch.object(host,'systemctl') as ctl,self.assertRaisesRegex(ValueError,'NO_REPLAY_OR_UNKNOWN'):
                    work.recover(True)
                ctl.assert_not_called()

    def test_v21_baseline_reads_actual_image_values_and_never_migrates(self):
        import catalog_reapply_host as host
        work=host.Reapply.__new__(host.Reapply);work.verify_schema=Mock()
        self.assertEqual(work.baseline_columns(['product_id','image_role']),['`product_id`','`image_role`'])
        with patch('catalog_host.migrate') as migrate:work.prepare_schema()
        migrate.assert_not_called();work.verify_schema.assert_called_once()

    def test_changed_live_schema_is_not_adopted_as_new_baseline(self):
        import catalog_reapply_host as host
        work=host.Reapply.__new__(host.Reapply);work.state={'schema':{'changed':'column'}};work.codec=Mock()
        with patch.object(host,'original_state') as read,self.assertRaisesRegex(ValueError,'ORIGINAL_V21_SCHEMA_CHANGED'):
            work.verify_previous_values()
        read.assert_not_called();work.codec.assert_not_called()

    def test_image_collation_change_fails_even_when_column_types_match(self):
        import catalog_reapply_host as host
        work=host.Reapply.__new__(host.Reapply);conn=MagicMock()
        values=[['image_asset_sha256','ascii','ascii_general_ci'],['image_assignment_run','ascii','ascii_general_ci'],
                ['image_display_notice','utf8mb4','utf8mb4_unicode_ci'],['image_role','utf8mb4','utf8mb4_unicode_ci']]
        conn.cursor.return_value.__enter__.return_value.fetchall.return_value=values
        work.image_collations(conn)
        values[-1][-1]='utf8mb4_bin'
        with self.assertRaisesRegex(ValueError,'COLLATION_CHANGED'):work.image_collations(conn)

    def test_original_journal_is_read_only_and_unchanged(self):
        import sqlite3,catalog_reapply_previous as previous
        from catalog_writer import Journal
        from manifest import digest
        with tempfile.TemporaryDirectory() as root:
            stage=Path(root);path=stage/'before-values.sqlite'
            b={'dataset':'catalog-handoff-'+contract.REQUEST,'source_sha256':contract.SOURCE_SHA,'commit':contract.PREVIOUS}
            journal=Journal(path,b);journal.close();before=digest(path)
            state={'binding':{'request_id':contract.REQUEST,'source_sha256':contract.SOURCE_SHA,'commit':contract.PREVIOUS}}
            with patch.object(previous,'old_stage',return_value=stage),patch.object(previous,'OLD_JOURNAL',before):
                with previous.previous_journal(state) as journal:
                    with self.assertRaises(sqlite3.OperationalError):journal.db.execute('DELETE FROM baseline')
            self.assertEqual(digest(path),before)

    def test_coordinator_race_rejected_under_lock_before_mutation(self):
        import coordination
        with tempfile.TemporaryDirectory(dir=Path.home()) as root:
            path=Path(root)/'coord';path.mkdir(mode=0o700)
            (path/'history').mkdir(mode=0o700);(path/'host.lock').touch(mode=0o600)
            coordination.atomic(path/'state.json',{'status':'IDLE'})
            before=(path/'state.json').read_bytes()
            with self.assertRaisesRegex(ValueError,'CHANGED_BEFORE_LOCK'):
                with coordination.locked('db','a'*64,root=path,owner=os.geteuid(),expected_sha256='0'*64):pass
            self.assertEqual((path/'state.json').read_bytes(),before)
            self.assertEqual(list((path/'history').iterdir()),[])


if __name__=='__main__':unittest.main()
