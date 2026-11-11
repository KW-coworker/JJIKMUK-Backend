"""Private image-list stage and bounded slices. No service stop or application deployment."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import sys
import time
import zipfile

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),'/opt/jjikmuk-cd/bin']
from product_image_patch import require


def save(path,value):
    with path.open('x',encoding='utf-8') as f:
        os.chmod(path,0o600);json.dump(value,f,ensure_ascii=False,allow_nan=False)
        f.flush();os.fsync(f.fileno())
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024**2),b''):h.update(block)
    return h.hexdigest()


def context():
    from deploy import load_config
    from host import Host
    require(os.geteuid()==0 and sys.flags.isolated and sys.flags.no_site,'IMAGES_RUNTIME')
    spec=json.loads((ROOT/'input.json').read_bytes())
    require(spec['source_sha256']=='aa402ea6c9a0be6cfdc6f1f214ce0aa4a12c08f75d032a5a367d113b671672dc'
            and spec['rows']==1098863 and spec['backend_commit']=='70dc1a70fff94dd0bee30f34638a15add23c0f26','IMAGES_EXACT_SOURCE')
    config=load_config();host=Host(config)
    require(host.baseline['manifest']['commit']==spec['backend_commit'],'IMAGES_BACKEND_CHANGED')
    host.runtime(host.baseline)
    return spec,config,host


def connection(config):
    from database_probe import load_vendor,properties
    load_vendor();import pymysql
    db=config['database'];props=properties(db['properties_file'])
    require(props['spring.datasource.url']==db['expected_jdbc_url'] and db['name']=='jjikmuk' and
            db['host']=='jjikmuk-dev-db.cp22o82i4ex5.ap-northeast-2.rds.amazonaws.com','IMAGES_DATABASE')
    return pymysql.connect(host=db['host'],port=3306,database=db['name'],user=props['spring.datasource.username'],
        password=props['spring.datasource.password'],ssl_ca=db['ca_file'],ssl_verify_cert=True,ssl_verify_identity=True,
        connect_timeout=5,read_timeout=30,write_timeout=10,autocommit=False,local_infile=False,charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor)


def source(spec):
    from host import secure
    path=ROOT/'input.sqlite';secure(path)
    require(path.stat().st_size==spec['input_bytes'] and digest(path)==spec['input_sha256'],'IMAGES_INPUT_HASH')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-16384')
    require(db.execute('SELECT COUNT(*) FROM inputs').fetchone()[0]==spec['rows'],'IMAGES_INPUT_COUNT')
    return db


def prepare():
    signal.alarm(600)
    spec,config,host=context();identity=host.unit('InvocationID')
    require(shutil.disk_usage(ROOT).free>spec['input_bytes']+3*1024**3,'IMAGES_HOST_SPACE')
    count=0
    with gzip.open(ROOT/'input.sqlite.gz','rb') as src,(ROOT/'input.sqlite').open('xb') as dst:
        os.chmod(dst.name,0o400)
        for block in iter(lambda:src.read(1024**2),b''):
            count+=len(block);require(count<=spec['input_bytes'],'IMAGES_DECOMPRESSED_LIMIT');dst.write(block)
        dst.flush();os.fsync(dst.fileno())
    data=source(spec)
    try:
        require(data.execute('PRAGMA quick_check').fetchone()[0]=='ok','IMAGES_INPUT_INTEGRITY')
        previous=0;total=0
        for i,s in enumerate(spec['slices']):
            require(s['index']==i and s['after_id']==previous and 0<s['count']<=20000,'IMAGES_SLICE_ORDER')
            found=data.execute('SELECT COUNT(*),MAX(product_id) FROM inputs WHERE product_id>? AND product_id<=?',(s['after_id'],s['last_id'])).fetchone()
            require(found==(s['count'],s['last_id']),'IMAGES_SLICE_COUNT');previous=s['last_id'];total+=s['count']
        require(total==spec['rows'],'IMAGES_SLICE_TOTAL')
    finally:data.close()
    runtime=ROOT/'runtime';runtime.mkdir(mode=0o700)
    with zipfile.ZipFile(host.release_path(host.baseline)/'backend.jar') as jar:
        for info in jar.infolist():
            prefix='BOOT-INF/classes/' if info.filename.startswith('BOOT-INF/classes/') and info.filename.endswith('.class') else 'BOOT-INF/lib/' if info.filename.startswith('BOOT-INF/lib/') and info.filename.endswith('.jar') else None
            if prefix is None:continue
            name=Path(info.filename.removeprefix(prefix));require(not name.is_absolute() and '..' not in name.parts,'IMAGES_JAR_PATH')
            target=runtime/('classes' if prefix=='BOOT-INF/classes/' else 'lib')/name
            target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with target.open('xb') as f:f.write(jar.read(info))
            os.chmod(target,0o600)
    (ROOT/'slices').mkdir(mode=0o700)
    require(host.unit('InvocationID')==identity,'IMAGES_SERVICE_CHANGED')
    save(ROOT/'result.json',{'status':'VERIFIED','operation_id':os.environ['JJIKMUK_OPERATION_ID'],
        'checks':{'private_input_verified':True,'slices_bound':True,'service_unchanged':True,'no_database_write':True}})


def apply_slice(index):
    from catalog_codec import Codec
    from host import secure
    from product_images_writer import Writer,Journal
    signal.alarm(1200);started=time.monotonic()
    spec,config,host=context();identity=host.unit('InvocationID')
    require(0<=index<len(spec['slices']),'IMAGES_SLICE_INDEX')
    s=spec['slices'][index];folder=ROOT/'slices'/f'{index:03d}'
    secure(folder);require(shutil.disk_usage(folder).free>2*1024**3+128*1024**2,'IMAGES_HOST_SPACE')
    data=source(spec)
    codec_class=Path('/opt/jjikmuk-catalog-2181e6fd7c0fba39/bin/java/CatalogCodec.class');secure(codec_class)
    require(digest(codec_class)=='070ec66de86fd6e6164aa93b04045c53c2b3be75531af9efc94b24df0ffae202','IMAGES_CODEC_CLASS')
    pure=Codec(['/usr/bin/java','-Xms32m','-Xmx192m','-cp',str(ROOT/'runtime/classes')+':'+str(ROOT/'runtime/lib/*')+':'+str(codec_class.parent),'CatalogCodec'])
    operation=os.environ['JJIKMUK_OPERATION_ID']
    journal=Journal(folder/'journal.sqlite',json.dumps({'operation':operation,'input':spec['input_sha256'],'slice':s},sort_keys=True))
    c=connection(config);counts={'checked':0,'changed':0,'last_id':s['after_id']}
    try:
        writer=Writer(c,pure,journal,operation);writer.setup()
        while True:
            rows=[{'product_id':pid,'image_url':url} for pid,url in data.execute('SELECT product_id,image_url FROM inputs WHERE product_id>? AND product_id<=? ORDER BY product_id LIMIT 500',(counts['last_id'],s['last_id']))]
            if not rows:break
            require(time.monotonic()-started<1100 and shutil.disk_usage(folder).free>2*1024**3,'IMAGES_ADMISSION_STOP_KEEP_COMPLETED')
            result=writer.batch(rows)
            counts['checked']+=result['checked'];counts['changed']+=result['changed'];counts['last_id']=result['last_id']
            with (folder/'progress.jsonl').open('a',encoding='utf-8') as log:
                os.chmod(log.name,0o600);log.write(json.dumps(dict(counts,elapsed_seconds=round(time.monotonic()-started,2)))+'\n');log.flush()
        require(counts['checked']==s['count'] and counts['last_id']==s['last_id'],'IMAGES_SLICE_INCOMPLETE')
    finally:c.close();pure.close();journal.close();data.close()
    require(host.unit('InvocationID')==identity,'IMAGES_SERVICE_CHANGED');host.runtime(host.baseline)
    counts['elapsed_ms']=int((time.monotonic()-started)*1000)
    save(folder/'result.json',{'status':'VERIFIED','operation_id':operation,'counts':counts,
        'checks':{'source_slice_complete':True,'other_product_fields_preserved':True,'same_service_running':True,'before_values_saved':True}})


if __name__=='__main__':
    if len(sys.argv)==1:prepare()
    else:
        require(len(sys.argv)==3 and sys.argv[1]=='apply' and sys.argv[2].isdigit(),'IMAGES_ENTRY_ARGUMENTS')
        apply_slice(int(sys.argv[2]))
