"""Refresh an S3 heartbeat while a fixed maintenance phase runs; fail closed."""
from datetime import datetime, timezone
import threading
import time
from connection import ACCOUNT, BUCKET, canonical
from storage_metrics import observe
from bootstrap import need


class Monitor:
    def __init__(self, s3, cloudwatch, binding, required_bytes, *, budget_check=lambda:None, minimum_reserve=5*1024**3):
        self.s3, self.cloudwatch, self.binding = s3, cloudwatch, binding
        need(type(minimum_reserve) is int and minimum_reserve in (2*1024**3,5*1024**3),'MAINTENANCE_RESERVE_POLICY')
        need(type(required_bytes) is int and required_bytes == binding['required_bytes']
             and required_bytes >= minimum_reserve, 'MAINTENANCE_RESERVE_REQUIRED')
        self.required = required_bytes
        self.budget_check=budget_check
        self.key = ('operations/bootstrap/' + binding['archive_sha256'] + '/monitor-'
                    + binding['request_id'] + '.json')
        self.stop_event = threading.Event()
        self.failure = None
        self.thread = None

    def publish(self):
        self.budget_check()
        report = observe(self.cloudwatch, datetime.now(timezone.utc))
        counts = report['counts']
        need(counts['window_minimum_bytes'] >= self.required, 'MAINTENANCE_STORAGE_RESERVE')
        value = {'format': 1, **{k: self.binding[k] for k in ('request_id', 'commit', 'archive_sha256')},
                 'state': 'PROCEED', 'written_epoch': int(time.time()),
                 'metric_epoch': counts['sample_epoch'], 'minimum_bytes': counts['window_minimum_bytes'],
                 'required_bytes': self.required}
        self.budget_check()
        self.s3.put_object(Bucket=BUCKET, Key=self.key, ExpectedBucketOwner=ACCOUNT,
            ServerSideEncryption='AES256', ContentType='application/json', Body=canonical(value))

    def run(self):
        while not self.stop_event.wait(20):
            try:
                self.publish()
            except BaseException as error:
                self.failure = type(error).__name__
                # If S3 itself is unavailable, expiry of the last lease also stops the host.
                try:
                    self.s3.put_object(Bucket=BUCKET, Key=self.key, ExpectedBucketOwner=ACCOUNT,
                        ServerSideEncryption='AES256', ContentType='application/json', Body=canonical({
                        'format':1, **{k:self.binding[k] for k in ('request_id','commit','archive_sha256')},
                        'state':'STOP', 'written_epoch':int(time.time()), 'metric_epoch':0,
                        'minimum_bytes':0, 'required_bytes':self.required}))
                except Exception:
                    pass
                return

    def __enter__(self):
        self.publish()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def check(self):
        self.budget_check()
        need(self.failure is None, 'MAINTENANCE_MONITOR_FAILED')

    def __exit__(self, kind, value, traceback):
        self.stop_event.set()
        self.thread.join(timeout=35)
        need(not self.thread.is_alive(), 'MAINTENANCE_MONITOR_DID_NOT_STOP')
        if kind is None:
            self.check()
