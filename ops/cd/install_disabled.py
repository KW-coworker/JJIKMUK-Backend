"""Install an explicitly hash-approved payload into new CD paths; never start services."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import zipfile
sys.dont_write_bytecode=True


def require(ok,code):
    if not ok:raise ValueError(code)


def sha(data):return hashlib.sha256(data).hexdigest()


def inspect_payload(archive, expected_manifest, commit):
    require(re.fullmatch('[a-f0-9]{64}',expected_manifest) and re.fullmatch('[a-f0-9]{40}',commit),'INVALID_APPROVAL')
    require(archive.stat().st_size<=256*1024*1024,'ARCHIVE_LIMIT')
    z=zipfile.ZipFile(archive)
    try:
        infos=z.infolist();names=[x.filename for x in infos]
        require(len(names)<=10000 and len(set(names))==len(names),'ARCHIVE_MEMBERS')
        require(sum(x.file_size for x in infos)<=768*1024*1024,'EXPANSION_LIMIT')
        require(z.getinfo('install-manifest.json').file_size<=2*1024*1024,'MANIFEST_LIMIT')
        raw=z.read('install-manifest.json');require(sha(raw)==expected_manifest,'MANIFEST_HASH')
        m=json.loads(raw)
        require(m['format']==1 and m['repository']=='KW-coworker/JJIKMUK-Backend'
                and m['commit']==commit and m['source_ref']=='refs/heads/main','FORMAL_MAIN_REQUIRED')
        files=m['files'];require(isinstance(files,list) and len(files)<=9999,'FILE_LIST_LIMIT')
        paths=[x['path'] for x in files]
        require(len(set(paths))==len(paths) and set(names)==set(paths)|{'install-manifest.json'},'PAYLOAD_FILE_SET')
        for f in files:
            name=f['path'];p=PurePosixPath(name)
            require(not p.is_absolute() and '..' not in p.parts and str(p)==name and '\\' not in name,'PAYLOAD_PATH')
            require(name=='config.json' or p.parts[0] in {'bin','vendor','tools','releases'},'PAYLOAD_ROOT')
            require(not name.endswith(('.pyc','.pth','.pyo')) and '__pycache__' not in p.parts,'PAYLOAD_IMPORT_HOOK')
            i=z.getinfo(name);mode=i.external_attr>>16
            require(not i.is_dir() and not stat.S_ISLNK(mode) and stat.S_IFMT(mode) in (0,stat.S_IFREG),'PAYLOAD_TYPE')
            require(type(f['bytes']) is int and 0<f['bytes']<=256*1024*1024 and i.file_size==f['bytes'],'PAYLOAD_SIZE')
            require(type(f['executable']) is bool and sha(z.read(name))==f['sha256'],'PAYLOAD_HASH')
        config=json.loads(z.read('config.json'))
        require(config['enabled'] is False and config['root']=='/opt/jjikmuk-cd'
                and config['service']=='jjikmuk-backend.service','DISABLED_CONFIG_REQUIRED')
        require('REPLACE_' not in json.dumps(config) and 'REQUIRES_OBSERVATION' not in json.dumps(config),'UNRESOLVED_CONFIG')
        return z,m
    except Exception:
        z.close();raise


def trusted_parents(path):
    for part in [path,*path.parents]:
        s=part.lstat()
        require(not part.is_symlink() and s.st_uid==0 and not s.st_mode & 0o022,'UNTRUSTED_INSTALL_PARENT')


def install(archive, manifest_sha, commit, root, settings, check_parent=trusted_parents):
    require(not root.exists() and not root.is_symlink() and not settings.exists() and not settings.is_symlink(),'INSTALL_TARGET_EXISTS')
    check_parent(root.parent);check_parent(settings.parent)
    z,m=inspect_payload(archive,manifest_sha,commit)
    try:
        require(shutil.disk_usage(root.parent).free >= sum(f['bytes'] for f in m['files'])+1024**3,
                'INSTALL_DISK_RESERVE_REQUIRED')
        root.mkdir(mode=0o755)
        journal=root/'install-journal.json'
        state={'status':'STARTED','commit':commit,'manifest_sha256':manifest_sha,'files':[],'enabled':False}
        with journal.open('x',encoding='utf-8') as log:
            os.chmod(journal,0o600)
            def record():
                log.seek(0);json.dump(state,log);log.truncate();log.flush();os.fsync(log.fileno())
            record()
            try:
                settings.mkdir(mode=0o700)
                for item in m['files']:
                    name=item['path'];target=settings/'config.json' if name=='config.json' else root/name
                    # Create only within the two newly owned trees; exclusive file writes.
                    for parent in reversed(target.parents):
                        if parent==root or root in parent.parents:
                            if not parent.exists():parent.mkdir(mode=0o755)
                    state['pending']=name;record()
                    with target.open('xb') as f:
                        data=z.read(name);require(sha(data)==item['sha256'],'PAYLOAD_CHANGED')
                        f.write(data);f.flush();os.fsync(f.fileno())
                    os.chmod(target,0o600 if name=='config.json' else 0o755 if item['executable'] else 0o644)
                    state['files'].append(name);state.pop('pending');record()
                for name in ('runs','releases'):(root/name).mkdir(mode=0o755,exist_ok=True)
                state['status']='INSTALLED_DISABLED';record()
            except Exception:
                state['status']='STOPPED_KEEP_FILES_NO_RETRY';record();raise
        return {'status':'INSTALLED_DISABLED','commit':commit,'restarts':0,'deployment':False}
    finally:z.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--commit',required=True);p.add_argument('--approve-disabled-install',action='store_true',required=True)
    a=p.parse_args()
    try:
        require(os.name=='posix' and os.geteuid()==0,'ROOT_LINUX_REQUIRED')
        print(json.dumps(install(Path(a.archive),a.manifest_sha256,a.commit,Path('/opt/jjikmuk-cd'),Path('/etc/jjikmuk-cd'))))
    except Exception:
        print(json.dumps({'status':'INSTALL_STOPPED_KEEP_RECORDS_NO_RETRY'}));raise SystemExit(1)
