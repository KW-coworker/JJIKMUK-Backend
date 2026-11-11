"""Read the single stopped catalog run. No application or DB writes/restarts."""
from connection import HOSTS,canonical,sha
from bootstrap import need
from run import read_object,execute
from maintenance_gate import Gate

REQUEST='a5291163ee0a456b85366e6075d8fce6'
RUN='42937366781'
RECEIPT_SHA='7b143aef536667c41f23f84cba2f694939c24d4d361f86e3973e524845dd24ad'


def document(saved):
    need(sha(canonical(saved))==RECEIPT_SHA,'CATALOG_INSPECTION_RECEIPT_CHANGED')
    binding,envelope=saved['binding'],saved['envelope']
    stage='/opt/jjikmuk-catalog-'+binding['archive_sha256'][:16]
    script=f'''
import fcntl,hashlib,json,os,re,signal,sqlite3,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,'/opt/jjikmuk-cd/bin')
from host import secure,read_host_state
from manifest import require,digest
stage=Path({stage!r});binding={binding!r};expected={envelope!r}
class InspectionDeadline(BaseException):pass
def deadline(*unused):raise InspectionDeadline()
signal.signal(signal.SIGALRM,deadline);signal.alarm(420)
try:
 require(os.geteuid()==0 and sys.flags.isolated and sys.flags.no_site,'CATALOG_INSPECTION_RUNTIME')
 secure(stage)
 for name,meta in expected['files'].items():
  p=stage/name;secure(p);require(p.stat().st_size==meta['bytes'] and digest(p)==meta['sha256'],'CATALOG_INSPECTION_CODE_CHANGED')
 from coordination import ROOT
 secure(ROOT/'host.lock');secure(ROOT/'state.json')
 with (ROOT/'host.lock').open('r') as lock:
  fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  coordination=(ROOT/'state.json').read_bytes();state_coord=json.loads(coordination)
  require(state_coord.get('operation_id')==hashlib.sha256(({REQUEST!r}+':recover').encode()).hexdigest() and
          state_coord.get('status')=='MANUAL_RECOVERY_REQUIRED','CATALOG_INSPECTION_COORDINATOR')
  sys.path.insert(0,str(stage/'bin'))
  from catalog_host import Work
  from catalog_host_support import chatbot_state,systemctl,UNITS
  from initial_schema import read_from_connection
  import subprocess
  for phase in ('freeze','apply','recover'):
   unit='jjikmuk-catalog-'+phase+'-'+binding['archive_sha256'][:16]
   observed=subprocess.run(['/usr/bin/systemctl','is-active',unit],capture_output=True,timeout=5)
   require(observed.stdout.strip() in (b'inactive',b'failed',b'unknown'),'CATALOG_INSPECTION_UNIT_RUNNING')
  work=Work(stage,binding);work.load();before=(stage/'state.json').read_bytes()
  require(work.state['status']=='APP_SWITCH_INTENT','CATALOG_INSPECTION_STATE')
  with work.connect() as conn:current=read_from_connection(conn)
  journal_path=stage/'before-values.sqlite';secure(journal_path)
  with sqlite3.connect(journal_path.as_uri()+'?mode=ro',uri=True) as journal:
   journal.execute('PRAGMA query_only=ON')
   changes=journal.execute('SELECT COUNT(*) FROM changes').fetchone()[0]
  first=chatbot_state();invocation=systemctl('show',UNITS[1],'--property=InvocationID','--value')
  work.host.verify(work.state['previous'],'')
  now=chatbot_state();previous=work.state['chatbot']
  require(now==first and invocation==systemctl('show',UNITS[1],'--property=InvocationID','--value'),
          'CATALOG_INSPECTION_CHATBOT_UNSTABLE')
  require((stage/'state.json').read_bytes()==before and (ROOT/'state.json').read_bytes()==coordination,'CATALOG_INSPECTION_STATE_CHANGED')
  counts={{'schema_matches_before':int(current==work.state['schema']),'journal_changes':changes,
    'flyway_started':int((stage/'flyway-owned').exists()),'chatbot_runtime_matches_before':int(now['runtime']==previous['runtime']),
    'chatbot_uid_matches_before':int(now['uid']==previous['uid']),'chatbot_cwd_matches_before':int(now['cwd']==previous['cwd']),
    'backend_active':int(systemctl('show',UNITS[0],'--property=ActiveState','--value')=='active'),
    'chatbot_active':int(systemctl('show',UNITS[1],'--property=ActiveState','--value')=='active')}}
  pid=systemctl('show',UNITS[1],'--property=MainPID','--value');require(pid.isdigit(),'CATALOG_INSPECTION_PID')
  keys=[x.split(b'=',1)[0] for x in (Path('/proc')/pid/'environ').read_bytes().split(b'\\0') if b'=' in x]
  for key in (b'MEMORY_PRESSURE_WATCH',b'MEMORY_PRESSURE_WRITE',b'LISTEN_PID',b'LISTEN_FDS',b'LISTEN_FDNAMES'):
   counts['systemd_env_'+key.decode()]=int(key in keys)
  print(json.dumps({{'status':'VERIFIED','checks':{{'read_only':True,'old_backend_health_verified':True,
    'chatbot_stable_60_seconds':True,'records_unchanged':True}},'counts':counts,
    'hashes':{{'state_sha256':hashlib.sha256(before).hexdigest(),'coordination_sha256':hashlib.sha256(coordination).hexdigest(),
    'chatbot_current_runtime':now['runtime'],'chatbot_previous_runtime':previous['runtime']}}}}))
except (Exception,InspectionDeadline) as error:
 code=str(error) if isinstance(error,ValueError) and re.fullmatch('[A-Z0-9_]{{1,70}}',str(error)) else type(error).__name__.upper()
 print(json.dumps({{'status':'STOPPED','codes':[code]}}));sys.exit(1)
'''
    return {'schemaVersion':'2.2','parameters':{},'description':'Read stopped catalog run state and stable original services',
            'mainSteps':[{'action':'aws:runShellScript','name':'report','inputs':{'timeoutSeconds':'480',
            'runCommand':["/usr/bin/python3.12 -I -S -B - <<'JJIKMUK_CATALOG_INSPECTION'\n"+script+'\nJJIKMUK_CATALOG_INSPECTION']}}]}


def inspect(api,ctx):
    need(ctx['request_id']==REQUEST,'CATALOG_INSPECTION_REQUEST')
    gate,_=Gate(api['s3']).read()
    need(gate is not None and gate['request_id']==REQUEST and gate['run_id']==RUN and gate['state']=='WORKING',
         'CATALOG_INSPECTION_GATE')
    saved=read_object(api['s3'],'receipts/catalog/'+RUN+'/binding.json')
    plan={'format':1,'component':'db','operation':'inspect','approved':True,
          'approval_id':'USER_SOURCE_COMPATIBILITY_AND_DB_APPLY_20261111','document':document(saved)}
    result=execute(api,ctx,plan,sha(canonical(plan)),HOSTS['backend'])
    need(result['success'],'CATALOG_INSPECTION_FAILED')
    return dict(result,request_id=REQUEST,commit=ctx['commit'])
