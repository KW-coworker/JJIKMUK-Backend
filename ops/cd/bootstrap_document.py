"""Generate a parameter-free SSM installer document after exact package approval."""
import json
import re
from manifest import require


def document(bucket,key,archive_sha,manifest_sha,installer_sha,commit):
    require(re.fullmatch('[a-z0-9][a-z0-9-]{1,61}[a-z0-9]',bucket),'INVALID_BUCKET')
    require(re.fullmatch('operations/bootstrap/[a-f0-9]{64}/payload.zip',key),'INVALID_INSTALL_KEY')
    require(all(re.fullmatch('[a-f0-9]{64}',s) for s in (archive_sha,manifest_sha,installer_sha))
            and re.fullmatch('[a-f0-9]{40}',commit),'INVALID_INSTALL_HASH')
    require(key.split('/')[2]==archive_sha,'CONTENT_ADDRESS_MISMATCH')
    stage='/var/lib/amazon/ssm/jjikmuk-cd-install-'+archive_sha[:16]
    prepare=f'''from pathlib import Path
import os,stat
p=Path({stage!r})
for parent in p.parents:
 s=parent.lstat()
 assert not parent.is_symlink() and s.st_uid==0 and not s.st_mode & 0o022
assert not p.exists() and not p.is_symlink()
p.mkdir(mode=0o700)
'''
    execute=f'''from pathlib import Path
import hashlib,os,subprocess,zipfile
p=Path({stage!r}); archive=p/'payload.zip'
s=archive.lstat()
assert not archive.is_symlink() and s.st_uid==0 and not s.st_mode & 0o022 and 0<s.st_size<=268435456
h=hashlib.sha256()
with archive.open('rb') as f:
 for block in iter(lambda:f.read(1048576),b''):h.update(block)
assert h.hexdigest()=={archive_sha!r}
with zipfile.ZipFile(archive) as z:
 assert z.namelist().count('bin/install_disabled.py')==1
 assert z.getinfo('bin/install_disabled.py').file_size<=131072
 code=z.read('bin/install_disabled.py')
 assert hashlib.sha256(code).hexdigest()=={installer_sha!r}
 target=p/'install_disabled.py'
 with target.open('xb') as f:f.write(code)
 os.chmod(target,0o600)
subprocess.run(['/usr/bin/python3.12','-I','-S','-B',str(target),'--archive',str(archive),'--manifest-sha256',{manifest_sha!r},'--commit',{commit!r},'--approve-disabled-install'],check=True,timeout=300)
'''
    def shell(code):
        return ["set -eu\n/usr/bin/python3.12 -I -S -B - <<'FIXED_CD_BOOTSTRAP'\n"+code+"\nFIXED_CD_BOOTSTRAP\n"]
    return {'schemaVersion':'2.2','description':'Install exact approved main CD package disabled. No restart or activation.',
        'parameters':{},'mainSteps':[
        {'action':'aws:runShellScript','name':'prepareOwnedStage','inputs':{'runCommand':shell(prepare),'timeoutSeconds':'30'}},
        {'action':'aws:downloadContent','name':'downloadPinnedPackage','inputs':{'sourceType':'S3',
          'sourceInfo':json.dumps({'path':'https://s3.ap-northeast-2.amazonaws.com/'+bucket+'/'+key}),'destinationPath':stage}},
        {'action':'aws:runShellScript','name':'verifyAndInstallDisabled','inputs':{'runCommand':shell(execute),'timeoutSeconds':'360'}},
        {'action':'aws:runShellScript','name':'report','inputs':{'timeoutSeconds':'60','runCommand':[
            '/usr/bin/python3 -B /opt/jjikmuk-cd/bin/install_coordinator.py']}}]}
