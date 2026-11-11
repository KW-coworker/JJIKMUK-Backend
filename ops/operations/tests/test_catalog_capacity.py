import unittest
from unittest.mock import Mock,patch
import catalog_capacity as capacity
from connection import ACCOUNT,REGION
from initial_contract import DB_HOST

class CapacityTests(unittest.TestCase):
    def fixture(self):
        return {'DBInstanceIdentifier':capacity.DB,'DBInstanceArn':f'arn:aws:rds:{REGION}:{ACCOUNT}:db:{capacity.DB}',
            'Endpoint':{'Address':DB_HOST},'Engine':'mysql','DBInstanceStatus':'available','StorageEncrypted':True,
            'AllocatedStorage':20,'MaxAllocatedStorage':40,'StorageType':'gp3'}, {'counts':{'latest_bytes':9749008384,'window_minimum_bytes':9749008384,'sample_epoch':1794368100}}

    def test_only_fixed_numeric_storage_fields_are_exported(self):
        db,metric=self.fixture();db['MasterUsername']='DO_NOT_EXPORT'
        value=capacity.report(db,metric)
        self.assertEqual(value['counts']['allocated_gib'],20)
        self.assertEqual(value['counts']['reserve_bytes'],2*1024**3)
        self.assertEqual(value['counts']['starting_required_bytes'],8*1024**3)
        self.assertNotIn('DO_NOT_EXPORT',str(value));self.assertNotIn(DB_HOST,str(value))

    def test_wrong_instance_or_size_is_rejected(self):
        db,metric=self.fixture()
        for key,value in [('DBInstanceIdentifier','other'),('AllocatedStorage',True),('DBInstanceStatus','deleting'),('StorageEncrypted',False)]:
            with self.assertRaisesRegex(ValueError,'CATALOG_CAPACITY_'):capacity.report(dict(db,**{key:value}),metric)

    def test_wrong_hold_never_queries_rds(self):
        with patch.object(capacity,'Gate') as gate,patch.object(capacity,'aws_client') as client:
            gate.return_value.read.return_value=({'request_id':capacity.REQUEST,'run_id':capacity.RUN,'state':'OPEN'},'etag')
            with self.assertRaisesRegex(ValueError,'CATALOG_CAPACITY_GATE'):capacity.inspect({'s3':Mock()},{'request_id':capacity.REQUEST})
            client.assert_not_called()

    def test_modification_observation_is_not_available_or_apply_permission(self):
        db,metric=self.fixture()
        for status in ('modifying','storage-optimization'):
            value=capacity.report(dict(db,DBInstanceStatus=status),metric)
            self.assertFalse(value['checks']['database_available'])
            self.assertIn('RDS_STATUS_'+status.upper(),value['codes'])

    def test_only_latest_recovered_hold_reads_fixed_rds(self):
        db,metric=self.fixture()
        with patch.object(capacity,'Gate') as gate,patch.object(capacity,'aws_client') as client,\
             patch.object(capacity,'observe',return_value=metric),\
             patch.object(capacity,'root_volume',return_value={'counts':{},'codes':[]}),patch.object(capacity,'ec2_client'):
            gate.return_value.read.return_value=({'request_id':capacity.REQUEST,'run_id':capacity.RUN,'state':'WORKING'},'etag')
            client.return_value.describe_db_instances.return_value={'DBInstances':[db]}
            value=capacity.inspect({'s3':Mock()},{'request_id':capacity.REQUEST})
            self.assertTrue(value['checks']['database_available'])
            client.return_value.describe_db_instances.assert_called_once_with(DBInstanceIdentifier=capacity.DB)
            client.return_value.modify_db_instance.assert_not_called()
            client.reset_mock()
            gate.return_value.read.return_value=({'request_id':capacity.REQUEST,'run_id':'42973951751','state':'WORKING'},'etag')
            with self.assertRaisesRegex(ValueError,'CATALOG_CAPACITY_GATE'):
                capacity.inspect({'s3':Mock()},{'request_id':capacity.REQUEST})
            client.assert_not_called()

    def test_ec2_factory_uses_fixed_region_and_bounded_single_attempt(self):
        with patch('boto3.client') as client:
            self.assertIs(capacity.ec2_client(),client.return_value)
        self.assertEqual(client.call_args.args,('ec2',))
        self.assertEqual(client.call_args.kwargs['region_name'],REGION)
        config=client.call_args.kwargs['config']
        self.assertEqual(config.retries,{'total_max_attempts':1})
        self.assertEqual(config.connect_timeout,10);self.assertEqual(config.read_timeout,30)

    def test_host_volume_read_is_bound_to_backend_root_and_exports_no_tags(self):
        from connection import HOSTS
        ec2=Mock();volume_id='vol-'+'a'*17;root='/dev/sda1'
        instance={'InstanceId':HOSTS['backend'],'RootDeviceType':'ebs','RootDeviceName':root,
                  'BlockDeviceMappings':[{'DeviceName':root,'Ebs':{'VolumeId':volume_id}}]}
        attachment={'InstanceId':HOSTS['backend'],'Device':root,'State':'attached'}
        volume={'VolumeId':volume_id,'State':'in-use','Size':30,'VolumeType':'gp3','Attachments':[attachment],
                'Tags':[{'Key':'private','Value':'DO_NOT_EXPORT'}]}
        ec2.describe_instances.return_value={'Reservations':[{'Instances':[instance]}]}
        ec2.describe_volumes.return_value={'Volumes':[volume]}
        result=capacity.root_volume(ec2)
        self.assertEqual(result['counts'],{'host_root_allocated_gib':30})
        self.assertNotIn('DO_NOT_EXPORT',str(result))
        self.assertEqual([call[0] for call in ec2.mock_calls],['describe_instances','describe_volumes'])
        ec2.describe_instances.assert_called_once_with(InstanceIds=[HOSTS['backend']])
        ec2.describe_volumes.assert_called_once_with(VolumeIds=[volume_id])
        for changed in (dict(volume,Size=True),dict(volume,Attachments=[dict(attachment,InstanceId='other')]),
                        dict(volume,Attachments=[dict(attachment,Device='/dev/sdf')]),dict(volume,State='available')):
            ec2.describe_volumes.return_value={'Volumes':[changed]}
            with self.assertRaisesRegex(ValueError,'CATALOG_HOST_'):capacity.root_volume(ec2)

if __name__=='__main__':unittest.main()
