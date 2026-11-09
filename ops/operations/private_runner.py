"""Approved private package runner. Never retries or automatically reverses SQL."""
import base64
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import stat
import shutil
import subprocess
import sys
import zipfile
sys.dont_write_bytecode=True
from coordination import locked,secure,ROOT
from private_plan import validate
from connection import BUCKET,ACCOUNT,canonical,sha
from bootstrap import need


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):h.update(block)
    return h.hexdigest()


def unpack(archive,destination):
    with zipfile.ZipFile(archive) as z:
        rows=z.infolist();names=[x.filename for x in rows]
        need(len(names)<=10000 and len(names)==len(set(names)) and sum(x.file_size for x in rows)<=8*1024**3,'PRIVATE_ARCHIVE_LIMIT')
        need(z.getinfo('package.json').file_size<=2*1024**2,'PRIVATE_MANIFEST_LIMIT')
        m=json.loads(z.read('package.json'))
        need(set(m)=={'format','files','entrypoint'} and m['format']==1 and m['entrypoint']=='operation.py'
             and set(names)==set(m['files'])|{'package.json'} and 'operation.py' in m['files'],'PRIVATE_MANIFEST_SCHEMA')
        for info in rows:
            p=PurePosixPath(info.filename)
            need(not p.is_absolute() and str(p)==info.filename and '..' not in p.parts and '\\' not in info.filename
                 and ':' not in info.filename and not info.is_dir()
                 and stat.S_IFMT(info.external_attr>>16) in (0,stat.S_IFREG),'PRIVATE_ARCHIVE_PATH')
            need(info.file_size<=4*1024**3,'PRIVATE_ARCHIVE_FILE_LIMIT')
        destination.mkdir(mode=0o700,exist_ok=False)
        for name,expected in m['files'].items():
            need(set(expected)=={'sha256','bytes'} and z.getinfo(name).file_size==expected['bytes'],'PRIVATE_FILE_SIZE')
            path=destination/name;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with z.open(name) as source,path.open('xb') as target:
                for block in iter(lambda:source.read(1024**2),b''):target.write(block)
            os.chmod(path,0o600);need(digest(path)==expected['sha256'],'PRIVATE_FILE_HASH')
    return destination/'operation.py'


def execute(envelope):
    validate(envelope);need(os.geteuid()==0,'PRIVATE_ROOT_REQUIRED')
    operation_id=sha(canonical(envelope))
    with locked(envelope['component'],operation_id,recovery_sha256=envelope['recovery_sha256']) as guard:
        stage=ROOT/('private-'+operation_id);stage.mkdir(mode=0o700)
        need(shutil.disk_usage(stage).free>=envelope['bytes']*3+2*1024**3,'PRIVATE_DISK_RESERVE_REQUIRED')
        archive=stage/'package.zip'
        key='operations/private/'+envelope['request_id']+'/'+envelope['sha256']+'.zip'
        aws=str(Path(__file__).resolve().parents[1]/'tools/aws-cli/aws');secure(Path(aws))
        result=subprocess.run([aws,'s3api','get-object','--region','ap-northeast-2','--bucket',BUCKET,'--key',key,
            '--version-id',envelope['version'],'--expected-bucket-owner',ACCOUNT,str(archive)],capture_output=True,timeout=600)
        need(result.returncode==0 and archive.stat().st_size==envelope['bytes'] and digest(archive)==envelope['sha256'],'PRIVATE_DOWNLOAD_HASH')
        entry=unpack(archive,stage/'payload')
        # Intent is durable before any reviewed package code can mutate the host/DB.
        guard.record('MUTATION_INTENT')
        # Private output remains on host, mode 0600; never copy raw logs to SSM/GitHub.
        with (stage/'private.log').open('xb') as log:
            os.chmod(stage/'private.log',0o600)
            result=subprocess.run(['/usr/bin/python3','-I','-S','-B',str(entry)],cwd=entry.parent,stdout=log,stderr=log,timeout=1500,
                env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','HOME':'/root','JJIKMUK_OPERATION_ID':operation_id})
        need(result.returncode==0,'PRIVATE_OPERATION_FAILED')
        receipt=entry.parent/'result.json'
        need(receipt.is_file() and not receipt.is_symlink() and receipt.stat().st_size<=4096,'PRIVATE_RESULT_MISSING')
        value=json.loads(receipt.read_bytes())
        need(set(value)=={'status','operation_id','checks'} and value['operation_id']==operation_id
             and value['status'] in ('SUCCEEDED','VERIFIED','INSTALLED_DISABLED') and type(value['checks']) is dict
             and 0<len(value['checks'])<=30 and all(v is True for v in value['checks'].values()),'PRIVATE_VERIFICATION_FAILED')
        guard.record(value['status'])
        return {'status':value['status'],'checks':{'private_operation_verified':True},'hashes':{'operation_id':operation_id}}


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(16385);need(len(raw)<=16384,'PRIVATE_ENVELOPE_LIMIT')
        envelope=json.loads(base64.b64decode(raw.strip(),validate=True))
        print(json.dumps(execute(envelope)))
    except Exception:
        print('{"status":"STOPPED","codes":["PRIVATE_OPERATION_REQUIRES_REVIEW_NO_REPLAY"]}');raise SystemExit(1)
