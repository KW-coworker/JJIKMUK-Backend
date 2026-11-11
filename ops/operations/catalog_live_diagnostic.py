"""Bounded metadata-only observation of the currently running catalog job."""
import json,re
from pathlib import Path
from bootstrap import need
from connection import HOSTS,canonical,sha
from run import read_object,execute
from maintenance_gate import Gate

RUN='42984831949'
COMMIT='2d01af1f5f139b3c650e93f477e2f4216ccf52e2'
REQUEST='a5291163ee0a456b85366e6075d8fce6'


def document(saved,expected_sha):
    need(re.fullmatch('[a-f0-9]{64}',expected_sha) and sha(canonical(saved))==expected_sha,'LIVE_DIAGNOSTIC_RECEIPT_CHANGED')
    from catalog_reapply_contract import validate_binding
    binding=saved['binding'];validate_binding(binding)
    need(binding['run_id']==RUN and binding['commit']==COMMIT and binding['request_id']==REQUEST,'LIVE_DIAGNOSTIC_BINDING')
    need(type(saved['envelope']['files']) is dict and 0<len(saved['envelope']['files'])<=100,'LIVE_DIAGNOSTIC_FILES')
    stage='/opt/jjikmuk-catalog-'+binding['archive_sha256'][:16]
    source=Path(__file__).with_name('catalog_live_sql.py').read_text(encoding='utf-8')
    script=source+f'''
import json,os,signal,sys,re
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,'/opt/jjikmuk-cd/bin')
from host import secure
from manifest import require,digest
stage=Path({stage!r});binding={binding!r};expected={saved['envelope']!r}
class ReadDeadline(BaseException):pass
def deadline(*unused):raise ReadDeadline()
signal.signal(signal.SIGALRM,deadline);signal.alarm(40)
try:
 require(os.geteuid()==0 and sys.flags.isolated and sys.flags.no_site,'LIVE_DIAGNOSTIC_RUNTIME')
 secure(stage)
 for name,meta in expected['files'].items():
  require(not Path(name).is_absolute() and '..' not in Path(name).parts,'LIVE_DIAGNOSTIC_PATH')
  p=stage/name;secure(p);require(p.stat().st_size==meta['bytes'] and digest(p)==meta['sha256'],'LIVE_DIAGNOSTIC_CODE')
 sys.path.insert(0,str(stage/'bin'))
 from catalog_host import Work
 with Work(stage,binding).connect(dictionary=True) as conn:
  counts=collect(conn)
 print(json.dumps({{'status':'VERIFIED','checks':{{'metadata_only':True,'no_product_rows':True,'no_service_change':True}},'counts':counts}}))
except BaseException as error:
 code=type(error).__name__.upper()
 print(json.dumps({{'status':'STOPPED','codes':[code if re.fullmatch('[A-Z_]{{1,70}}',code) else 'READ_FAILED']}}));sys.exit(1)
'''
    return {'schemaVersion':'2.2','parameters':{},'description':'Fixed active catalog SQL categories and engine counters only',
            'mainSteps':[{'action':'aws:runShellScript','name':'report','inputs':{'timeoutSeconds':'50',
            'runCommand':["/usr/bin/python3.12 -I -S -B - <<'JJIKMUK_LIVE_SQL'\n"+script+'\nJJIKMUK_LIVE_SQL']}}]}


def read_saved(api,ctx):
    need(ctx['request_id']==REQUEST,'LIVE_DIAGNOSTIC_REQUEST')
    gate,_=Gate(api['s3']).read()
    need(gate is not None and gate['state']=='WORKING' and gate['run_id']==RUN and gate['commit']==COMMIT and
         gate['request_id']==REQUEST,'LIVE_DIAGNOSTIC_GATE')
    saved=read_object(api['s3'],'receipts/catalog/'+RUN+'/binding.json')
    need(saved['context']=={'commit':COMMIT,'run_id':RUN,'attempt':'1','request_id':REQUEST},'LIVE_DIAGNOSTIC_CONTEXT')
    return saved


def metadata(api,ctx):
    saved=read_saved(api,ctx)
    return {'status':'VERIFIED','checks':{'s3_metadata_only':True,'no_host_command':True},
            'hashes':{'receipt_sha256':sha(canonical(saved))},'request_id':REQUEST,'commit':ctx['commit']}


def inspect(api,ctx,expected_sha):
    saved=read_saved(api,ctx)
    plan={'format':1,'component':'db','operation':'inspect','approved':True,
          'approval_id':'USER_SOURCE_COMPATIBILITY_AND_DB_APPLY_20261111','document':document(saved,expected_sha)}
    result=execute(api,ctx,plan,sha(canonical(plan)),HOSTS['backend'])
    need(result['success'],'LIVE_DIAGNOSTIC_READ_FAILED')
    return dict(result,request_id=REQUEST,commit=ctx['commit'])
