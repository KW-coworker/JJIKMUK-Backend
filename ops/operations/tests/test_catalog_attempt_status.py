import unittest
from datetime import datetime,timezone
from unittest.mock import Mock,patch
from botocore.exceptions import ClientError
import catalog_attempt_status as status
from connection import ACCOUNT,REGION,HOSTS


class AttemptStatusTests(unittest.TestCase):
    def row(self):
        name='jjikmuk-ops-initial-db-'+status.RUN
        return {'DBSnapshotIdentifier':name,'DBInstanceIdentifier':status.DB,'Encrypted':True,'SnapshotType':'manual',
                'DBSnapshotArn':f'arn:aws:rds:{REGION}:{ACCOUNT}:snapshot:{name}',
                'Status':'available','PercentProgress':100,'SnapshotCreateTime':datetime.now(timezone.utc),'MasterUsername':'DO_NOT_EXPORT'}

    def test_reads_only_exact_snapshot_without_exposing_database_login(self):
        rds=Mock();rds.describe_db_snapshots.return_value={'DBSnapshots':[self.row()]}
        value=status.snapshot_status(rds)
        self.assertEqual(value['status'],'available');self.assertNotIn('MasterUsername',value)
        self.assertEqual([c[0] for c in rds.mock_calls],['describe_db_snapshots'])
        for field,value in [('Encrypted',False),('DBInstanceIdentifier','other'),('DBSnapshotArn','other')]:
            row=self.row();row[field]=value;rds.describe_db_snapshots.return_value={'DBSnapshots':[row]}
            with self.assertRaises(ValueError):status.snapshot_status(rds)

    def test_absent_is_not_permission_failure_and_no_snapshot_is_created(self):
        rds=Mock();rds.describe_db_snapshots.side_effect=ClientError({'Error':{'Code':'DBSnapshotNotFound'}},'DescribeDBSnapshots')
        self.assertEqual(status.snapshot_status(rds),{'status':'ABSENT'})
        rds.describe_db_snapshots.side_effect=ClientError({'Error':{'Code':'AccessDenied'}},'DescribeDBSnapshots')
        with self.assertRaises(ClientError):status.snapshot_status(rds)
        rds.create_db_snapshot.assert_not_called()

    def test_recovered_attempt_reads_receipts_and_command_metadata_only(self):
        api={'s3':Mock(),'ssm':Mock()};ctx={'request_id':status.REQUEST}
        gate={'request_id':status.REQUEST,'run_id':status.RUN,'commit':status.COMMIT,'state':'WORKING'}
        receipt={'command_id':status.COMMANDS['recover'],'status':'Success','response_code':0,
                 'report':{'status':'VERIFIED','checks':{'old_product_values_restored':True}}}
        intent={'snapshot':'jjikmuk-ops-initial-db-'+status.RUN,'commit':status.COMMIT,'request_id':status.REQUEST}
        def command(**args):return {**args,'Status':'Success','ResponseCode':0,'ExecutionStartDateTime':'fixture-start',
            'ExecutionEndDateTime':'fixture-end','ExecutionElapsedTime':'PT1M','StandardOutputContent':'DO_NOT_EXPORT'}
        api['ssm'].get_command_invocation.side_effect=command
        with patch.object(status,'Gate') as Gate,patch.object(status,'read_object',side_effect=[receipt,intent]),patch.object(status,'aws_client'),patch.object(status,'snapshot_status',return_value={'status':'available'}):
            Gate.return_value.read.return_value=(gate,'etag');value=status.inspect(api,ctx)
        self.assertTrue(all(value['checks'].values()));self.assertNotIn('StandardOutputContent',value['commands']['freeze'])
        self.assertEqual(api['ssm'].get_command_invocation.call_count,2);api['ssm'].send_command.assert_not_called()

        for snapshot in ({'status':'ABSENT'},{'status':'available'}):
            missing=ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')
            with patch.object(status,'Gate') as Gate,patch.object(status,'read_object',side_effect=[receipt,missing]),patch.object(status,'aws_client'),patch.object(status,'snapshot_status',return_value=snapshot):
                Gate.return_value.read.return_value=(gate,'etag');value=status.inspect(api,ctx)
                self.assertEqual(value['snapshot_intent'],'ABSENT');self.assertEqual(value['snapshot'],snapshot)
        denied=ClientError({'Error':{'Code':'AccessDenied'}},'GetObject')
        with patch.object(status,'Gate') as Gate,patch.object(status,'read_object',side_effect=[receipt,denied]),patch.object(status,'aws_client') as client:
            Gate.return_value.read.return_value=(gate,'etag')
            with self.assertRaises(ClientError):status.inspect(api,ctx)
            client.assert_not_called()


if __name__=='__main__':unittest.main()
