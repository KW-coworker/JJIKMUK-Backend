"""Package exact tracked AI bytes. No local files, .env, wheels or generated index."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile

REPO='Alphrit/jjikmuk-CO-WORKER-'
REPO_ID=1206944262
MAX_BYTES=128*1024**2


def need(ok,code):
    if not ok:raise ValueError(code)


def sha(data):return hashlib.sha256(data).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def safe_name(name):
    p=PurePosixPath(name)
    need(p.parts and not p.is_absolute() and str(p)==name and '..' not in p.parts
         and '\\' not in name and ':' not in name and len(name)<240,'SOURCE_PATH')
    need(not any(x in {'.env','__pycache__','.git','chroma_db','venv','.venv'} for x in p.parts)
         and not name.endswith(('.pyc','.pyo','.pem','.key')),'UNEXPECTED_SOURCE_FILE')


def manifest(files,commit,run,attempt):
    need(re.fullmatch('[a-f0-9]{40}',commit) and re.fullmatch('[1-9][0-9]{0,19}',run)
         and re.fullmatch('[1-9][0-9]{0,3}',attempt),'SOURCE_IDENTITY')
    need(0<len(files)<=3000 and sum(len(v) for v in files.values())<=MAX_BYTES,'SOURCE_LIMIT')
    for name,raw in files.items():safe_name(name);need(len(raw)<=16*1024**2,'SOURCE_FILE_LIMIT')
    need({'app/api/main.py','app/start.py','requirements.txt'}<=set(files),'SOURCE_REQUIRED')
    entries={k:{'bytes':len(v),'sha256':sha(v)} for k,v in sorted(files.items())}
    def subset(predicate):return sha(canonical({k:v for k,v in entries.items() if predicate(k)}))
    return dict(format=1,repository=REPO,repository_id=REPO_ID,source_ref='refs/heads/chatbot',
        commit=commit,run_id=run,attempt=attempt,files=entries,source_sha256=sha(canonical(entries)),
        runtime_sha256=subset(lambda k:k.startswith('requirements') or k.endswith(('pyproject.toml','uv.lock'))),
        schema_sha256=subset(lambda k:k.startswith('migrations/')),
        rag_sha256=subset(lambda k:k.startswith(('app/knowledge/','app/reference_sources/','data/')) or k in
                         {'app/infrastructure/rag.py','app/infrastructure/knowledge_review.py',
                          'app/infrastructure/knowledge_sources.py','app/start.py'}))


def compatible(previous,candidate):
    for key,code in [('runtime_sha256','RUNTIME_CHANGE_REQUIRES_REVIEW'),
                     ('schema_sha256','SCHEMA_CHANGE_REQUIRES_SEPARATE_RELEASE'),
                     ('rag_sha256','RAG_CHANGE_REQUIRES_REVIEW')]:
        need(previous[key]==candidate[key],code)


def build(source,commit,run,attempt,output):
    def git(*args):
        result=subprocess.run(['git','-C',str(source),*args],capture_output=True,check=True)
        return result.stdout
    need(git('rev-parse','HEAD').decode().strip()==commit,'SOURCE_HEAD_CHANGED')
    rows=git('ls-tree','-r','-z',commit,'AI/').split(b'\0')
    files={}
    for row in rows:
        if not row:continue
        meta,path=row.split(b'\t',1);mode,kind,blob=meta.split()
        need(mode in (b'100644',b'100755') and kind==b'blob','SOURCE_TYPE')
        name=path.decode()[3:];safe_name(name)
        raw=git('cat-file','blob',blob.decode())
        local=Path(source)/path.decode()
        need(local.is_file() and not local.is_symlink() and local.read_bytes()==raw,'SOURCE_WORKTREE_CHANGED')
        files[name]=raw
    m=manifest(files,commit,run,attempt)
    output=Path(output);output.mkdir(exist_ok=False)
    with zipfile.ZipFile(output/'chatbot.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
        for name,raw in sorted(files.items()):
            info=zipfile.ZipInfo(name);info.external_attr=(stat.S_IFREG|0o644)<<16
            z.writestr(info,raw)
    archive=output/'chatbot.zip';m.update(archive_sha256=sha(archive.read_bytes()),archive_bytes=archive.stat().st_size)
    (output/'manifest.json').write_bytes(canonical(m))
    return m


def unpack(archive,m,destination):
    archive=Path(archive)
    need(0<archive.stat().st_size<=MAX_BYTES and archive.stat().st_size==m['archive_bytes']
         and sha(archive.read_bytes())==m['archive_sha256'],'SOURCE_ARCHIVE_HASH')
    with zipfile.ZipFile(archive) as z:
        rows=z.infolist();names=[x.filename for x in rows]
        need(len(names)==len(set(names)) and set(names)==set(m['files']) and len(names)<=3000,'SOURCE_ARCHIVE_MEMBERS')
        need(sum(x.file_size for x in rows)<=MAX_BYTES,'SOURCE_EXPANSION_LIMIT')
        files={}
        for entry in rows:
            safe_name(entry.filename)
            need(not entry.is_dir() and stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG)
                 and entry.file_size<=16*1024**2,'SOURCE_ARCHIVE_TYPE')
            files[entry.filename]=z.read(entry)
        actual=manifest(files,m['commit'],m['run_id'],m['attempt'])
        need(actual=={k:v for k,v in m.items() if k not in ('archive_sha256','archive_bytes')},'SOURCE_MANIFEST_MISMATCH')
        destination=Path(destination);destination.mkdir(exist_ok=False,mode=0o755)
        for name,raw in files.items():
            target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(raw)
    return actual
