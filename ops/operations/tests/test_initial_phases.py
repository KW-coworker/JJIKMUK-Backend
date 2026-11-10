from datetime import datetime,timezone
import unittest
from unittest.mock import MagicMock,patch
import initial_db_runner as runner


class InitialPhaseTests(unittest.TestCase):
    def test_frozen_snapshot_must_precede_apply(self):
        events=[];ctx={'commit':'a'*40};backup={'id':'fixed'}
        def phase(name,snapshot=None):
            events.append(name)
            if name=='freeze':return {'success':True,'report':{'counts':{'frozen_epoch':123}}}
            self.assertEqual(snapshot,backup)
            return {'success':True}
        def snapshot(*args,**kwargs):
            self.assertEqual(kwargs['frozen_epoch'],123)
            events.append('snapshot');return backup
        with patch.object(runner,'snapshot',side_effect=snapshot),patch.object(runner,'validate_context',return_value=ctx):
            runner.maintain({},ctx,MagicMock(),MagicMock(),phase)
        self.assertEqual(events,['freeze','snapshot','apply'])

    def test_snapshot_failure_recovers_but_never_applies(self):
        phase=MagicMock(return_value={'success':True,'report':{'counts':{'frozen_epoch':123}}})
        with patch.object(runner,'snapshot',side_effect=ValueError('SYNTHETIC_SNAPSHOT_FAILURE')), \
                patch.object(runner,'save_local'),self.assertRaisesRegex(ValueError,'SYNTHETIC'):
            runner.maintain({}, {},MagicMock(),MagicMock(),phase)
        self.assertEqual([c.args[0] for c in phase.call_args_list],['freeze','recover'])

    def test_failed_freeze_never_creates_snapshot(self):
        with patch.object(runner,'snapshot') as snapshot,patch.object(runner,'save_local'), \
                self.assertRaisesRegex(ValueError,'FREEZE_FAILED'):
            runner.maintain({}, {},MagicMock(),MagicMock(),MagicMock(return_value={'success':False}))
        snapshot.assert_not_called()

    def test_snapshot_requires_frozen_state_before_creation(self):
        rds=MagicMock()
        with self.assertRaisesRegex(ValueError,'FROZEN_DATABASE_REQUIRED'):
            runner.snapshot(rds,{}, {})
        rds.create_db_snapshot.assert_not_called()

    def test_later_documents_never_extract_or_replace_host_files(self):
        h='a'*64;envelope={'files':{},'commit':'b'*40}
        for name in ('apply','recover'):
            doc=runner.document('operations/bootstrap/'+h+'/payload.zip',h,envelope,{},name)
            self.assertEqual(len(doc['mainSteps']),1)
            code=doc['mainSteps'][0]['inputs']['runCommand'][0]
            self.assertIn('if '+repr(name)+"=='freeze':",code)
            self.assertIn('meta[\'sha256\']',code)


if __name__=='__main__':unittest.main()
