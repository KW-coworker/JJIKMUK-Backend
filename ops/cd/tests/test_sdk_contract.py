"""Validate AWS request shapes against the exact locked SDK, without networking."""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
import test_release
try:
    import botocore.session
    from botocore.validate import validate_parameters
except ImportError:
    botocore = None

@unittest.skipIf(botocore is None, 'Install requirements-sdk.lock; mandatory in GitHub CI')
class SdkContractTests(unittest.TestCase):
    def test_real_release_uses_valid_sdk_request_shapes(self):
        fixture=test_release.ReleaseTests(); fake=fixture.setup_clients()
        from auto_context import ACCOUNT,DATABASE
        fake['rds'].describe_db_snapshots.return_value={'DBSnapshots':[{
            'Status':'available','Encrypted':True,'SnapshotType':'automated','DBInstanceIdentifier':DATABASE,
            'DBSnapshotArn':f'arn:aws:rds:ap-northeast-2:{ACCOUNT}:snapshot:automated',
            'SnapshotCreateTime':datetime.now(timezone.utc)}]}
        session=botocore.session.get_session()
        class Validated:
            def __init__(self,name,target):self.model=session.get_service_model(name);self.target=target
            def __getattr__(self,name):
                # AWS acronym spelling differs from Python method names.
                lookup={botocore.xform_name(x):x for x in self.model.operation_names}
                operation=lookup[name]
                def call(**kwargs):
                    shape=self.model.operation_model(operation).input_shape
                    if shape:validate_parameters(kwargs,shape)
                    return getattr(self.target,name)(**kwargs)
                return call
        validated={name:Validated(name,target) for name,target in fake.items()}
        from release import dispatch
        with test_release.release_fixture(),patch('release.clients',return_value=validated):
            self.assertEqual('SUCCEEDED',dispatch()['status'])
