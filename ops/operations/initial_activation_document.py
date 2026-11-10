"""One parameter-free initial switch using only the reviewed installed payload."""
import json,re
from bootstrap import need


def document(package,phase):
    need(phase in ('activate','recover'),'INITIAL_ACTIVATION_PHASE')
    commit=package['commit'];archive_sha=package['archive_sha256'];manifest_sha=package['manifest_sha256']
    need(re.fullmatch('[a-f0-9]{40}',commit) and all(re.fullmatch('[a-f0-9]{64}',v)
         for v in (archive_sha,manifest_sha,package['jar_sha256'])),'INITIAL_ACTIVATION_HASH')
    timeout=900 if phase=='activate' else 480
    code=f'''import hashlib,json,os,subprocess,zipfile
from pathlib import Path
try:
 archive=Path('/var/lib/amazon/ssm/jjikmuk-cd-install-{archive_sha[:16]}/payload.zip')
 for path in [archive,*archive.parents]:
  st=path.lstat();assert not path.is_symlink() and st.st_uid==0 and not st.st_mode&0o022
 assert 0<archive.stat().st_size<=268435456
 assert hashlib.sha256(archive.read_bytes()).hexdigest()=={archive_sha!r}
 with zipfile.ZipFile(archive) as z:
  raw=z.read('install-manifest.json');assert hashlib.sha256(raw).hexdigest()=={manifest_sha!r}
  m=json.loads(raw);assert m['commit']=={commit!r} and m['candidate_jar_sha256']=={package['jar_sha256']!r}
  for item in m['files']:
   if item['path']=='config.json':continue
   path=Path('/opt/jjikmuk-cd')/item['path']
   for parent in [path,*path.parents]:
    st=parent.lstat();assert not parent.is_symlink() and st.st_uid==0 and not st.st_mode&0o022
   assert path.stat().st_size==item['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
 result=subprocess.run(['/usr/bin/systemd-run','--quiet','--wait','--pipe','--collect','--service-type=exec',
  '--unit=jjikmuk-cd-initial-{phase}-{archive_sha[:16]}','--property=RuntimeMaxSec={timeout}',
  '--property=TimeoutStartSec=30','--property=TimeoutStopSec=5','--property=KillMode=control-group',
  '--property=UMask=0077','--property=Restart=no','/usr/bin/python3.12','-I','-S','-B',
  '/opt/jjikmuk-cd/bin/initial_activation.py',{phase!r},'--commit',{commit!r},'--jar-sha256',{package['jar_sha256']!r}],
  capture_output=True,timeout={timeout+60},cwd='/',env={{'PATH':'/usr/bin:/bin','LANG':'C'}})
 assert not result.stderr and len(result.stdout)<12000
 value=json.loads(result.stdout);assert isinstance(value,dict)
 print(json.dumps(value))
except Exception:
 print('{{"status":"STOPPED","codes":["INITIAL_ACTIVATION_STAGE_REQUIRES_REVIEW"]}}')
'''
    return {'schemaVersion':'2.2','parameters':{},'description':'Approved initial backend '+phase+' without SQL writes',
        'mainSteps':[{'name':'report','action':'aws:runShellScript','inputs':{'timeoutSeconds':str(timeout+90),
        'runCommand':["/usr/bin/python3.12 -I -S -B - <<'INITIAL_ACTIVATION_FIXED'\n"+code+'\nINITIAL_ACTIVATION_FIXED']}}]}
