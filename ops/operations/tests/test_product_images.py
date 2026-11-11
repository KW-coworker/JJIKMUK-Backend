import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from product_images_writer import Journal,reconcile,rows_by_id
from product_images_runner import held,slice_plan,REQUEST
from connection import canonical,sha

class ImageListTests(unittest.TestCase):
    def test_commit_checkpoint_cannot_be_assumed_from_old_session(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'j.sqlite','binding')
            before=[{'product_id':7,'image_url':'before','other':'same'}]
            after=[dict(before[0],image_url='after')]
            j.prepare([{'product_id':7}],before,42);j.intent(7,after)
            old=Mock();old.thread_id.return_value=42
            with self.assertRaisesRegex(ValueError,'NEW_CONNECTION'):reconcile(lambda:old,j)
            old.rollback.assert_not_called()
            self.assertEqual(j.db.execute('SELECT status FROM batches').fetchall(),[('COMMITTING',)])
            c=Mock();c.thread_id.return_value=43;c.cursor.return_value.__enter__=Mock(return_value=Mock())
            c.cursor.return_value.__exit__=Mock(return_value=False)
            with patch('product_images_writer.rows_by_id',return_value=after) as read:
                reconcile(lambda:c,j)
                self.assertTrue(read.call_args.kwargs['lock'])
            self.assertEqual(j.db.execute('SELECT status FROM batches').fetchall(),[('COMMITTED',)])
            c.close.assert_called_once();j.close()

    def test_unknown_data_does_not_become_rollback_or_commit(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'j.sqlite','binding');j.prepare([{'product_id':1}],[{'product_id':1,'x':0}],4)
            j.intent(1,[{'product_id':1,'x':1}])
            c=Mock();c.thread_id.return_value=5;c.cursor.return_value.__enter__=Mock(return_value=Mock());c.cursor.return_value.__exit__=Mock(return_value=False)
            with patch('product_images_writer.rows_by_id',return_value=[{'product_id':1,'x':2}]):
                with self.assertRaisesRegex(ValueError,'CONFLICT'):reconcile(lambda:c,j)
            self.assertEqual(j.db.execute('SELECT status FROM batches').fetchall(),[('COMMITTING',)]);j.close()

    def test_target_missing_or_duplicate_and_batch_limit_fail(self):
        q=Mock();q.fetchall.return_value=[{'product_id':1}]
        for ids in ([1,2],[1,1],list(range(501)),[]):
            with self.assertRaises(ValueError):rows_by_id(q,ids)

    def test_existing_hold_must_match_all_bound_identity(self):
        gate={'state':'WORKING','request_id':REQUEST,'run_id':'43041472793'}
        with patch('product_images_runner.Gate') as g:
            g.return_value.read.return_value=(gate,None)
            self.assertEqual(held({'s3':Mock()},{'request_id':REQUEST}),gate)
            for key,value in [('state','OPEN'),('run_id','other'),('request_id','other')]:
                g.return_value.read.return_value=(dict(gate,**{key:value}),None)
                with self.assertRaises(ValueError):held({'s3':Mock()},{'request_id':REQUEST})

    def test_remote_document_binds_each_slice_and_is_valid_python(self):
        r={'seed_operation':'a'*64,'package_sha256':'b'*64,'index':0,'input_sha256':'c'*64}
        a=slice_plan(r);b=slice_plan(dict(r,index=1))
        self.assertNotEqual(sha(canonical(a)),sha(canonical(b)))
        command=a['document']['mainSteps'][0]['inputs']['runCommand'][0]
        compile(command.split('\n',1)[1].rsplit('\n',1)[0],'<fixed-command>','exec')

    def test_oidc_new_mode_retains_context_boundary(self):
        from catalog_credentials import Renewal
        from connection import REPO
        env={'GITHUB_ACTIONS':'true','GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':'123','OPERATIONS_CONFIRM':'true',
             'GITHUB_WORKFLOW_REF':REPO+'/.github/workflows/server-maintenance.yml@refs/heads/main','MAINTENANCE_MODE':'product-images'}
        Renewal(env,Mock(),seconds=9000)
        for change in ({'MAINTENANCE_MODE':'arbitrary'},{'GITHUB_RUN_ATTEMPT':'2'},{'OPERATIONS_CONFIRM':'false'}):
            with self.assertRaises(ValueError):Renewal(dict(env,**change),Mock(),seconds=9000)

if __name__=='__main__':unittest.main()
