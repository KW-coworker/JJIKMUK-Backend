import hashlib,json,os,sqlite3,tempfile,time,unittest
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import catalog_reapply_contract as contract
import catalog_reapply_runner as runner
import catalog_reapply_last as last
import initial_db_runner as snapshots
from connection import REPO_ID,canonical,sha


class SnapshotRetryTests(unittest.TestCase):
    def test_admission_hashes_stored_ssm_result_not_runner_summary(self):
        import run as executor
        from connection import ACCOUNT
        doc={'schemaVersion':'2.2','mainSteps':[]}
        api={'ssm':Mock(),'s3':Mock()}
        api['ssm'].describe_document.return_value={'Document':{'Owner':ACCOUNT,'LatestVersion':'1','Hash':'a'*64}}
        api['ssm'].get_document.return_value={'Content':json.dumps(doc)}
        api['ssm'].send_command.return_value={'Command':{'CommandId':'fixture-command'}}
        raw={'status':'Success','response_code':0,'report':{'status':'VERIFIED','checks':{'restored':True}}}
        stored={}
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}),patch.object(executor,'wait_result',return_value=raw),\
             patch.object(executor,'save_local'),patch.object(executor,'put_once',side_effect=lambda s3,key,value:stored.update({key:value})):
            wrapper=executor.execute(api,{'commit':'c'*40},
                {'document':doc,'component':'db','operation':'deploy'},'d'*64,'fixture-host',output_prefix='recover-')
        receipt=stored['receipts/'+wrapper['operation_id']+'/result.json']
        self.assertEqual(receipt,raw)
        self.assertNotEqual(sha(canonical(receipt)),sha(canonical(wrapper)))
        gate={'state':'WORKING','request_id':contract.REQUEST,'run_id':contract.LAST_RUN,'commit':contract.LAST_COMMIT,
              'work_sha256':'e'*64,'verify_sha256':'f'*64}
        oldproof={'fixture':'old service proof'}
        for checksum,accepted in ((sha(canonical(receipt)),True),(sha(canonical(wrapper)),False)):
            with patch.object(runner,'Gate') as holder,patch.object(runner,'read_object',side_effect=[oldproof,receipt]),\
                 patch.object(runner,'SERVICE_RESULT',sha(canonical(oldproof))),patch.object(runner,'LAST_RECOVERY_RESULT',checksum):
                holder.return_value.read.return_value=(gate,'etag')
                if accepted:self.assertEqual(runner.previous_gate(api,{},'e'*64,'f'*64),(gate,'etag'))
                else:
                    with self.assertRaisesRegex(ValueError,'RECOVERY_PROOF_CHANGED'):runner.previous_gate(api,{},'e'*64,'f'*64)

    def test_new_bounded_wait_survives_old_limit_without_second_create(self):
        now=datetime.now(timezone.utc);ctx={'run_id':'987654321','commit':'a'*40,'request_id':contract.REQUEST}
        row={'DBSnapshotIdentifier':'jjikmuk-ops-initial-db-'+ctx['run_id'],'DBInstanceIdentifier':snapshots.DB,
             'Encrypted':True,'SnapshotType':'manual','PercentProgress':100,'DBSnapshotArn':'fixture','SnapshotCreateTime':now}
        rds=Mock();rds.describe_db_snapshots.side_effect=[{'DBSnapshots':[dict(row,Status='creating')]}]*60+[{'DBSnapshots':[dict(row,Status='available')]}]
        with patch.object(snapshots,'put_once'),patch.object(snapshots,'save_local'),patch('auto_context.check_snapshot'):
            result=snapshots.snapshot(rds,{'s3':Mock()},ctx,sleep=lambda _:None,frozen_epoch=int(now.timestamp()),max_polls=contract.SNAPSHOT_POLLS)
        self.assertEqual(result['id'],row['DBSnapshotIdentifier']);self.assertEqual(rds.describe_db_snapshots.call_count,61)
        rds.create_db_snapshot.assert_called_once()
        rds.reset_mock();rds.describe_db_snapshots.side_effect=None;rds.describe_db_snapshots.return_value={'DBSnapshots':[dict(row,Status='creating')]}
        with patch.object(snapshots,'put_once'),self.assertRaisesRegex(ValueError,'WAIT_LIMIT_NO_RECREATE'):
            snapshots.snapshot(rds,{'s3':Mock()},ctx,sleep=lambda _:None,frozen_epoch=int(now.timestamp()))
        self.assertEqual(rds.describe_db_snapshots.call_count,60);rds.create_db_snapshot.assert_called_once()
        rds.reset_mock()
        with self.assertRaisesRegex(ValueError,'WAIT_BOUND'):
            snapshots.snapshot(rds,{},ctx,max_polls=181)
        rds.create_db_snapshot.assert_not_called()

    def test_job_keeps_full_apply_and_recovery_time_after_slow_backup(self):
        now=int(time.time());ctx={'run_id':'123456','commit':'a'*40}
        run={'id':123456,'head_sha':ctx['commit'],'run_attempt':1,'repository':{'id':REPO_ID},
             'path':'.github/workflows/server-maintenance.yml'}
        for elapsed,accepted in [(1800,True),(3800,False),(-1,False)]:
            value=dict(run,run_started_at=datetime.fromtimestamp(now-elapsed,timezone.utc).isoformat())
            with patch.object(runner,'github',return_value=value),patch.object(runner.time,'time',return_value=now):
                if accepted:runner.require_job_recovery_budget(ctx)
                else:
                    with self.assertRaisesRegex(ValueError,'RECOVERY_TIME_RESERVED'):runner.require_job_recovery_budget(ctx)
        with patch.object(runner,'github',return_value=dict(run,head_sha='b'*40)),self.assertRaisesRegex(ValueError,'TIME_IDENTITY'):
            runner.require_job_recovery_budget(ctx)
        runtime=Mock(ctx=ctx,api={'s3':Mock()})
        with patch.object(runner,'load',return_value=({},{})),patch.object(runner,'require_job_recovery_budget',side_effect=ValueError('NO_TIME')),\
             patch.object(runner,'read_object') as read:
            with self.assertRaisesRegex(ValueError,'NO_TIME'):runner.apply(runtime)
        runtime.command.assert_not_called();runtime.monitor.assert_not_called();read.assert_not_called()

    def test_only_last_recovered_gate_and_receipt_admit_new_run(self):
        current={'state':'WORKING','request_id':contract.REQUEST,'run_id':contract.LAST_RUN,'commit':contract.LAST_COMMIT,
                 'work_sha256':'c'*64,'verify_sha256':'d'*64}
        oldproof={'fixture':'old service proof'};lastproof={'fixture':'last recovery proof'}
        with patch.object(runner,'Gate') as gate,patch.object(runner,'read_object',side_effect=[oldproof,lastproof]),\
             patch.object(runner,'SERVICE_RESULT',sha(canonical(oldproof))),patch.object(runner,'LAST_RECOVERY_RESULT',sha(canonical(lastproof))):
            gate.return_value.read.return_value=(current,'etag')
            self.assertEqual(runner.previous_gate({'s3':Mock()},{},'c'*64,'d'*64),(current,'etag'))
        for field,value in [('run_id',contract.OLD_RUN),('commit',contract.PREVIOUS),('state','OPEN')]:
            with patch.object(runner,'Gate') as gate,patch.object(runner,'read_object') as read:
                gate.return_value.read.return_value=(dict(current,**{field:value}),'etag')
                with self.assertRaisesRegex(ValueError,'GATE_CHANGED'):runner.previous_gate({'s3':Mock()},{},'c'*64,'d'*64)
                read.assert_not_called()
        recovered={'status':'ROLLED_BACK','component':'db','operation_id':sha((contract.REQUEST+':'+contract.LAST_RUN+':recover').encode()),
                   'recovery_of':contract.previous_apply_record()[1]}
        contract.previous_coordinator(recovered)
        for value in (dict(recovered,status='SUCCEEDED'),dict(recovered,recovery_of='unexpected'),dict(recovered,operation_id='0'*64)):
            with self.assertRaisesRegex(ValueError,'COORDINATOR_CHANGED'):contract.previous_coordinator(value)


