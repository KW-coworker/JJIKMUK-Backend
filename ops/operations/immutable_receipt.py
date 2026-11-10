"""Reconcile only ambiguous immutable S3 receipts, never repeat a server command."""
import time
from connection import ACCOUNT,BUCKET,canonical
from bootstrap import need


def transient(error):
    from botocore.exceptions import ConnectionClosedError,EndpointConnectionError,ReadTimeoutError,ConnectTimeoutError
    return isinstance(error,(ConnectionClosedError,EndpointConnectionError,ReadTimeoutError,ConnectTimeoutError))


def put_once(s3,key,value,*,sleep=time.sleep):
    body=canonical(value)
    ambiguous=False
    for attempt in range(3):
        try:
            return s3.put_object(Bucket=BUCKET,Key=key,Body=body,ContentType='application/json',
                ServerSideEncryption='AES256',ExpectedBucketOwner=ACCOUNT,IfNoneMatch='*')
        except Exception as error:
            code=(getattr(error,'response',None) or {}).get('Error',{}).get('Code')
            # An already-existing intent on the first request is always a replay.
            if not transient(error) and not (ambiguous and code=='PreconditionFailed'):raise
            ambiguous=True
        try:
            response=s3.get_object(Bucket=BUCKET,Key=key,ExpectedBucketOwner=ACCOUNT)
            need(response['ContentLength']==len(body),'IMMUTABLE_RECEIPT_CHANGED')
            with response['Body'] as stream:actual=stream.read(len(body)+1)
            need(actual==body,'IMMUTABLE_RECEIPT_CHANGED')
            return {'confirmed_after_transport_error':True}
        except Exception as error:
            code=(getattr(error,'response',None) or {}).get('Error',{}).get('Code')
            if not transient(error) and code!='NoSuchKey':raise
        if attempt<2:sleep(attempt+1)
    raise ValueError('IMMUTABLE_RECEIPT_UNCONFIRMED_NO_COMMAND_REPLAY')
