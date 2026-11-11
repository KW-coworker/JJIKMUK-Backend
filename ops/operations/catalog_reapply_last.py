"""Read the pinned completed rollback, including its immutable before-image."""
from contextlib import contextmanager
import hashlib,json,sqlite3,subprocess
from pathlib import Path
from host import secure,read_host_state
from manifest import require,digest
from catalog_reapply_contract import REQUEST,LAST_RUN,LAST_COMMIT,LAST_ARCHIVE,LAST_BINDING,SOURCE_SHA
from catalog_writer import Journal


def stage():return Path('/opt/jjikmuk-catalog-'+LAST_ARCHIVE[:16])


@contextmanager
def recovered_journal():
    folder=stage();secure(folder)
    for phase in ('freeze','apply','recover'):
        result=subprocess.run(['/usr/bin/systemctl','is-active','jjikmuk-catalog-'+phase+'-'+LAST_ARCHIVE[:16]],
                              capture_output=True,timeout=5)
        require(result.stdout.strip() in (b'inactive',b'failed',b'unknown'),'REAPPLY_LAST_UNIT_ACTIVE')
    path=folder/'state.json';state=read_host_state(path);state_hash=digest(path)
    actual=hashlib.sha256(json.dumps(state['binding'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    require(actual==LAST_BINDING and state['status']=='RECOVERED',
            'REAPPLY_LAST_RECOVERY_STATE_CHANGED')
    journal=folder/'before-values.sqlite';secure(journal);before=digest(journal)
    require(not any(Path(str(journal)+suffix).exists() for suffix in ('-journal','-wal','-shm')),'REAPPLY_LAST_JOURNAL_ACTIVE')
    with journal.open('rb') as stream:header=stream.read(100)
    require(header[:16]==b'SQLite format 3\x00' and header[18:20]==b'\x01\x01','REAPPLY_LAST_JOURNAL_FORMAT')
    expected={'dataset':'catalog-handoff-'+hashlib.sha256((REQUEST+':'+LAST_RUN).encode()).hexdigest()[:32],
              'source_sha256':SOURCE_SHA,'commit':LAST_COMMIT}
    saved=Journal.__new__(Journal);saved.path=journal
    saved.db=sqlite3.connect(journal.as_uri()+'?mode=ro',uri=True)
    try:
        db=saved.db
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA busy_timeout=1000')
        require(json.loads(db.execute("SELECT value FROM metadata WHERE key='binding'").fetchone()[0])==expected,
                'REAPPLY_LAST_JOURNAL_BINDING')
        count=db.execute('SELECT COUNT(*) FROM changes').fetchone()[0]
        recovery=state.get('recovery_counts',{})
        require(set(recovery)=={'restored','never_committed'} and
                all(type(n) is int and n>=0 for n in recovery.values()) and
                0<recovery['restored']<=count<=1348425 and sum(recovery.values())==count,
                'REAPPLY_LAST_RECOVERY_COUNTS')
        require(state.get('recovery_verification')=={'products':1348425,'original_values_restored':True},
                'REAPPLY_LAST_RECOVERY_UNVERIFIED')
        require(db.execute("SELECT COUNT(*) FROM changes WHERE status IS NULL OR status<>?",('RESTORED_OR_NOT_COMMITTED',)).fetchone()[0]==0,
                'REAPPLY_LAST_JOURNAL_NOT_RESTORED')
        require(db.execute('SELECT COUNT(*) FROM baseline').fetchone()[0]==1348425,'REAPPLY_LAST_BASELINE_INCOMPLETE')
        yield state,saved,expected['dataset']
    finally:
        saved.close()
        require(digest(path)==state_hash and digest(journal)==before,'REAPPLY_LAST_RECORD_CHANGED')


def verify(work):
    from coordination import ROOT
    from catalog_reapply_contract import previous_apply_record
    expected,checksum=previous_apply_record()
    history=ROOT/'history'/expected['operation_id']/'01.json'
    for path in (ROOT,ROOT/'history',history.parent,history):secure(path)
    require(history.stat().st_size<4096,'REAPPLY_LAST_APPLY_RECORD_SIZE')
    raw=history.read_bytes()
    require(len(raw)<4096 and hashlib.sha256(raw).hexdigest()==checksum and json.loads(raw)==expected,
            'REAPPLY_LAST_APPLY_RECORD_CHANGED')
    with recovered_journal() as (state,_,unused):
        require(state['previous']==work.host.baseline,'REAPPLY_LAST_RECOVERY_STATE_CHANGED')
