"""Inspect only product column names/types after the bounded reader rejected drift."""
import json

SOURCE='/opt/jjikmuk-db-compare-ff115d01ea3fb49d6368/source-fingerprints.sqlite'
SOURCE_SHA='b0c36f25372234ba17e5e9559a36552b06e0c1b589471a8c69d8f34ba6a5aa4d'

CHILD=r'''
import hashlib,json,os,re,sqlite3,sys
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0,'/opt/jjikmuk-cd/bin')
from database_probe import load_vendor,properties

def need(ok,code):
    if not ok:raise ValueError(code)

def describe(expected,actual):
    need(len(actual)<=100 and len(expected)<=100,'SCHEMA_LIMIT')
    need(all(re.fullmatch('[a-z][a-z0-9_]{0,63}',k) for k in actual),'SCHEMA_NAME')
    optional={'image_role','image_display_notice','image_asset_sha256','image_assignment_run'}
    codes=[]
    for kind,names in [('EXTRA',set(actual)-set(expected)),('MISSING',set(expected)-set(actual)-optional),
                       ('TYPE_DIFF',{k for k in set(actual)&set(expected) if actual[k]!=expected[k]})]:
        for name in sorted(names):
            code=kind+'_'+name.upper();need(len(code)<=80,'SCHEMA_CODE_LIMIT');codes.append(code)
            if name in actual:
                value=actual[name]
                need(re.fullmatch('[a-z0-9_(), ]{1,64}',value),'SCHEMA_TYPE')
                value=re.sub('[(), ]+','_',value).strip('_').upper()
                code='ACTUAL_'+name.upper()+'__'+value
                need(len(code)<=80,'SCHEMA_CODE_LIMIT');codes.append(code)
    need(len(codes)<=50,'SCHEMA_DIFFERENCE_LIMIT')
    return {'status':'VERIFIED','codes':codes,'counts':{'source_columns':len(expected),
        'operating_columns':len(actual),'extra_columns':len(set(actual)-set(expected)),
        'missing_required_columns':len(set(expected)-set(actual)-optional),
        'image_columns_present':len(set(actual)&optional),'db_connections':1,'db_writes':0,'product_rows_read':0},
        'checks':{'schema_metadata_read_only':True,'same_compared_schema':not bool(codes)},
        'hashes':{'actual_schema':hashlib.sha256(json.dumps(actual,sort_keys=True).encode()).hexdigest()}}

def run():
    need(os.geteuid()!=0 and sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,'ISOLATION_REQUIRED')
    config=json.loads(sys.stdin.buffer.read(65537));db=config['database']
    need(db['host']=='jjikmuk-dev-db.cp22o82i4ex5.ap-northeast-2.rds.amazonaws.com' and db['name']=='jjikmuk'
         and db['properties_file']=='/home/ubuntu/JJIKMUK-Backend/application-local.properties'
         and db['ca_file']=='/opt/food-chatbot/rds-global-bundle.pem','FIXED_DATABASE')
    props=properties(db['properties_file']);need(props['spring.datasource.url']==db['expected_jdbc_url'],'DATABASE_URL_CHANGED')
    target=urlsplit(db['expected_jdbc_url'].removeprefix('jdbc:'))
    need(db['expected_jdbc_url'].startswith('jdbc:mysql://') and target.hostname==db['host'] and
         (target.port or 3306)==3306 and target.path=='/jjikmuk' and not target.username and not target.password,'DATABASE_URL_TARGET')
    with sqlite3.connect(Path(SOURCE).as_uri()+'?mode=ro',uri=True) as source:
        expected=dict(json.loads(source.execute("SELECT value FROM metadata WHERE key='columns'").fetchone()[0]))
    load_vendor();import pymysql
    conn=pymysql.connect(host=db['host'],port=3306,database='jjikmuk',user=props['spring.datasource.username'],
        password=props['spring.datasource.password'],ssl_ca=db['ca_file'],ssl_verify_cert=True,ssl_verify_identity=True,
        connect_timeout=5,read_timeout=15,write_timeout=5,autocommit=True,charset='utf8mb4')
    try:
        with conn.cursor() as cur:
            cur.execute('SET SESSION MAX_EXECUTION_TIME=10000')
            cur.execute('SET SESSION TRANSACTION READ ONLY')
            cur.execute('START TRANSACTION READ ONLY')
            cur.execute('SELECT DATABASE(),@@transaction_read_only')
            need(cur.fetchone()==('jjikmuk',1),'READONLY_REQUIRED')
            cur.execute('SELECT COLUMN_NAME,COLUMN_TYPE FROM information_schema.COLUMNS '
                'WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION LIMIT 101',('jjikmuk','products'))
            actual=dict(cur.fetchmany(101))
        result=describe(expected,actual);conn.rollback();return result
    finally:conn.close()

try:print(json.dumps(run()))
except BaseException as e:
    code=str(e) if isinstance(e,ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{0,69}',str(e)) else 'SCHEMA_INSPECTION_FAILED'
    print(json.dumps({'status':'STOPPED','codes':[code]}));raise SystemExit(1)
'''

