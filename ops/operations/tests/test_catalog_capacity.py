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
        self.assertEqual(value['counts']['reserve_bytes'],5368709120)
        self.assertNotIn('DO_NOT_EXPORT',str(value));self.assertNotIn(DB_HOST,str(value))

    def test_wrong_instance_or_size_is_rejected(self):
        db,metric=self.fixture()
        for key,value in [('DBInstanceIdentifier','other'),('AllocatedStorage',True),('DBInstanceStatus','modifying'),('StorageEncrypted',False)]:
            with self.assertRaisesRegex(ValueError,'CATALOG_CAPACITY_'):capacity.report(dict(db,**{key:value}),metric)

    def test_wrong_hold_never_queries_rds(self):
        with patch.object(capacity,'Gate') as gate,patch.object(capacity,'aws_client') as client:
            gate.return_value.read.return_value=({'request_id':capacity.REQUEST,'run_id':capacity.RUN,'state':'OPEN'},'etag')
            with self.assertRaisesRegex(ValueError,'CATALOG_CAPACITY_GATE'):capacity.inspect({'s3':Mock()},{'request_id':capacity.REQUEST})
            client.assert_not_called()

if __name__=='__main__':unittest.main()
