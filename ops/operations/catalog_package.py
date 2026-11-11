"""Build an immutable main JAR + reviewed maintenance helpers, without product data."""
import json,os,re,subprocess,sys,zipfile
from pathlib import Path
from connection import canonical,sha
from bootstrap import need
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cd'))
from manifest import make_manifest,digest

SOURCE_SHA='f277f176e199336e7d4dcc8058c64a1d3b87c3b5768171691c3eb11f29ba1e4f'
SOURCE_BYTES=1052856320
ARCHIVE_SHA='d228022bd57af796c9b0a785438435596c5e203887fb53d2dd622425eed331b6'
ARCHIVE_BYTES=107030642
PREVIOUS='c155c14332774510a8017185b33a2e8734959ced'


def source_plan(path,expected):
    need(re.fullmatch(r'ops/operations/plans/catalog-[a-z0-9-]+\.json',path) and re.fullmatch('[a-f0-9]{64}',expected),'CATALOG_PLAN_PATH')
    file=Path(path);raw=file.read_bytes();need(len(raw)<8192 and sha(raw)==expected,'CATALOG_PLAN_HASH')
    value=json.loads(raw)
    return validate_source_plan(value)


def validate_source_plan(value):
    need(set(value)=={'approved','approval_id','source_key','source_version','source_archive_sha256','source_archive_bytes',
                     'source_sqlite_sha256','source_sqlite_bytes','previous_commit','required_bytes'},'CATALOG_PLAN_FIELDS')
    need(value['approved'] is True and value['approval_id']=='USER_SOURCE_COMPATIBILITY_AND_DB_APPLY_20261111','CATALOG_APPROVAL')
    need(re.fullmatch('operations/private/[a-f0-9]{32}/'+ARCHIVE_SHA+r'\.zip',value['source_key']) and
         re.fullmatch('[A-Za-z0-9._~+/-]{1,1024}',value['source_version']) and value['source_version']!='null','CATALOG_SOURCE_OBJECT')
    need(value['source_archive_sha256']==ARCHIVE_SHA and value['source_archive_bytes']==ARCHIVE_BYTES and
         value['source_sqlite_sha256']==SOURCE_SHA and value['source_sqlite_bytes']==SOURCE_BYTES and
         value['previous_commit']==PREVIOUS and type(value['required_bytes']) is int and value['required_bytes']>=5*1024**3,
         'CATALOG_FIXED_SOURCE_BINDING')
    return value


def build(repo,ctx):
    folder=repo/'build/catalog-maintenance';folder.mkdir()
    jars=[p for p in (repo/'build/libs').glob('*.jar') if not p.name.endswith('-plain.jar')]
    need(len(jars)==1,'CATALOG_ONE_JAR')
    manifest=make_manifest(jars[0],ctx['commit'],ctx['run_id'],'1')
    compile_dir=folder/'compile';compile_dir.mkdir()
    with zipfile.ZipFile(jars[0]) as z:
        for info in z.infolist():
            if info.filename.startswith('BOOT-INF/lib/') and info.filename.endswith('.jar'):
                target=compile_dir/Path(info.filename).name;target.write_bytes(z.read(info))
        for info in z.infolist():
            if info.filename.startswith('BOOT-INF/classes/') and info.filename.endswith('.class'):
                target=compile_dir/'classes'/info.filename.removeprefix('BOOT-INF/classes/')
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(info))
    subprocess.run(['javac','-cp',str(compile_dir/'*')+os.pathsep+str(compile_dir/'classes'),'-d',str(compile_dir),
                    *[str(repo/'ops/cd/java'/name) for name in ('InitialSchema.java','CatalogSchema.java','CatalogCodec.java')]],
                   check=True,timeout=90,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    sdk=folder/'sdk';sdk.mkdir()
    subprocess.run([sys.executable,'-m','pip','download','--require-hashes','--only-binary=:all:','--dest',str(sdk),
                    '-r',str(repo/'ops/operations/requirements.lock')],check=True,timeout=180,stdout=subprocess.DEVNULL)
    pins=re.findall(r'^([a-z0-9-]+)==([^ ]+) --hash=sha256:([a-f0-9]{64})$',
                    (repo/'ops/operations/requirements.lock').read_text(),flags=re.M)
    need(len(pins)==7 and len(list(sdk.iterdir()))==7,'CATALOG_SDK_COUNT')
    files={'backend.jar':jars[0]};generated={};lock={}
    for name,version,expected in pins:
        matches=list(sdk.glob(name.replace('-','_')+'-'+version+'-*.whl'))
        need(len(matches)==1 and digest(matches[0])==expected,'CATALOG_SDK_HASH')
        files['vendor/'+matches[0].name]=matches[0];lock[matches[0].name]=expected
    generated['vendor/sdk-lock.json']=canonical(lock)
    for path in compile_dir.glob('*.class'):files['bin/java/'+path.name]=path
    operations=('catalog_host','catalog_host_support','catalog_writer','catalog_checks','catalog_codec','catalog_delta','catalog_compare',
                'catalog_preservation','catalog_followup_host','readiness_probe','readiness_paths','fulltext_definition')
    for name in operations:files['bin/'+name+'.py']=repo/'ops/operations'/(name+'.py')
    for name in ('initial_guard','initial_schema','initial_schema_contract','initial_contract','initial_db_facts','initial_service_state','initial_preservation','initial_flyway'):
        files['bin/'+name+'.py']=repo/'ops/cd'/(name+'.py')
    entries={name:{'sha256':digest(path),'bytes':path.stat().st_size} for name,path in files.items()}
    entries.update({name:{'sha256':sha(raw),'bytes':len(raw)} for name,raw in generated.items()})
    envelope={'format':1,'commit':ctx['commit'],'jar_sha256':manifest['jar_sha256'],'files':entries}
    archive=folder/'payload.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name,path in files.items():z.write(path,name)
        for name,raw in generated.items():z.writestr(name,raw)
        z.writestr('payload-manifest.json',canonical(envelope))
    need(archive.stat().st_size<256*1024**2,'CATALOG_CODE_PACKAGE_SIZE')
    return archive,envelope,manifest
