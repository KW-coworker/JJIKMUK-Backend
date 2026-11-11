"""Admit only the exact recovered, zero-product-write attempt. Preserve its records."""
from contextlib import closing
import hashlib,json,sqlite3,subprocess
from pathlib import Path
from host import secure,read_host_state
from manifest import require,digest
from catalog_reapply_contract import REQUEST,LAST_RUN,LAST_COMMIT,LAST_ARCHIVE,LAST_BINDING,SOURCE_SHA


def stage():return Path('/opt/jjikmuk-catalog-'+LAST_ARCHIVE[:16])


def verify(work):
    folder=stage();secure(folder)
    for phase in ('freeze','apply','recover'):
        result=subprocess.run(['/usr/bin/systemctl','is-active','jjikmuk-catalog-'+phase+'-'+LAST_ARCHIVE[:16]],
                              capture_output=True,timeout=5)
        require(result.stdout.strip() in (b'inactive',b'failed',b'unknown'),'REAPPLY_LAST_UNIT_ACTIVE')
    path=folder/'state.json';state=read_host_state(path);state_hash=digest(path)
    actual=hashlib.sha256(json.dumps(state['binding'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    require(actual==LAST_BINDING and state['status']=='RECOVERED' and state['previous']==work.host.baseline,
            'REAPPLY_LAST_RECOVERY_STATE_CHANGED')
    journal=folder/'before-values.sqlite';secure(journal);before=digest(journal)
    require(not any(Path(str(journal)+suffix).exists() for suffix in ('-journal','-wal','-shm')),'REAPPLY_LAST_JOURNAL_ACTIVE')
    with journal.open('rb') as stream:header=stream.read(100)
    require(header[:16]==b'SQLite format 3\x00' and header[18:20]==b'\x01\x01','REAPPLY_LAST_JOURNAL_FORMAT')
    expected={'dataset':'catalog-handoff-'+hashlib.sha256((REQUEST+':'+LAST_RUN).encode()).hexdigest()[:32],
              'source_sha256':SOURCE_SHA,'commit':LAST_COMMIT}
    with closing(sqlite3.connect(journal.as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA busy_timeout=1000')
        require(json.loads(db.execute("SELECT value FROM metadata WHERE key='binding'").fetchone()[0])==expected,
                'REAPPLY_LAST_JOURNAL_BINDING')
        require(db.execute('SELECT COUNT(*) FROM changes').fetchone()[0]==0,'REAPPLY_LAST_PRODUCT_WRITES_REQUIRE_REVIEW')
        require(db.execute('SELECT COUNT(*) FROM baseline').fetchone()[0]==1348425,'REAPPLY_LAST_BASELINE_INCOMPLETE')
    require(digest(path)==state_hash and digest(journal)==before,'REAPPLY_LAST_RECORD_CHANGED')
