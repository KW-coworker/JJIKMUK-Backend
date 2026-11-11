import copy,hashlib,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import catalog_prewrite_retry as retry
import catalog_reapply_contract as contract


class PrewriteRetryTests(unittest.TestCase):
    def state(self):
        binding={'run_id':retry.RUN,'commit':retry.COMMIT,'archive_sha256':retry.ARCHIVE}
        baseline={'manifest':{'commit':contract.PREVIOUS}}
        return {'binding':binding,'status':'RECOVERED','previous':baseline},baseline

    def test_only_recovered_prewrite_state_with_exact_old_release_is_admitted(self):
        state,baseline=self.state()
        digest=hashlib.sha256(json.dumps(state['binding'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with patch.object(retry,'BINDING',digest):
            retry.validate_state(state,baseline)
            for key in ('preservation','candidate_release','counts','recovery_counts','value_verification','recovery_verification'):
                with self.subTest(key=key),self.assertRaisesRegex(ValueError,'DATA_WORK_PRESENT'):
                    retry.validate_state(dict(state,**{key:{}}),baseline)
            with self.assertRaisesRegex(ValueError,'STATE_CHANGED'):retry.validate_state(dict(state,status='RECOVERY_INTENT'),baseline)
            with self.assertRaisesRegex(ValueError,'STATE_CHANGED'):retry.validate_state(state,{})
            changed=copy.deepcopy(state);changed['binding']['run_id']='1'
            with self.assertRaisesRegex(ValueError,'BINDING_CHANGED'):retry.validate_state(changed,baseline)

    def test_prewrite_admission_does_not_replace_data_rollback_journal(self):
        self.assertEqual(contract.LAST_RUN,'42984831949')
        self.assertEqual(contract.LAST_ARCHIVE,'ce8e03247702573860180199b619404d4ff573194bdd4663dcb2b71f97fa516d')
        value=retry.coordinator();contract.previous_coordinator(value)
        self.assertEqual(value['operation_id'],'6830d6df296c92e9c8480208257b5a021541df4aa4431cd01705c5c431e881ab')
        self.assertEqual(value['recovery_of'],'9028ffdb6e13310bf828ae60eb01663dff760e409199d2e54b2c3d61bcc0f7e3')
        for key in value:
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'COORDINATOR_CHANGED'):
                contract.previous_coordinator(dict(value,**{key:'changed'}))

    @unittest.skipUnless(os.name=='posix','Linux coordination import')
    def test_host_checks_record_units_and_journal_absence_without_writing(self):
        state,baseline=self.state()
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);path=folder/'state.json';path.write_text(json.dumps(state))
            record=folder/'history'/retry.coordinator()['operation_id']/'02.json'
            record.parent.mkdir(parents=True);record.write_text(json.dumps(retry.coordinator()))
            binding=hashlib.sha256(json.dumps(state['binding'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
            before=path.read_bytes();work=SimpleNamespace(host=SimpleNamespace(baseline=baseline))
            with patch.object(retry,'stage',return_value=folder),patch.object(retry,'BINDING',binding),\
                 patch('coordination.ROOT',folder),patch('host.secure'),\
                 patch('subprocess.run',return_value=SimpleNamespace(stdout=b'inactive')) as run:
                retry.verify(work)
                self.assertEqual(run.call_count,3);self.assertEqual(path.read_bytes(),before)
                (folder/'before-values.sqlite').touch()
                with self.assertRaisesRegex(ValueError,'JOURNAL_EXISTS'):retry.verify(work)
                (folder/'before-values.sqlite').unlink()
                run.return_value.stdout=b'active'
                with self.assertRaisesRegex(ValueError,'UNIT_ACTIVE'):retry.verify(work)
                run.return_value.stdout=b'inactive'
                record.write_text(json.dumps(dict(retry.coordinator(),status='VERIFIED')))
                with self.assertRaisesRegex(ValueError,'RECOVERY_RECORD_CHANGED'):retry.verify(work)
                self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
