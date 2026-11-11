"""Admit only the inspected pre-DDL failure, preserving its original records."""
import hashlib,json,os,sqlite3
from pathlib import Path
from manifest import require,digest
from host import secure,read_host_state

FOLLOWUP={
 'request_id':'a5291163ee0a456b85366e6075d8fce6',
 'old_run':'42937366781',
 'old_archive':'6a4d669e3568768714e08c5a8c259c4849ecde541c2061194ed3f9799729d68e',
 'state_sha256':'968ec285024d2cf338920b236eb37e3d0060e3568de1f04e89cf7f30138ca513',
 'coordination_sha256':'b2f9d7f848cde81d3569eccc2c4d6ee08c82f50a96095e4aa891fc5585ea3137'}


def old_stage():return Path('/opt/jjikmuk-catalog-'+FOLLOWUP['old_archive'][:16])


def validate(binding):
    require(binding.get('followup')==FOLLOWUP and binding['request_id']==FOLLOWUP['request_id'] and
            binding['run_id']!=FOLLOWUP['old_run'],'CATALOG_FOLLOWUP_BINDING')


def link_source(destination,binding):
    validate(binding)
    source=old_stage()/'source-products.sqlite';secure(source)
    require(source.is_file() and source.stat().st_size==binding['source_bytes'] and
            digest(source)==binding['source_sha256'],'CATALOG_FOLLOWUP_SOURCE_CHANGED')
    os.link(source,destination,follow_symlinks=False)


def verify_previous(work):
    """Called under the new host lock, before stop/write, or for no-state recovery."""
    validate(work.binding)
    from catalog_host_support import chatbot_state,systemctl,UNITS
    from initial_schema import read_from_connection
    stage=old_stage();secure(stage)
    path=stage/'state.json';state=read_host_state(path)
    require(digest(path)==FOLLOWUP['state_sha256'] and state['status']=='APP_SWITCH_INTENT' and
            state['binding']['run_id']==FOLLOWUP['old_run'] and state['binding']['request_id']==FOLLOWUP['request_id'] and
            state['binding']['archive_sha256']==FOLLOWUP['old_archive'],'CATALOG_FOLLOWUP_OLD_STATE')
    require(work.host.baseline==state['previous'] and not (stage/'flyway-owned').exists(),'CATALOG_FOLLOWUP_OLD_RELEASE')
    journal=stage/'before-values.sqlite';secure(journal)
    with sqlite3.connect(journal.as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        require(db.execute('SELECT COUNT(*) FROM changes').fetchone()[0]==0,'CATALOG_FOLLOWUP_OLD_WRITES')
    with work.connect() as conn:
        require(read_from_connection(conn)==state['schema'],'CATALOG_FOLLOWUP_OLD_SCHEMA')
    require(chatbot_state()==state['chatbot'],'CATALOG_FOLLOWUP_OLD_CHATBOT')
    invocation=systemctl('show',UNITS[1],'--property=InvocationID','--value')
    work.host.verify(state['previous'],'')
    require(invocation==systemctl('show',UNITS[1],'--property=InvocationID','--value') and
            chatbot_state()==state['chatbot'] and digest(path)==FOLLOWUP['state_sha256'],
            'CATALOG_FOLLOWUP_CHANGED_DURING_CHECK')


def recovery_hash(binding,coordination):
    validate(binding)
    require(hashlib.sha256(coordination).hexdigest()==FOLLOWUP['coordination_sha256'],
            'CATALOG_FOLLOWUP_COORDINATOR_CHANGED')
    state=json.loads(coordination)
    require(state.get('status')=='MANUAL_RECOVERY_REQUIRED' and state.get('component')=='db' and
            state.get('operation_id')==hashlib.sha256((FOLLOWUP['request_id']+':recover').encode()).hexdigest(),
            'CATALOG_FOLLOWUP_COORDINATOR_IDENTITY')
    return FOLLOWUP['coordination_sha256']
