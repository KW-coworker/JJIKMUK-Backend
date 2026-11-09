"""Prepare/install ONLY the OCR host's common operations tools, never OCR code/models.

This disabled preparation is separately approved and invoked via a hash-fixed SSM
document after the one-time OIDC connection. It never reads an application secret.
"""
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import runpy
import stat
import sys
import zipfile


def need(ok,code):
    if not ok:raise ValueError(code)
def sha(data):return hashlib.sha256(data).hexdigest()


def package(repo,cli,commit,output):
    sys.path.insert(0,str(repo/'ops/cd'))
    from package_install import formal_main,CLI_SHA
    formal_main(repo,commit);need(sha(cli.read_bytes())==CLI_SHA,'TOOLS_CLI_HASH')
    files={}
    for name in ['private_runner.py','private_plan.py','connection.py','bootstrap.py','install_coordinator.py','ocr_tools.py']:
        files['bin/'+name]=((repo/'ops/operations'/name).read_bytes(),False)
    files['bin/coordination.py']=((repo/'ops/cd/coordination.py').read_bytes(),False)
    with zipfile.ZipFile(cli) as z:
        for entry in z.infolist():
            if not entry.filename.startswith('aws/dist/') or entry.is_dir():continue
            need(not stat.S_ISLNK(entry.external_attr>>16),'TOOLS_CLI_SYMLINK')
            files['tools/aws-cli/'+entry.filename.removeprefix('aws/dist/')]=(z.read(entry),bool(entry.external_attr>>16&0o111))
    m={'format':1,'repository':'KW-coworker/JJIKMUK-Backend','commit':commit,'files':{
        name:{'sha256':sha(data),'bytes':len(data),'executable':executable} for name,(data,executable) in files.items()}}
    raw=json.dumps(m,sort_keys=True).encode()
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name,(data,_) in files.items():z.writestr(name,data)
        z.writestr('tools-manifest.json',raw)
    return {'manifest_sha256':sha(raw),'archive_sha256':sha(output.read_bytes()),'archive_bytes':output.stat().st_size}


def install(archive,manifest_sha,commit,root=Path('/opt/jjikmuk-operations')):
    need(os.geteuid()==0 and str(root)=='/opt/jjikmuk-operations','TOOLS_FIXED_ROOT')
    need(not root.exists() and not root.is_symlink() and not Path('/var/lib/jjikmuk-operations').exists(),'TOOLS_ALREADY_EXIST')
    for parent in root.parents:
        s=parent.lstat();need(not parent.is_symlink() and s.st_uid==0 and not s.st_mode&0o022,'TOOLS_PARENT_UNTRUSTED')
    need(0<archive.stat().st_size<=256*1024**2,'TOOLS_ARCHIVE_SIZE')
    with zipfile.ZipFile(archive) as z:
        rows=z.infolist();names=[x.filename for x in rows]
        need(len(names)<=10000 and len(names)==len(set(names)) and sum(x.file_size for x in rows)<=768*1024**2,'TOOLS_ARCHIVE_LIMIT')
        need(z.getinfo('tools-manifest.json').file_size<=2*1024**2,'TOOLS_MANIFEST_LIMIT')
        raw=z.read('tools-manifest.json');need(sha(raw)==manifest_sha,'TOOLS_MANIFEST_HASH');m=json.loads(raw)
        need(m['format']==1 and m['repository']=='KW-coworker/JJIKMUK-Backend' and m['commit']==commit
             and set(names)==set(m['files'])|{'tools-manifest.json'},'TOOLS_SOURCE_IDENTITY')
        for name,info in m['files'].items():
            p=PurePosixPath(name);entry=z.getinfo(name)
            need(not p.is_absolute() and '..' not in p.parts and str(p)==name and '\\' not in name
                 and ':' not in name and p.parts[0] in ('bin','tools') and stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG)
                 and entry.file_size==info['bytes'] and sha(z.read(entry))==info['sha256'],'TOOLS_FILE_VALIDATION')
        import shutil
        need(shutil.disk_usage(root.parent).free>=sum(x.file_size for x in rows)+2*1024**3,'TOOLS_DISK_RESERVE')
        root.mkdir(mode=0o755)
        # A partial install preserves this root; rerunning cannot overwrite it.
        for name,info in m['files'].items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o755)
            with target.open('xb') as stream:stream.write(z.read(name));stream.flush();os.fsync(stream.fileno())
            os.chmod(target,0o755 if info['executable'] else 0o644)
    sys.path.insert(0,str(root/'bin'))
    initializer=runpy.run_path(str(root/'bin/install_coordinator.py'),run_name='tools_install_import')
    initializer['install']()
    return {'status':'INSTALLED_DISABLED','checks':{'operations_tools_only':True,'no_ocr_restart':True}}