class LastAttemptTests(unittest.TestCase):
    def test_completed_product_rollback_is_checked_readonly_and_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root);state={'status':'RECOVERED','previous':{'fixture':'baseline'},'binding':{'fixture':'binding'},
                'recovery_counts':{'restored':1,'never_committed':1},
                'recovery_verification':{'products':1348425,'original_values_restored':True}}
            state_path=folder/'state.json';state_path.write_text(json.dumps(state));journal=folder/'before-values.sqlite'
            expected={'dataset':'catalog-handoff-'+sha((contract.REQUEST+':'+contract.LAST_RUN).encode())[:32],
                      'source_sha256':contract.SOURCE_SHA,'commit':contract.LAST_COMMIT}
            with closing(sqlite3.connect(journal)) as db,db:
                db.execute('CREATE TABLE metadata(key TEXT,value TEXT)');db.execute('INSERT INTO metadata VALUES (?,?)',('binding',json.dumps(expected)))
                db.execute('CREATE TABLE changes(product_id INTEGER PRIMARY KEY,status TEXT)')
                db.executemany('INSERT INTO changes VALUES (?,?)',[(1,'RESTORED_OR_NOT_COMMITTED'),(2,'RESTORED_OR_NOT_COMMITTED')])
                db.execute('CREATE TABLE baseline(id INTEGER PRIMARY KEY)')
                db.execute('WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<1348425) INSERT INTO baseline SELECT x FROM n')
            work=SimpleNamespace(host=SimpleNamespace(baseline=state['previous']))
            before=hashlib.sha256(journal.read_bytes()).hexdigest()
            record,_=contract.previous_apply_record();history=folder/'history'/record['operation_id'];history.mkdir(parents=True)
            (history/'01.json').write_text(json.dumps(record,sort_keys=True),encoding='utf-8')
            with patch('coordination.ROOT',folder),patch.object(last,'stage',return_value=folder),patch.object(last,'secure'),patch.object(last,'read_host_state',return_value=state),\
                 patch.object(last,'LAST_BINDING',sha(canonical(state['binding']))),patch.object(last.subprocess,'run',return_value=SimpleNamespace(stdout=b'inactive')):
                last.verify(work)
                with last.recovered_journal() as (observed,saved,dataset):
                    self.assertEqual(observed,state);self.assertEqual(dataset,expected['dataset'])
                    with self.assertRaises(sqlite3.OperationalError):saved.db.execute('DELETE FROM changes')
                self.assertEqual(hashlib.sha256(journal.read_bytes()).hexdigest(),before)
                state['status']='FROZEN_WITH_BASELINE'
                with self.assertRaisesRegex(ValueError,'RECOVERY_STATE_CHANGED'):last.verify(work)
                state['status']='RECOVERED'
                for changed in ({'restored':0,'never_committed':2},{'restored':2,'never_committed':1},
                                {'restored':True,'never_committed':1},{'restored':1,'never_committed':1,'extra':0}):
                    state['recovery_counts']=changed
                    with self.assertRaisesRegex(ValueError,'RECOVERY_COUNTS'):last.verify(work)
                state['recovery_counts']={'restored':1,'never_committed':1}
                state['recovery_verification']['original_values_restored']=False
                with self.assertRaisesRegex(ValueError,'RECOVERY_UNVERIFIED'):last.verify(work)
                state['recovery_verification']['original_values_restored']=True
                for status in (None,'PREPARED','COMMITTED'):
                    with closing(sqlite3.connect(journal)) as db,db:db.execute('UPDATE changes SET status=? WHERE product_id=1',(status,))
                    with self.assertRaisesRegex(ValueError,'JOURNAL_NOT_RESTORED'):last.verify(work)
                with closing(sqlite3.connect(journal)) as db,db:
                    db.execute("UPDATE changes SET status='RESTORED_OR_NOT_COMMITTED'")
                    db.execute('DELETE FROM baseline WHERE id=1')
                with self.assertRaisesRegex(ValueError,'BASELINE_INCOMPLETE'):last.verify(work)
                journal.with_name(journal.name+'-wal').touch()
                with self.assertRaisesRegex(ValueError,'JOURNAL_ACTIVE'):last.verify(work)


if __name__=='__main__':unittest.main()
