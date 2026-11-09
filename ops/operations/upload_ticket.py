"""One-object upload capability, encrypted to the requesting local process.

No AWS session is exported. The presigned URL is a secret bearer capability:
it exists only in runner/local process memory and never in logs or public artifacts.
"""
import base64
from datetime import datetime,timezone
import hashlib
import json
import os
import re
from urllib.parse import urlsplit,parse_qs,unquote
from connection import ACCOUNT,REGION,BUCKET,canonical,sha
from bootstrap import need


def b64(raw):return base64.b64encode(raw).decode('ascii')
def unb64(text):return base64.b64decode(text,validate=True)


def validate(binding):
    need(type(binding) is dict and set(binding)=={'request_id','commit','sha256','bytes','public_key','expires'},'UPLOAD_BINDING')
    need(re.fullmatch('[a-f0-9]{32}',binding['request_id']) and re.fullmatch('[a-f0-9]{40}',binding['commit'])
         and re.fullmatch('[a-f0-9]{64}',binding['sha256']),'UPLOAD_IDENTITY')
    need(type(binding['bytes']) is int and 0<binding['bytes']<=4*1024**3,'UPLOAD_SIZE_LIMIT')
    need(type(binding['expires']) is int and 0<binding['expires']-int(datetime.now(timezone.utc).timestamp())<=3600,'UPLOAD_APPROVAL_EXPIRED')
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key=serialization.load_pem_public_key(binding['public_key'].encode())
    need(isinstance(key,rsa.RSAPublicKey) and key.key_size==3072 and key.public_numbers().e==65537,'UPLOAD_PUBLIC_KEY')
    return key


def object_key(binding):return 'operations/private/'+binding['request_id']+'/'+binding['sha256']+'.zip'


def seal(binding,payload):
    public=validate(binding)
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key=os.urandom(32);nonce=os.urandom(12);aad=canonical(binding)
    return {'format':1,'binding_sha256':sha(aad),'nonce':b64(nonce),
        'key':b64(public.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=aad))),
        'ciphertext':b64(AESGCM(key).encrypt(nonce,canonical(payload),aad))}


def open_ticket(private,binding,envelope):
    validate(binding)
    need(set(envelope)=={'format','binding_sha256','nonce','key','ciphertext'} and envelope['format']==1
         and envelope['binding_sha256']==sha(canonical(binding)),'UPLOAD_ENVELOPE_IDENTITY')
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aad=canonical(binding)
    key=private.decrypt(unb64(envelope['key']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=aad))
    result=json.loads(AESGCM(key).decrypt(unb64(envelope['nonce']),unb64(envelope['ciphertext']),aad))
    validate_ticket(binding,result)
    return result


def validate_ticket(binding,ticket):
    need(set(ticket)=={'url','headers','expires','run_id','attempt'} and re.fullmatch('[1-9][0-9]{0,19}',ticket['run_id'])
         and ticket['attempt']=='1','UPLOAD_TICKET_CONTEXT')
    need(type(ticket['expires']) is int and int(datetime.now(timezone.utc).timestamp())<ticket['expires']<=binding['expires'],'UPLOAD_TICKET_EXPIRED')
    parsed=urlsplit(ticket['url']);query=parse_qs(parsed.query)
    need(parsed.scheme=='https' and parsed.hostname==f'{BUCKET}.s3.{REGION}.amazonaws.com'
         and parsed.port in (None,443) and not parsed.username and not parsed.password and not parsed.fragment
         and unquote(parsed.path)=='/'+object_key(binding),'UPLOAD_DESTINATION')
    required={'content-length','content-type','host','if-none-match','x-amz-checksum-sha256','x-amz-expected-bucket-owner','x-amz-server-side-encryption'}
    need(required<=set(query.get('X-Amz-SignedHeaders',[''])[0].split(';')),'UPLOAD_UNSIGNED_CONSTRAINT')
    need(ticket['headers']==headers(binding),'UPLOAD_HEADERS_CHANGED')


def headers(binding):return {'Content-Length':str(binding['bytes']),'Content-Type':'application/zip',
    'If-None-Match':'*','x-amz-checksum-sha256':b64(bytes.fromhex(binding['sha256'])),
    'x-amz-expected-bucket-owner':ACCOUNT,'x-amz-server-side-encryption':'AES256'}


def issue(s3,binding,run_id,attempt):
    validate(binding);need(attempt=='1','UPLOAD_NO_RERUN')
    now=int(datetime.now(timezone.utc).timestamp())
    seconds=min(900,binding['expires']-now)
    url=s3.generate_presigned_url('put_object',Params={'Bucket':BUCKET,'Key':object_key(binding),
        'ContentLength':binding['bytes'],'ContentType':'application/zip','IfNoneMatch':'*',
        'ChecksumSHA256':b64(bytes.fromhex(binding['sha256'])),'ExpectedBucketOwner':ACCOUNT,
        'ServerSideEncryption':'AES256'},ExpiresIn=seconds,HttpMethod='PUT')
    ticket={'url':url,'headers':headers(binding),'expires':now+seconds,
            'run_id':run_id,'attempt':attempt}
    validate_ticket(binding,ticket)
    return seal(binding,ticket)


if __name__=='__main__':
    from pathlib import Path
    from run import context,clients
    try:
        binding=json.loads(unb64(os.environ['UPLOAD_BINDING']))
        context(binding['commit'],True)
        need(binding['request_id']==os.environ['OPERATIONS_REQUEST_ID'],'UPLOAD_REQUEST_CHANGED')
        envelope=issue(clients(True)['s3'],binding,os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_RUN_ATTEMPT'])
        out=Path('upload-ticket');out.mkdir(exist_ok=False)
        (out/'ticket.json').write_bytes(canonical(envelope))
        print('ENCRYPTED_ONE_OBJECT_UPLOAD_TICKET_READY')
    except Exception:
        print('UPLOAD_TICKET_FAILED_NO_SECRET_OUTPUT');raise SystemExit(1)