PARENT=r'''
import fcntl,hashlib,json,os,re,signal,subprocess,sys
from pathlib import Path
def need(ok,code):
    if not ok:raise ValueError(code)
def secure(path):
    p=Path(path)
    for item in [p,*p.parents]:
        s=item.lstat();need(not item.is_symlink() and s.st_uid==0 and not s.st_mode&0o022,'UNTRUSTED_PATH')
    return p
try:
    need(os.geteuid()==0,'ROOT_LAUNCHER_REQUIRED')
    sys.path.insert(0,str(secure('/opt/jjikmuk-cd/bin')))
    from host import Host
    from coordination import TERMINAL
    with secure('/var/lib/jjikmuk-operations/host.lock').open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        need(json.loads(secure('/var/lib/jjikmuk-operations/state.json').read_bytes())['status'] in TERMINAL,'UNRESOLVED_HOST_OPERATION')
        with secure(SOURCE).open('rb') as f:need(hashlib.file_digest(f,'sha256').hexdigest()==SOURCE_SHA,'SOURCE_HASH')
        config=json.loads(secure('/etc/jjikmuk-cd/config.json').read_bytes());host=Host(config)
        host.runtime(host.baseline);before=host.identity()
        process=subprocess.Popen(['/usr/sbin/runuser','-u','ubuntu','--','/usr/bin/python3.12','-I','-S','-B','-c',
            'SOURCE='+repr(SOURCE)+'\n'+CHILD],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env={'PATH':'/usr/bin:/bin','HOME':'/home/ubuntu'})
        try:stdout,stderr=process.communicate(json.dumps({'database':config['database']}).encode(),timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.communicate(timeout=10)
            raise ValueError('SCHEMA_CHILD_TIMEOUT')
        need(not stderr and len(stdout)<=16384,'SCHEMA_CHILD_OUTPUT')
        value=json.loads(stdout)
        if value.get('status')=='STOPPED':
            codes=value.get('codes',[])
            need(type(codes) is list and len(codes)==1 and type(codes[0]) is str and
                 re.fullmatch('[A-Z][A-Z0-9_]{0,69}',codes[0]),'SCHEMA_CHILD_CODE')
            raise ValueError(codes[0])
        need(process.returncode==0 and value['status']=='VERIFIED','SCHEMA_NOT_VERIFIED')
        host.runtime(host.baseline);need(host.identity()==before,'BACKEND_PROCESS_CHANGED')
        value['checks']['same_backend_process']=True;value['checks']['protected_files_unchanged']=True
        print(json.dumps(value))
except BaseException as e:
    code=str(e) if isinstance(e,ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{0,69}',str(e)) else 'SCHEMA_LAUNCHER_FAILED'
    print(json.dumps({'status':'STOPPED','codes':[code]}));raise SystemExit(1)
'''

def document():
    script='SOURCE='+repr(SOURCE)+'\nSOURCE_SHA='+repr(SOURCE_SHA)+'\nCHILD='+repr(CHILD)+'\n'+PARENT
    return {'schemaVersion':'2.2','description':'Inspect product column names/types only; no product rows or DB changes',
        'parameters':{},'mainSteps':[{'name':'report','action':'aws:runShellScript','inputs':{'timeoutSeconds':'180',
        'runCommand':["/usr/bin/python3 -I -S -B <<'SCHEMA_METADATA_ONLY'\n"+script+"\nSCHEMA_METADATA_ONLY"]}}]}
