"""Exact code and data versions; only the approved fixed catalog entry can run."""
from connection import canonical,BUCKET
from bootstrap import need
import re


def document(binding,envelope,phase,snapshot=None):
    need(phase in ('freeze','apply','recover') and re.fullmatch('[a-f0-9]{64}',binding['archive_sha256']),'CATALOG_DOCUMENT_PHASE')
    stage='/opt/jjikmuk-catalog-'+binding['archive_sha256'][:16]
    limit={'freeze':1200,'apply':2700,'recover':1500}[phase]
    entry={'binding':dict(binding,phase=phase),'phase':phase,'snapshot':snapshot}
    script=f'''import hashlib,json,os,stat,subprocess,sys,time,zipfile
from pathlib import Path,PurePosixPath
root=Path('/opt/jjikmuk-cd/bin')
for p in [root,*root.parents]:
 s=p.lstat();assert not p.is_symlink() and s.st_uid==0 and not s.st_mode&0o022
sys.path.insert(0,str(root));sys.dont_write_bytecode=True
from host import secure
from host_aws import command as aws,require_identity
from deploy import load_config
from manifest import digest
stage=Path({stage!r});binding={binding!r};expected={envelope!r};started=time.monotonic()
try:
 if {phase!r}=='freeze':
  assert not stage.exists() and not stage.is_symlink()
  stage.mkdir(mode=0o755);os.chmod(stage,0o755)
  download=stage/'download';download.mkdir(mode=0o700)
  config=load_config();require_identity(config['aws'],'ap-northeast-2')
  for name,key,version,size,checksum in [
    ('payload.zip',binding['archive_key'],binding['archive_version'],binding['archive_bytes'],binding['archive_sha256']),
    ('source.zip',binding['source_key'],binding['source_version'],binding['source_archive_bytes'],binding['source_archive_sha256'])]:
   target=download/name
   aws([config['aws'],'s3api','get-object','--region','ap-northeast-2','--bucket',{BUCKET!r},'--key',key,'--version-id',version,
        '--expected-bucket-owner','076767081522',str(target)],180)
   os.chmod(target,0o600);assert target.stat().st_size==size and digest(target)==checksum
  with zipfile.ZipFile(download/'payload.zip') as z:
   assert json.loads(z.read('payload-manifest.json'))==expected
   assert len(z.namelist())==len(set(z.namelist())) and set(z.namelist())==set(expected['files'])|{{'payload-manifest.json'}}
   assert sum(i.file_size for i in z.infolist())<400*1024**2
   for name,meta in expected['files'].items():
    p=PurePosixPath(name);assert not p.is_absolute() and '..' not in p.parts and str(p)==name and '\\\\' not in name
    i=z.getinfo(name);assert not stat.S_ISLNK(i.external_attr>>16) and i.file_size==meta['bytes'] and i.file_size<256*1024**2
    raw=z.read(name);assert hashlib.sha256(raw).hexdigest()==meta['sha256']
    target=stage/name
    for parent in reversed(target.parents):
     if stage in parent.parents and not parent.exists():parent.mkdir(mode=0o755);os.chmod(parent,0o755)
    with target.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    os.chmod(target,0o644)
  with zipfile.ZipFile(download/'source.zip') as z:
   assert sorted(z.namelist())==['source-manifest.json','source-products.sqlite']
   info=z.getinfo('source-products.sqlite');assert not stat.S_ISLNK(info.external_attr>>16) and info.file_size==binding['source_bytes']
   meta=json.loads(z.read('source-manifest.json'));assert meta['sha256']==binding['source_sha256'] and meta['bytes']==binding['source_bytes'] and meta['rows']==1348425
   with z.open(info) as src,(stage/'source-products.sqlite').open('xb') as out:
    import shutil
    shutil.copyfileobj(src,out,1024**2);out.flush();os.fsync(out.fileno())
   os.chmod(stage/'source-products.sqlite',0o600)
   assert digest(stage/'source-products.sqlite')==binding['source_sha256']
 for name,meta in expected['files'].items():
  p=stage/name;secure(p);assert p.stat().st_size==meta['bytes'] and digest(p)==meta['sha256']
 assert time.monotonic()-started < (450 if {phase!r}=='freeze' else 30)
 if {phase!r}=='recover':
  for attempt in range(60):
   states=[]
   for previous in ('freeze','apply'):
    unit='jjikmuk-catalog-'+previous+'-'+binding['archive_sha256'][:16]
    observed=subprocess.run(['/usr/bin/systemctl','is-active',unit],capture_output=True,timeout=5)
    states.append(observed.stdout.strip())
   if all(s in (b'inactive',b'failed',b'unknown') for s in states):break
   time.sleep(1)
  else:raise ValueError('CATALOG_PREVIOUS_UNIT_STILL_RUNNING')
 # Pre-DDL recovery can restore the old app even when the unused data file is damaged.
 r=subprocess.run(['/usr/bin/systemd-run','--quiet','--wait','--pipe','--collect','--service-type=exec',
  '--unit=jjikmuk-catalog-{phase}-{binding['archive_sha256'][:16]}','--property=RuntimeMaxSec={limit}',
  '--property=TimeoutStartSec=30','--property=TimeoutStopSec=10','--property=KillMode=control-group',
  '--property=UMask=0077','--property=Restart=no','/usr/bin/python3.12','-I','-S','-B',str(stage/'bin/catalog_host.py')],
  input={canonical(entry)!r},capture_output=True,timeout={limit+60},cwd='/',env={{'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'}})
 assert not r.stderr and len(r.stdout)<12000
 value=json.loads(r.stdout);assert isinstance(value,dict)
 print(json.dumps(value));sys.exit(0 if r.returncode==0 else 1)
except Exception:
 print('{{"status":"STOPPED","codes":["CATALOG_STAGE_STOPPED_KEEP_RECORDS"]}}');sys.exit(1)
'''
    need(len(script.encode())<60000,'CATALOG_DOCUMENT_SIZE')
    return {'schemaVersion':'2.2','parameters':{},'description':'Approved catalog phase '+phase,
            'mainSteps':[{'action':'aws:runShellScript','name':'report','inputs':{'timeoutSeconds':str({'freeze':1770,'apply':2850,'recover':1740}[phase]),
                'runCommand':["/usr/bin/python3.12 -I -S -B - <<'JJIKMUK_CATALOG_FIXED'\n"+script+'\nJJIKMUK_CATALOG_FIXED']}}]}
