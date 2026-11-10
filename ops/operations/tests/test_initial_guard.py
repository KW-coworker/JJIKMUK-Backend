import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'cd'))
from initial_guard import validate_heartbeat, Guard
from initial_monitor import Monitor


class InitialGuardTests(unittest.TestCase):
    def setUp(self):
        self.binding={'request_id':'a'*32,'commit':'b'*40,'archive_sha256':'c'*64,'required_bytes':5*1024**3}
        self.value={'format':1,**{k:self.binding[k] for k in ('request_id','commit','archive_sha256')},
                    'state':'PROCEED','written_epoch':1000,'metric_epoch':950,
                    'minimum_bytes':10*1024**3,'required_bytes':5*1024**3}

    def test_binding_freshness_storage_and_stop_are_enforced(self):
        validate_heartbeat(self.value,self.binding,1010)
        for key,value in [('request_id','d'*32),('commit','d'*40),('state','STOP'),
                          ('written_epoch',800),('metric_epoch',700),('minimum_bytes',0),
                          ('required_bytes',3*1024**3),('minimum_bytes',True)]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_heartbeat(dict(self.value,**{key:value}),self.binding,1010)

    def test_cache_never_hides_expired_lease(self):
        client=MagicMock();client.get_object.return_value={'ContentLength':600,'Body':io.BytesIO(json.dumps(self.value).encode())}
        epoch=[1010];guard=Guard(client,self.binding,clock=lambda:epoch[0],monotonic=lambda:1)
        guard();epoch[0]=1100
        with self.assertRaisesRegex(ValueError,'STALE'):guard()
        client.get_object.assert_called_once()
        self.assertEqual(client.get_object.call_args.kwargs['ExpectedBucketOwner'],'076767081522')

    def test_monitor_writes_stop_when_metrics_fail(self):
        monitor=Monitor(MagicMock(),MagicMock(),self.binding,5*1024**3)
        monitor.stop_event=MagicMock();monitor.stop_event.wait.return_value=False
        monitor.publish=MagicMock(side_effect=ValueError('stale'))
        monitor.run()
        value=json.loads(monitor.s3.put_object.call_args.kwargs['Body'])
        self.assertEqual(value['state'],'STOP')
        with self.assertRaisesRegex(ValueError,'MONITOR_FAILED'):monitor.check()


if __name__ == '__main__':unittest.main()
