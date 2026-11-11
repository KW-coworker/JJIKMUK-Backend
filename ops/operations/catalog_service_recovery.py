"""Restore service access for the exact inspected, already data-restored catalog run."""
from connection import HOSTS,canonical,sha
from bootstrap import need
from run import read_object,execute
from maintenance_gate import Gate
from catalog_state_inspection import REQUEST,RUN,RECEIPT_SHA

STATE_SHA='fb13fa0da139bd01e3c9c41aeec64bffa89eab5698579ed4801f787f4967ce1b'
COORD_SHA='ef1303eb1c891501120cdb73eaf17b9ad722b8beaa93b5d8fbca775745fa1571'
JOURNAL_SHA='10c110c3ad9feb726d7ce6269b187170137d0b6419e1896e0ca70e664d8b4314'
SCHEMA_SHA='b768920c4335a7d19a5e5f228a8e4f11810f40aabdc184f08d71cbdde2d4c2e6'

HOST_SCRIPT=r'''
import hashlib,json,os,re,signal,subprocess,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,'/opt/jjikmuk-cd/bin')
from host import secure,atomic_json
from manifest import require,digest
from coordination import locked,ROOT
class Deadline(BaseException):pass
def deadline(*unused):raise Deadline()
def validate_restored_state(state):
 require(state['status']=='APP_SWITCH_INTENT' and state['recovery_counts']=={'restored':618578,'never_committed':500} and
         state['recovery_verification']=={'products':1348425,'original_values_restored':True},'SERVICE_RECOVERY_DATA_PROOF')
signal.signal(signal.SIGALRM,deadline);signal.alarm(660)
try:
 require(os.geteuid()==0 and sys.flags.isolated and sys.flags.no_site,'SERVICE_RECOVERY_RUNTIME')
 stage=Path('/opt/jjikmuk-catalog-'+binding['archive_sha256'][:16]);secure(stage)
 for name,meta in envelope['files'].items():
  path=stage/name;secure(path)
  require(path.stat().st_size==meta['bytes'] and digest(path)==meta['sha256'],'SERVICE_RECOVERY_ORIGINAL_CODE')
 for phase in ('freeze','apply','recover'):
  r=subprocess.run(['/usr/bin/systemctl','is-active','jjikmuk-catalog-'+phase+'-'+binding['archive_sha256'][:16]],capture_output=True,timeout=5)
  require(r.stdout.strip() in (b'inactive',b'failed',b'unknown'),'SERVICE_RECOVERY_PRIOR_RUNNING')
 sys.path.insert(0,str(stage/'bin'))
 from catalog_host import Work
 from catalog_host_support import chatbot_state,systemctl
 work=Work(stage,binding);work.load()
 require(digest(stage/'state.json')==state_sha and digest(stage/'before-values.sqlite')==journal_sha,'SERVICE_RECOVERY_RECORD_CHANGED')
 validate_restored_state(work.state)
 require(work.host.baseline==work.state['previous'],'SERVICE_RECOVERY_BASELINE_CHANGED')
 original_coord=(ROOT/'state.json').read_bytes()
 require(hashlib.sha256(original_coord).hexdigest()==coord_sha,'SERVICE_RECOVERY_COORDINATOR_CHANGED')
 original=json.loads(original_coord)
 require(original['component']=='db' and original['operation_id']==hashlib.sha256((binding['request_id']+':'+binding['run_id']+':recover').encode()).hexdigest(), 'SERVICE_RECOVERY_COORDINATOR_OWNER')
 operation=hashlib.sha256((binding['request_id']+':service-access:'+run_id).encode()).hexdigest()
 record_path=stage/('service-recovery-'+run_id+'.json')
 require(not record_path.exists() and not record_path.is_symlink(),'SERVICE_RECOVERY_ALREADY_RECORDED')
 with locked('db',operation,recovery_sha256=coord_sha) as coordinator:
  release=work.state['candidate_release'];folder=work.host.release_path(release)
  secure(folder);secure(folder/'backend.jar')
  require((work.host.root/'current').resolve(strict=True)==folder and set(p.name for p in folder.iterdir())=={'backend.jar','manifest.json'},'SERVICE_RECOVERY_CURRENT_RELEASE')
  require(folder.stat().st_mode & 0o777==0o700 and (folder/'backend.jar').stat().st_mode & 0o777==0o644 and
          digest(folder/'backend.jar')==release['manifest']['jar_sha256'],'SERVICE_RECOVERY_ACCESS_PRECONDITION')
  require(work.host.config['db_user']=='ubuntu' and work.host.protected()==release['protected'],'SERVICE_RECOVERY_PROTECTED')
  observed=work.verify_schema()
  require(hashlib.sha256(json.dumps(observed,sort_keys=True,separators=(',',':')).encode()).hexdigest()==schema_sha,'SERVICE_RECOVERY_SCHEMA_CHANGED')
  work.host.database(release['manifest'])
  require(chatbot_state()==work.state['chatbot'],'SERVICE_RECOVERY_CHATBOT_CHANGED')
  chatbot_id=systemctl('show','food-chatbot-team.service','--property=InvocationID','--value')
  require(bool(chatbot_id),'SERVICE_RECOVERY_CHATBOT_IDENTITY')
  atomic_json(record_path,{'status':'ACCESS_REPAIR_INTENT','binding':binding,'state_sha256':state_sha,'journal_sha256':journal_sha,'operation_id':operation})
  coordinator.record('MUTATION_INTENT')
  systemctl('stop','jjikmuk-backend.service')
  os.chmod(folder,0o755)
  readable=subprocess.run(['/usr/sbin/runuser','-u','ubuntu','--','/usr/bin/test','-r',str(folder/'backend.jar')],capture_output=True,timeout=5)
  require(readable.returncode==0,'SERVICE_RECOVERY_JAR_NOT_READABLE')
  work.host.restart();work.host.verify(release,work.state['old_identity'])
  require(chatbot_state()==work.state['chatbot'] and systemctl('show','food-chatbot-team.service','--property=InvocationID','--value')==chatbot_id,'SERVICE_RECOVERY_CHATBOT_NOT_STABLE')
  require(digest(stage/'state.json')==state_sha and digest(stage/'before-values.sqlite')==journal_sha,'SERVICE_RECOVERY_ORIGINAL_RECORD_CHANGED')
  work.host.commit(release)
  atomic_json(record_path,{'status':'SERVICES_RESTORED','binding':binding,'state_sha256':state_sha,'journal_sha256':journal_sha,'operation_id':operation})
  coordinator.record('ROLLED_BACK')
  print(json.dumps({'status':'VERIFIED','checks':{'backend_healthy_60_seconds':True,'chatbot_unchanged':True,'original_records_preserved':True,'no_product_writes':True},
      'counts':{'directory_mode':folder.stat().st_mode & 0o777,'recorded_restored_products':618578,'recorded_verified_products':1348425},
      'hashes':{'backend_commit_sha256':hashlib.sha256(release['manifest']['commit'].encode()).hexdigest(),'source_state_sha256':state_sha,'source_journal_sha256':journal_sha}}))
except (Exception,Deadline) as error:
 code=str(error) if isinstance(error,ValueError) and re.fullmatch('[A-Z0-9_]{1,75}',str(error)) else type(error).__name__.upper()
 print(json.dumps({'status':'STOPPED','codes':[code]}));sys.exit(1)
'''

