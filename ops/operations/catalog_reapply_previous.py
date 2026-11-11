"""Read-only admission of the exact restored catalog; old records stay immutable."""
from contextlib import contextmanager
import json,os,sqlite3,subprocess
from pathlib import Path
from catalog_reapply_contract import OLD_ARCHIVE,OLD_STATE,OLD_JOURNAL,PREVIOUS,OLD_RUN,SERVICE_RUN,validate_binding
from catalog_writer import Journal
from host import secure,read_host_state
from manifest import require,digest


def old_stage():return Path('/opt/jjikmuk-catalog-'+OLD_ARCHIVE[:16])


def link_source(destination,binding):
    validate_binding(binding)
    source=old_stage()/'source-products.sqlite';secure(source)
    require(source.stat().st_size==binding['source_bytes'] and digest(source)==binding['source_sha256'],'REAPPLY_SOURCE_CHANGED')
    os.link(source,destination,follow_symlinks=False)


def original_state():
    stage=old_stage();secure(stage)
    path=stage/'state.json';state=read_host_state(path)
    journal=stage/'before-values.sqlite';secure(journal)
    require(digest(path)==OLD_STATE and digest(journal)==OLD_JOURNAL,'REAPPLY_ORIGINAL_RECORD_CHANGED')
    require(not any(Path(str(journal)+suffix).exists() for suffix in ('-journal','-wal','-shm')),'REAPPLY_ORIGINAL_JOURNAL_ACTIVE')
    require(state['status']=='APP_SWITCH_INTENT' and state['binding']['run_id']==OLD_RUN and
            state['binding']['archive_sha256']==OLD_ARCHIVE and state['candidate']['commit']==PREVIOUS and
            state['recovery_counts']=={'restored':618578,'never_committed':500} and
            state['recovery_verification']=={'products':1348425,'original_values_restored':True},'REAPPLY_RECOVERY_PROOF')
    service=read_host_state(stage/('service-recovery-'+SERVICE_RUN+'.json'))
    require(service['status']=='SERVICES_RESTORED' and service['binding']==state['binding'] and
            service['state_sha256']==OLD_STATE and service['journal_sha256']==OLD_JOURNAL,'REAPPLY_SERVICE_RECORD')
    return state


def verify_service(work):
    from catalog_host_support import chatbot_state
    from catalog_reapply_last import verify
    state=original_state()
    for phase in ('freeze','apply','recover'):
        observed=subprocess.run(['/usr/bin/systemctl','is-active','jjikmuk-catalog-'+phase+'-'+OLD_ARCHIVE[:16]],
                                capture_output=True,timeout=5)
        require(observed.stdout.strip() in (b'inactive',b'failed',b'unknown'),'REAPPLY_PREVIOUS_UNIT_ACTIVE')
    require(work.host.baseline==state['candidate_release'],'REAPPLY_PREVIOUS_BASELINE_CHANGED')
    work.host.verify(work.host.baseline,'')
    require(chatbot_state()==state['chatbot'],'REAPPLY_PREVIOUS_CHATBOT_CHANGED')
    verify(work)


@contextmanager
def previous_journal(state):
    path=old_stage()/'before-values.sqlite'
    journal=Journal.__new__(Journal);journal.path=path
    journal.db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        journal.db.execute('PRAGMA query_only=ON')
        expected={'dataset':'catalog-handoff-'+state['binding']['request_id'],
                  'source_sha256':state['binding']['source_sha256'],'commit':state['binding']['commit']}
        observed=json.loads(journal.db.execute("SELECT value FROM metadata WHERE key='binding'").fetchone()[0])
        require(observed==expected,'REAPPLY_ORIGINAL_JOURNAL_BINDING')
        yield journal
    finally:journal.close()
    require(digest(path)==OLD_JOURNAL,'REAPPLY_ORIGINAL_JOURNAL_CHANGED')
