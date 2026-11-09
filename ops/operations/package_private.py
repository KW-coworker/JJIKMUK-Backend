"""Create a local private operation archive; publishing it to GitHub is forbidden."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def build(folder,output):
    from bootstrap import need
    need(folder.is_dir() and not folder.is_symlink() and not output.exists(),'PRIVATE_PACKAGE_PATH')
    files=sorted(p for p in folder.rglob('*') if p.is_file())
    need(0<len(files)<=9999 and (folder/'operation.py').is_file(),'PRIVATE_ENTRY_REQUIRED')
    manifest={'format':1,'entrypoint':'operation.py','files':{}}
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_STORED,allowZip64=True) as z:
        for path in files:
            need(not any(p.is_symlink() for p in [path,*path.parents] if p==folder or folder in p.parents),'PRIVATE_SYMLINK')
            name=path.relative_to(folder).as_posix()
            need(name not in ('package.json','result.json') and not any(x in {'.env','.git','__pycache__'} for x in path.parts)
                 and not name.endswith(('.pem','.key','.pyc')),'PRIVATE_PACKAGE_UNEXPECTED_FILE')
            h=hashlib.sha256();size=0
            with path.open('rb') as stream:
                for block in iter(lambda:stream.read(1024**2),b''):h.update(block);size+=len(block)
            manifest['files'][name]={'sha256':h.hexdigest(),'bytes':size}
            z.write(path,name)
        z.writestr('package.json',json.dumps(manifest,sort_keys=True))
    need(output.stat().st_size<=4*1024**3,'PRIVATE_PACKAGE_LIMIT')
    from upload_private import file_sha
    return {'sha256':file_sha(output),'bytes':output.stat().st_size,'files':len(files)}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    try:print(json.dumps(build(Path(a.folder).resolve(),Path(a.output))))
    except Exception:print('PRIVATE_PACKAGE_FAILED');raise SystemExit(1)
