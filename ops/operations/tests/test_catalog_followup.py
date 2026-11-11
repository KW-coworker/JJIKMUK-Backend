import base64,copy,hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,MagicMock,patch
import catalog_followup as runner
import catalog_followup_host as host
from connection import canonical,sha
from catalog_document import document


class FollowupTests(unittest.TestCase):
    def binding(self):
        return {'followup':dict(host.FOLLOWUP),'request_id':host.FOLLOWUP['request_id'],
                'run_id':'123456','archive_sha256':'b'*64,'source_bytes':7,'source_sha256':sha(b'fixture')}

    def test_old_run_or_changed_binding_rejected(self):
        for modify in (lambda x:x.update(run_id=host.FOLLOWUP['old_run']),
                       lambda x:x.update(request_id='f'*32),
                       lambda x:x['followup'].update(old_archive='c'*64)):
            value=self.binding();modify(value)
            with self.assertRaisesRegex(ValueError,'BINDING'):host.validate(value)

    def test_exact_failed_coordinator_and_hash_required(self):
        value={'component':'db','status':'MANUAL_RECOVERY_REQUIRED',
               'operation_id':sha((host.FOLLOWUP['request_id']+':recover').encode())}
        raw=canonical(value)
        with patch.dict(host.FOLLOWUP,coordination_sha256=sha(raw)):
            binding=self.binding();self.assertEqual(host.recovery_hash(binding,raw),sha(raw))
            with self.assertRaisesRegex(ValueError,'COORDINATOR_CHANGED'):host.recovery_hash(binding,raw+b' ')
            bad=canonical(dict(value,status='SUCCEEDED'))
            with patch.dict(host.FOLLOWUP,coordination_sha256=sha(bad)):
                with self.assertRaisesRegex(ValueError,'IDENTITY'):host.recovery_hash(self.binding(),bad)

    def test_readonly_source_reuse_preserves_bytes_and_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            stage=Path(root);source=stage/'source-products.sqlite';source.write_bytes(b'fixture')
            destination=stage/'new.sqlite'
            with patch.object(host,'old_stage',return_value=stage),patch.object(host,'secure'):
                host.link_source(destination,self.binding())
                self.assertTrue(os.path.samefile(source,destination))
                self.assertEqual(source.read_bytes(),b'fixture')
                with self.assertRaises(FileExistsError):host.link_source(destination,self.binding())
                with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):
                    host.link_source(stage/'wrong.sqlite',dict(self.binding(),source_sha256='0'*64))
                self.assertFalse((stage/'wrong.sqlite').exists())

    def test_followup_document_has_separate_stage_and_fixed_source(self):
        for phase in ('freeze','apply','recover'):
            doc=document(self.binding(),{'files':{}},phase)
            script=doc['mainSteps'][0]['inputs']['runCommand'][0].split('\n',1)[1].rsplit('\nJJIKMUK_CATALOG_FIXED',1)[0]
            compile(script,'fixed-followup','exec')
            self.assertIn('link_source(',script)
            self.assertIn("assert not stage.exists()",script)

    def test_changed_hold_or_inspection_never_rebinds(self):
        api={'s3':Mock()};ctx={'request_id':host.FOLLOWUP['request_id'],'run_id':'123456','commit':'a'*40}
        gate=Mock();gate.read.return_value=({'state':'WORKING'},'etag')
        with patch.object(runner,'read_object',return_value={}),patch.object(runner,'put_once') as put:
            with self.assertRaisesRegex(ValueError,'HOLD_CHANGED'):runner.bind(api,ctx,gate,'c'*64,'d'*64)
            put.assert_not_called();gate.write.assert_not_called()
        previous={'state':'WORKING','work_sha256':'c'*64,'verify_sha256':'d'*64}
        gate.read.return_value=(previous,'etag')
        with patch.object(runner,'GATE_SHA',sha(canonical(previous))),patch.object(runner,'read_object',return_value={}):
            with self.assertRaisesRegex(ValueError,'INSPECTION_CHANGED'):runner.bind(api,ctx,gate,'c'*64,'d'*64)
            gate.write.assert_not_called()

    def test_gate_transition_keeps_hold_and_preserves_original(self):
        previous={'state':'WORKING','work_sha256':'c'*64,'verify_sha256':'d'*64,'run_id':host.FOLLOWUP['old_run'],
                  'request_id':host.FOLLOWUP['request_id'],'commit':'e'*40}
        original=copy.deepcopy(previous);observed={'verified':'fixture'}
        gate=Mock();gate.read.return_value=(previous,'etag')
        ctx={'request_id':host.FOLLOWUP['request_id'],'run_id':'123456','commit':'a'*40}
        with patch.object(runner,'GATE_SHA',sha(canonical(previous))),patch.object(runner,'INSPECTION_SHA',sha(canonical(observed))),\
             patch.object(runner,'read_object',return_value=observed),patch.object(runner,'put_once') as put:
            runner.bind({'s3':Mock()},ctx,gate,'c'*64,'d'*64)
        self.assertEqual(previous,original)
        value,etag=gate.write.call_args.args
        self.assertEqual(value['state'],'WORKING');self.assertEqual(value['run_id'],'123456');self.assertEqual(etag,'etag')
        self.assertEqual(put.call_args.args[2]['previous_gate'],original)

    def test_followup_reaches_new_freeze_without_replaying_locked_before_probe(self):
        import catalog_runner as flow
        from contextlib import ExitStack
        for mode in ('catalog','catalog-continue'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as root,ExitStack() as stack:
                archive=Path(root)/'payload.zip';archive.write_bytes(b'fixture')
                ctx={'commit':'a'*40,'request_id':host.FOLLOWUP['request_id'],'run_id':'123456'}
                source={'source_key':'source','source_version':'version','source_archive_bytes':7,'source_archive_sha256':sha(b'fixture'),
                        'previous_commit':'b'*40,'required_bytes':5*1024**3}
                api={'s3':Mock(),'ssm':Mock()}
                api['s3'].head_object.return_value={'ContentLength':7,'ServerSideEncryption':'AES256',
                    'ChecksumSHA256':base64.b64encode(bytes.fromhex(source['source_archive_sha256'])).decode()}
                api['s3'].put_object.return_value={'VersionId':'version'}
                order=[]
                stack.enter_context(patch.dict(os.environ,MAINTENANCE_MODE=mode,WORK_PLAN='fixed',WORK_SHA256='c'*64))
                replacements={'context':Mock(return_value=ctx),'clients':Mock(return_value=api),'source_plan':Mock(return_value=source),
                    'aws_client':Mock(),'check_database':Mock(return_value={}), 'save_local':Mock(),'put_once':Mock(),
                    'build':Mock(side_effect=lambda *args:(order.append('build') or archive,{}, {'jar_sha256':'d'*64,'migrations':[{'version':'21','sha256':'e'*64}]})),
                    'Gate':Mock(),'drained':Mock(side_effect=lambda *args:order.append('drained') or True),
                    'probe_plan':Mock(return_value={}), 'checked_execute':Mock(),'Monitor':MagicMock(),'time_budget':Mock(),
                    'call_phase':Mock(side_effect=lambda *args:order.append('freeze') or {'success':True,'report':{'counts':{'frozen_epoch':1}}}),
                    'snapshot':Mock(side_effect=lambda *args,**kw:order.append('snapshot') or {})}
                for name,value in replacements.items():stack.enter_context(patch.object(flow,name,value))
                stack.enter_context(patch.object(runner,'check',side_effect=lambda *args:order.append('check')))
                bind=stack.enter_context(patch.object(runner,'bind',side_effect=lambda *args:order.append('bind')))
                flow.freeze()
                self.assertEqual(order[-2:],['freeze','snapshot'])
                if mode=='catalog-continue':
                    self.assertEqual(order,['check','build','bind','drained','freeze','snapshot'])
                    replacements['probe_plan'].assert_not_called();replacements['checked_execute'].assert_not_called()
                    replacements['Gate'].return_value.start.assert_not_called();bind.assert_called_once()
                else:
                    replacements['probe_plan'].assert_called_once_with(ctx['request_id'],'before')
                    replacements['checked_execute'].assert_called_once();bind.assert_not_called()

    def test_post_apply_probe_uses_a_fresh_run_identity(self):
        from maintenance_probe import plan
        first=plan(host.FOLLOWUP['request_id'],'after-123456')
        second=plan(host.FOLLOWUP['request_id'],'after-123457')
        self.assertNotEqual(first['document'],second['document'])


@unittest.skipUnless(os.name=='posix','Linux host')
class StartupTests(unittest.TestCase):
    def test_waits_for_health_before_runtime_comparison(self):
        import catalog_host_support as support
        host=Mock();host.protected.return_value={'old':True}
        verified=[];host.verify.side_effect=lambda *args:verified.append(True)
        def state():return {'runtime':'original' if verified else 'launcher-starting'}
        def ctl(*args):
            return 'active' if '--property=ActiveState' in args else 'new-invocation'
        with patch.object(support,'systemctl',side_effect=ctl),patch.object(support,'chatbot_state',side_effect=state):
            support.start_and_enroll(host,{'protected':{'old':True},'manifest':{}},'old',{'runtime':'original'},Mock())
        host.commit.assert_called_once()

    def test_persistent_chatbot_change_never_commits_baseline(self):
        import catalog_host_support as support
        host=Mock();host.protected.return_value={'old':True}
        with patch.object(support,'systemctl',return_value='new-invocation'),patch.object(support,'chatbot_state',return_value={'runtime':'changed'}):
            with self.assertRaisesRegex(ValueError,'RUNTIME_CHANGED'):
                support.start_and_enroll(host,{'protected':{'old':True},'manifest':{}},'old',{'runtime':'original'},Mock())
        host.commit.assert_not_called()

    def test_new_run_uses_new_phase_ids_without_replaying_old_ids(self):
        from catalog_host import phase_id
        binding={'request_id':host.FOLLOWUP['request_id'],'run_id':'123456'}
        ids={phase_id(binding,phase) for phase in ('freeze','apply','recover')}
        self.assertEqual(len(ids),3)
        self.assertTrue(ids.isdisjoint({sha((binding['request_id']+':'+phase).encode()) for phase in ('freeze','apply','recover')}))
        self.assertNotEqual(phase_id(binding,'freeze'),phase_id(dict(binding,run_id='123457'),'freeze'))


if __name__=='__main__':unittest.main()
