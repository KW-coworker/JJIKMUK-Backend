"""Fixed phase documents: extract once, reverify the same payload for later phases."""
import json
from connection import BUCKET,canonical
from bootstrap import need


def document(key,archive_sha,envelope,binding,phase='freeze',snapshot=None):
    need(phase in ('freeze','apply','recover'),'INITIAL_PHASE')
    need(key=='operations/bootstrap/'+archive_sha+'/payload.zip','INITIAL_PAYLOAD_KEY')
    stage='/opt/jjikmuk-initial-'+archive_sha[:16]
    download='/var/lib/amazon/ssm/jjikmuk-initial-'+archive_sha[:16]
    def shell(code):return ["/usr/bin/python3.12 -I -S -B - <<'INITIAL_SCHEMA_FIXED'\n"+code+'\nINITIAL_SCHEMA_FIXED']
    setup=f'''from pathlib import Path
import os
p=Path({download!r})
for parent in p.parents:
 s=parent.lstat();assert not parent.is_symlink() and s.st_uid==0 and not s.st_mode&0o022
p.mkdir(mode=0o700);os.chmod(p,0o700)
'''
    timeout={'freeze':1200,'apply':2100,'recover':240}[phase]
    code=f'''import hashlib,json,os,subprocess,zipfile
from pathlib import Path,PurePosixPath
try:
 stage=Path({stage!r});expected={envelope!r}
 if {phase!r}=='freeze':
  archive=Path({download!r})/'payload.zip'
  assert not archive.is_symlink() and archive.stat().st_size<268435456
  assert hashlib.sha256(archive.read_bytes()).hexdigest()=={archive_sha!r}
  assert not stage.exists() and not stage.is_symlink()
  with zipfile.ZipFile(archive) as z:
   assert json.loads(z.read('payload-manifest.json'))==expected
   names=z.namelist();assert len(names)==len(set(names)) and set(names)==set(expected['files'])|{{'payload-manifest.json'}}
   assert sum(i.file_size for i in z.infolist())<400*1024**2
   for name,meta in expected['files'].items():
    p=PurePosixPath(name);assert not p.is_absolute() and '..' not in p.parts and str(p)==name
    assert z.getinfo(name).file_size==meta['bytes'] and hashlib.sha256(z.read(name)).hexdigest()==meta['sha256']
   stage.mkdir(mode=0o755);os.chmod(stage,0o755)
   for name in expected['files']:
    path=stage/name
    for parent in reversed(path.parents):
     if stage in parent.parents and not parent.exists():parent.mkdir(mode=0o755);os.chmod(parent,0o755)
    with path.open('xb') as f:f.write(z.read(name));f.flush();os.fsync(f.fileno())
    os.chmod(path,0o644)
 for name,meta in expected['files'].items():
  path=stage/name
  for p in [path,*path.parents]:
   s=p.lstat();assert not p.is_symlink() and s.st_uid==0 and not s.st_mode&0o022
  assert path.stat().st_size==meta['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==meta['sha256']
 r=subprocess.run(['/usr/bin/systemd-run','--quiet','--wait','--pipe','--collect','--service-type=exec',
  '--unit=jjikmuk-initial-{phase}-{archive_sha[:16]}','--property=RuntimeMaxSec={timeout}',
  '--property=TimeoutStartSec=30','--property=TimeoutStopSec=5','--property=KillMode=control-group',
  '--property=UMask=0077','--property=Restart=no',
  '/usr/bin/python3.12','-I','-S','-B',str(stage/'bin/initial_maintenance_host.py')],
  input={canonical({'phase':phase,'binding':binding,'snapshot':snapshot})!r},capture_output=True,timeout={timeout+60},
  cwd='/',env={{'PATH':'/usr/bin:/bin','LANG':'C'}})
 assert r.returncode==0 and not r.stderr and len(r.stdout)<12000
 value=json.loads(r.stdout);assert isinstance(value,dict)
 print(json.dumps(value))
except Exception:
 print('{{"status":"STOPPED","codes":["INITIAL_DB_STAGE_FAILED_KEEP_RECORDS"]}}')
'''
    steps=[]
    if phase=='freeze':
        steps=[{'name':'prepareStage','action':'aws:runShellScript','inputs':{'timeoutSeconds':'30','runCommand':shell(setup)}},
            {'name':'downloadOriginal','action':'aws:downloadContent','inputs':{'sourceType':'S3',
             'sourceInfo':json.dumps({'path':'https://s3.ap-northeast-2.amazonaws.com/'+BUCKET+'/'+key}),
             'destinationPath':download}}]
    steps.append({'name':'report','action':'aws:runShellScript','inputs':{'timeoutSeconds':str(timeout+90),'runCommand':shell(code)}})
    return {'schemaVersion':'2.2','parameters':{},'description':'Approved fixed initial DB maintenance phase '+phase,'mainSteps':steps}
