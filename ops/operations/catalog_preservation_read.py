"""One recovered, pre-write failure: inspect state and history counts, never replay."""
import json
from connection import HOSTS, canonical, sha
from bootstrap import need
from maintenance_gate import Gate
from run import read_object, execute

REQUEST = 'a5291163ee0a456b85366e6075d8fce6'
RUN = '43030219397'
COMMIT = 'ecb1baec6f840e0b4e048899aeabf5064940463a'
RECEIPT = '94e8f4f962f4daff3e2dbc6c12526083b8f7b39fc2595698505050a0b73639ce'
RECOVERY = 'a748da85fc03bc4830c3bd0f605b8d8360207a4efed5ebe05436818169edd891'
RECOVERY_SHA = 'f51733edeba99ef400ff4c55ad072abeea339637b7e5643a228d39a59542f73c'

HOST_SCRIPT = r'''
import fcntl,hashlib,json,os,shutil,signal,subprocess,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,'/opt/jjikmuk-cd/bin')
from host import secure,read_host_state
from manifest import require,digest
from coordination import ROOT
from initial_preservation import projection
def expected_coordinator(binding):
 def phase_id(phase):
  return hashlib.sha256((binding['request_id']+':'+binding['run_id']+':'+phase).encode()).hexdigest()
 previous={'status':'MUTATION_INTENT','component':'db','operation_id':phase_id('freeze')}
 return {'status':'ROLLED_BACK','component':'db','operation_id':phase_id('recover'),
         'recovery_of':hashlib.sha256(json.dumps(previous,sort_keys=True).encode()).hexdigest()}
def history_counts(conn,bound):
 require(type(bound) is int and 0<bound<2**63,'PRESERVATION_READ_HISTORY_BOUND')
 with conn.cursor() as cur:
  cur.execute('SET SESSION MAX_EXECUTION_TIME=60000')
  cur.execute('START TRANSACTION READ ONLY')
  cur.execute('SELECT COUNT(*),COALESCE(MIN(id),0),COALESCE(MAX(id),0) FROM product_attribute_snapshots WHERE id<=%s',(bound,))
  count,low,high=cur.fetchone()
  require(all(type(n) is int and 0<=n<2**63 for n in (count,low,high)) and
          ((count==0 and low==high==0) or (0<count<=bound and 0<low<=high<=bound)),
          'PRESERVATION_READ_COUNT')
  conn.rollback()
  return count,low,high
class ReadDeadline(BaseException):pass
def alarm(*unused):raise ReadDeadline()
signal.signal(signal.SIGALRM,alarm);signal.alarm(90)
try:
 require(os.geteuid()==0 and sys.flags.isolated and sys.flags.no_site,'PRESERVATION_READ_RUNTIME')
 stage=Path('/opt/jjikmuk-catalog-'+binding['archive_sha256'][:16]);secure(stage)
 for name,meta in envelope['files'].items():
  p=stage/name;secure(p)
  require(p.stat().st_size==meta['bytes'] and digest(p)==meta['sha256'],'PRESERVATION_READ_CODE')
 for p in (ROOT,ROOT/'host.lock',ROOT/'state.json'):secure(p)
 with (ROOT/'host.lock').open('r') as lock:
  fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  raw_coord=(ROOT/'state.json').read_bytes();coord=json.loads(raw_coord)
  require(coord==expected_coordinator(binding),'PRESERVATION_READ_COORDINATOR')
  for phase in ('freeze','apply','recover'):
   unit='jjikmuk-catalog-'+phase+'-'+binding['archive_sha256'][:16]
   r=subprocess.run(['/usr/bin/systemctl','is-active',unit],capture_output=True,timeout=5)
   require(r.stdout.strip() in (b'inactive',b'failed',b'unknown'),'PRESERVATION_READ_ACTIVE_WORK')
  sys.path.insert(0,str(stage/'bin'))
  from catalog_host import Work
  from catalog_host_support import chatbot_state
  from catalog_progress import read_fixed,identity
  work=Work(stage,binding);work.load()
  raw_state=(stage/'state.json').read_bytes();state=work.state
  require(state['status']=='RECOVERED' and state['binding']==binding and
          state['previous']==work.host.baseline,'PRESERVATION_READ_STATE')
  require(not any(k in state for k in ('preservation','candidate_release','counts','recovery_counts',
          'value_verification','recovery_verification')),'PRESERVATION_READ_UNEXPECTED_WRITES')
  require(not (stage/'before-values.sqlite').exists(),'PRESERVATION_READ_UNEXPECTED_JOURNAL')
  before_chat=chatbot_state();before_identity=work.host.identity()
  require(before_chat==state['chatbot'] and work.host.protected()==state['previous']['protected'],
          'PRESERVATION_READ_SERVICE_CHANGED')
  shapes=projection(state['schema']);tables=sorted(shapes)
  require('product_attribute_snapshots' in tables,'PRESERVATION_READ_HISTORY_TABLE')
  bound=state['bounds']['snapshot_id']
  with work.connect() as conn:count,low,high=history_counts(conn,bound)
  require(raw_state==(stage/'state.json').read_bytes() and raw_coord==(ROOT/'state.json').read_bytes(),
          'PRESERVATION_READ_RECORD_CHANGED')
  require(work.host.identity()==before_identity and chatbot_state()==before_chat and
          work.host.protected()==state['previous']['protected'],'PRESERVATION_READ_SERVICE_CHANGED')
  progress=read_fixed(stage,identity(binding,'freeze'))
  require(progress is not None,'PRESERVATION_READ_PROGRESS_MISSING')
  report={'status':'VERIFIED','checks':{'read_only':True,'no_product_values':True,'no_service_change':True,
    'prewrite_failure':True},
    'counts':{'preserved_history_rows':count,'history_min_id':low,'history_max_id':high,
      'snapshot_id_bound':bound,'previous_row_limit':3000000,'history_table_index':tables.index('product_attribute_snapshots'),
      'table_count':len(tables),'host_free_bytes':shutil.disk_usage(stage).free,
      'history_exceeds_previous_limit':int(count>3000000)},
    'hashes':{'state_sha256':hashlib.sha256(raw_state).hexdigest(),
      'coordinator_sha256':hashlib.sha256(raw_coord).hexdigest()},
    'codes':['FROZEN_PROGRESS_'+progress['stage'],'FROZEN_ERROR_'+(progress['error_code'] or 'NONE')]}
  print(json.dumps(report))
except BaseException as error:
 import re
 code=str(error) if isinstance(error,ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{0,79}',str(error)) else type(error).__name__.upper()
 print(json.dumps({'status':'STOPPED','codes':[code]}));sys.exit(1)
'''


