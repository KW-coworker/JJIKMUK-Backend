import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import catalog_root_space as root


def fixture(size=30):
    mount={'filesystems':[{'target':'/','source':'/dev/root','fstype':'ext4','options':'rw,relatime','maj:min':'259:1'}]}
    part={'name':'/dev/nvme0n1p1','type':'part','pkname':'/dev/nvme0n1','size':20*root.GIB-1024**2,
          'fstype':'ext4','mountpoints':['/'],'ro':False,'uuid':'filesystem-id','partuuid':'partition-id','maj:min':'259:1'}
    disk={'name':'/dev/nvme0n1','type':'disk','serial':root.VOLUME,'ro':False,'size':size*root.GIB,'children':[part]}
    return mount,{'blockdevices':[disk]}


def selected(size=30):
    m,t=fixture(size)
    return root.select_root(m,t,'/dev/nvme0n1p1',1,1024**2) | {'free_bytes':4*root.GIB,'filesystem_bytes':19*root.GIB}


class RootSpaceTests(unittest.TestCase):
    def test_exact_volume_and_root_are_selected(self):
        self.assertEqual(selected()['disk_bytes'],30*root.GIB)

    def test_separate_boot_partitions_can_precede_root_beyond_one_gib(self):
        mount,tree=fixture()
        start=1152*1024**2
        tree['blockdevices'][0]['children'][0]['size']=20*root.GIB-start
        result=root.select_root(mount,tree,'/dev/nvme0n1p1',1,start)
        self.assertEqual(result['start'],start)
        changed=dict(result,start=start+512)
        with self.assertRaisesRegex(ValueError,'IDENTITY_CHANGED'):root.same_identity(result,changed)

    def test_kernel_root_alias_needs_no_dev_root_symlink(self):
        mount,tree=fixture()
        with patch.object(root,'command',side_effect=[json.dumps(mount),json.dumps(tree)]), \
             patch.object(Path,'read_text',side_effect=['1','2048']), \
             patch.object(root.shutil,'disk_usage',return_value=SimpleNamespace(free=4*root.GIB,total=19*root.GIB)):
            self.assertEqual(root.observe(),selected())

    def test_wrong_volume_or_readonly_disk_rejected(self):
        for field,value in [('serial','vol00000000000000000'),('ro',True),('size',40*root.GIB)]:
            m,t=fixture();t['blockdevices'][0][field]=value
            with self.assertRaises(ValueError):root.select_root(m,t,'/dev/nvme0n1p1',1,1024**2)

    def test_wrong_mount_lvm_partition_or_filesystem_rejected(self):
        for field,value in [('pkname','/dev/nvme1n1'),('mountpoints',['/other']),('fstype','btrfs'),
                            ('type','lvm'),('children',[{}]),('uuid','')]:
            m,t=fixture();t['blockdevices'][0]['children'][0][field]=value
            with self.assertRaises(ValueError):root.select_root(m,t,'/dev/nvme0n1p1',1,1024**2)
        m,t=fixture()
        for device,number,start in [('/dev/mapper/root',1,1024**2),('/dev/nvme0n1p1',2,1024**2),
                                    ('/dev/nvme0n1p1',1,0),('/dev/nvme0n1p1',1,2*root.GIB)]:
            with self.assertRaises(ValueError):root.select_root(m,t,device,number,start)

    def test_ambiguous_root_mapping_rejected(self):
        m,t=fixture();t['blockdevices'].append(copy.deepcopy(t['blockdevices'][0]))
        with self.assertRaisesRegex(ValueError,'MAPPING'):root.select_root(m,t,'/dev/nvme0n1p1',1,1024**2)

    def test_unexpanded_ebs_cannot_mutate(self):
        runner=Mock()
        with self.assertRaisesRegex(ValueError,'NOT_30GIB'):
            root.expand(selected(20),run=runner)
        runner.assert_not_called()

    def test_expansion_command_order_and_success(self):
        before=selected();partitioned=dict(before,partition_bytes=30*root.GIB-1024**2)
        after=dict(partitioned,filesystem_bytes=29*root.GIB,free_bytes=14*root.GIB)
        calls=[];records=[]
        result=root.expand(before,read=Mock(side_effect=[partitioned,after]),run=lambda *args:calls.append(args),
                           tools=lambda name:'/usr/bin/'+name,record=records.append)
        self.assertEqual(result,after)
        self.assertEqual(calls,[(['/usr/bin/growpart','--dry-run','/dev/nvme0n1','1'],),
            (['/usr/bin/growpart','/dev/nvme0n1','1'],90),(['/usr/bin/resize2fs','/dev/nvme0n1p1'],180)])
        self.assertEqual([x['step'] for x in records],['GROWPART_INTENT','FILESYSTEM_GROW_INTENT'])

    def test_dry_run_failure_never_mutates(self):
        run=Mock(side_effect=ValueError('FAIL'));record=Mock()
        with self.assertRaises(ValueError):root.expand(selected(),run=run,tools=lambda n:n,record=record)
        self.assertEqual(run.call_count,1);record.assert_not_called()

    def test_partition_identity_change_prevents_filesystem_write(self):
        before=selected();after=dict(before,uuid='changed',partition_bytes=30*root.GIB-1024**2)
        run=Mock()
        with self.assertRaisesRegex(ValueError,'IDENTITY_CHANGED'):
            root.expand(before,read=lambda:after,run=run,tools=lambda n:n,record=lambda x:None)
        self.assertEqual(run.call_count,2)

    def test_capacity_failure_is_not_success(self):
        before=selected();partitioned=dict(before,partition_bytes=30*root.GIB-1024**2)
        with self.assertRaisesRegex(ValueError,'CAPACITY_NOT_READY'):
            root.expand(before,read=lambda:partitioned,run=lambda *a:None,tools=lambda n:n,record=lambda x:None)

    def test_already_large_partition_skips_growpart_xfs_uses_mount(self):
        before=dict(selected(),fstype='xfs',partition_bytes=30*root.GIB-1024**2)
        after=dict(before,filesystem_bytes=29*root.GIB,free_bytes=14*root.GIB)
        run=Mock()
        root.expand(before,read=Mock(side_effect=[before,after]),run=run,tools=lambda n:n,record=lambda x:None)
        run.assert_called_once_with(['xfs_growfs','-d','/'],180)

    def test_coordinator_is_the_existing_recovered_catalog_contract(self):
        from catalog_reapply_contract import previous_coordinator
        previous_coordinator(root.expected_coordinator())

    def test_other_request_or_hold_never_executes(self):
        from catalog_reapply_contract import REQUEST,LAST_RUN
        from catalog_capacity import root_volume
        with patch('run.execute') as execute,patch('maintenance_gate.Gate') as gate:
            with self.assertRaisesRegex(ValueError,'REQUEST'):
                root.execute_under_hold({'s3':Mock()},{'request_id':'f'*32},'grow')
            gate.return_value.read.return_value=({'state':'OPEN','request_id':REQUEST,'run_id':LAST_RUN},'etag')
            with self.assertRaisesRegex(ValueError,'HOLD'):
                root.execute_under_hold({'s3':Mock()},{'request_id':REQUEST},'grow')
            execute.assert_not_called()

    def test_runner_accepts_only_exact_root_volume(self):
        from catalog_reapply_contract import REQUEST,LAST_RUN
        with patch('run.execute') as execute,patch('maintenance_gate.Gate') as gate, \
             patch('catalog_capacity.ec2_client'),patch('catalog_capacity.root_volume') as meta:
            gate.return_value.read.return_value=({'state':'WORKING','request_id':REQUEST,'run_id':LAST_RUN},'etag')
            meta.return_value={'codes':['HOST_ROOT_VOL_00000000000000000'],'counts':{'host_root_allocated_gib':30}}
            with self.assertRaisesRegex(ValueError,'VOLUME'):
                root.execute_under_hold({'s3':Mock()},{'request_id':REQUEST},'grow')
            execute.assert_not_called()

    def test_runner_real_plan_with_matching_volume_and_hold(self):
        from catalog_reapply_contract import REQUEST,LAST_RUN
        report={'status':'VERIFIED','checks':{'capacity_ready':True}}
        with tempfile.TemporaryDirectory() as folder,patch('run.execute',return_value={'success':True}) as execute, \
             patch('maintenance_gate.Gate') as gate,patch('catalog_capacity.ec2_client'), \
             patch('catalog_capacity.root_volume') as meta:
            gate.return_value.read.return_value=({'state':'WORKING','request_id':REQUEST,'run_id':LAST_RUN},'etag')
            meta.return_value={'codes':['HOST_ROOT_VOL_0BC5EBC80E1F852C6'],'counts':{'host_root_allocated_gib':30}}
            prior=Path.cwd()
            try:
                os.chdir(folder);Path('operation-results').mkdir()
                Path('operation-results/result.json').write_text(json.dumps({'report':report}))
                self.assertEqual(root.execute_under_hold({'s3':Mock()},{'request_id':REQUEST},'grow'),report)
            finally:os.chdir(prior)
            self.assertEqual(execute.call_args.args[-1],'i-06350403fe0400e1b')

    def test_checked_in_plans_match_source(self):
        folder=Path(root.__file__).parent/'plans'
        from run import safe_report
        safe_report(json.dumps({'status':'VERIFIED','codes':['ROOT_FS_EXT4','ROOT_VOLUME_'+root.VOLUME.upper()]}))
        for mode in ('inspect','grow'):
            actual=json.loads((folder/f'catalog-root-space-{mode}-v2.json').read_bytes())
            self.assertEqual(actual,root.plan(mode))
            self.assertLess(len(json.dumps(actual).encode()),60000)
            script=actual['document']['mainSteps'][0]['inputs']['runCommand'][0]
            compile(script.split("<<'ROOT_SPACE_FIXED'\n",1)[1].rsplit('\nROOT_SPACE_FIXED',1)[0],'<plan>','exec')

    def test_original_plans_are_preserved(self):
        folder=Path(root.__file__).parent/'plans'
        for mode,digest in {'inspect':'97edf8e2e93b4b787ab1d9f003a7a9dac30db89e9f099fb8ec49e953dd40f8f2',
                            'grow':'5267f405f55a6f5441438557c188f75eaf510e6f6dc65f4b436d19c0accf79cc'}.items():
            self.assertEqual(hashlib.sha256((folder/f'catalog-root-space-{mode}.json').read_bytes()).hexdigest(),digest)


if __name__=='__main__':unittest.main()