def document(saved,run_id):
 need(sha(canonical(saved))==RECEIPT_SHA,'SERVICE_RECOVERY_RECEIPT_CHANGED')
 import re
 need(re.fullmatch('[1-9][0-9]{0,19}',run_id),'SERVICE_RECOVERY_RUN')
 scope={'binding':saved['binding'],'envelope':saved['envelope'],'run_id':run_id,'state_sha':STATE_SHA,'coord_sha':COORD_SHA,'journal_sha':JOURNAL_SHA,'schema_sha':SCHEMA_SHA}
 script='\n'.join(k+'='+repr(v) for k,v in scope.items())+'\n'+HOST_SCRIPT
 return {'schemaVersion':'2.2','parameters':{},'description':'Repair exact inspected release directory and verify existing service',
     'mainSteps':[{'action':'aws:runShellScript','name':'report','inputs':{'timeoutSeconds':'720',
     'runCommand':["/usr/bin/python3.12 -I -S -B - <<'JJIKMUK_SERVICE_RECOVERY'\n"+script+'\nJJIKMUK_SERVICE_RECOVERY']}}]}

def restore(api,ctx):
 need(ctx['request_id']==REQUEST,'SERVICE_RECOVERY_REQUEST')
 gate,_=Gate(api['s3']).read()
 need(gate is not None and gate['request_id']==REQUEST and gate['run_id']==RUN and gate['state']=='WORKING','SERVICE_RECOVERY_GATE')
 saved=read_object(api['s3'],'receipts/catalog/'+RUN+'/binding.json')
 plan={'format':1,'component':'db','operation':'deploy','approved':True,'approval_id':'USER_SOURCE_COMPATIBILITY_AND_DB_APPLY_20261111','document':document(saved,ctx['run_id'])}
 result=execute(api,ctx,plan,sha(canonical(plan)),HOSTS['backend'])
 need(result['success'],'SERVICE_RECOVERY_FAILED_KEEP_HOLD')
 return dict(result,request_id=REQUEST,commit=ctx['commit'])