def document(saved):
    need(sha(canonical(saved)) == RECEIPT, 'PRESERVATION_READ_RECEIPT')
    binding = saved['binding']
    need(binding['run_id'] == RUN and binding['commit'] == COMMIT and binding['request_id'] == REQUEST,
         'PRESERVATION_READ_BINDING')
    script = 'binding=' + repr(binding) + '\nenvelope=' + repr(saved['envelope']) + '\n' + HOST_SCRIPT
    need(len(script.encode()) < 60000, 'PRESERVATION_READ_SIZE')
    return {'schemaVersion': '2.2', 'parameters': {}, 'description': 'Fixed prewrite failure state and bounded history count only',
            'mainSteps': [{'action': 'aws:runShellScript', 'name': 'report', 'inputs': {'timeoutSeconds': '120',
                'runCommand': ["/usr/bin/python3.12 -I -S -B - <<'JJIKMUK_PRESERVATION_READ'\n" + script + '\nJJIKMUK_PRESERVATION_READ']}}]}


def inspect(api, ctx):
    need(ctx['request_id'] == REQUEST, 'PRESERVATION_READ_REQUEST')
    gate, unused = Gate(api['s3']).read()
    need(gate is not None and gate['state'] == 'WORKING' and gate['request_id'] == REQUEST
         and gate['run_id'] == RUN and gate['commit'] == COMMIT, 'PRESERVATION_READ_GATE')
    recovery = read_object(api['s3'], 'receipts/' + RECOVERY + '/result.json')
    need(sha(canonical(recovery)) == RECOVERY_SHA, 'PRESERVATION_READ_RECOVERY')
    saved = read_object(api['s3'], 'receipts/catalog/' + RUN + '/binding.json')
    plan = {'format': 1, 'component': 'db', 'operation': 'inspect', 'approved': True,
            'approval_id': 'USER_SOURCE_COMPATIBILITY_AND_DB_APPLY_20261111', 'document': document(saved)}
    result = execute(api, ctx, plan, sha(canonical(plan)), HOSTS['backend'])
    need(result['success'], 'PRESERVATION_READ_FAILED')
    return dict(result, request_id=REQUEST, commit=ctx['commit'])
