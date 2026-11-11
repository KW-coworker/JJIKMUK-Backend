"""Fresh data-only application on the already installed original V21 schema."""
import hashlib,json,os,re,shutil,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
if __name__=='__main__':
    path=Path(__file__).absolute()
    assert re.fullmatch('/opt/jjikmuk-catalog-[a-f0-9]{16}/bin/catalog_reapply_host.py',str(path))
    assert os.geteuid()==0 and sys.flags.isolated and sys.flags.no_site
    for part in [path,*path.parents]:
        st=part.lstat();assert not part.is_symlink() and st.st_uid==0 and not st.st_mode&0o022
    sys.path[:0]=[str(path.parent),'/opt/jjikmuk-cd/bin']
from catalog_host import Work,phase_id
from catalog_reapply_contract import validate_binding,dataset,lease_binding,previous_coordinator,PHASE_SECONDS,HOST_START_BYTES,SCHEMA_SHA,RDS_RESERVE_BYTES
from catalog_reapply_previous import verify_service,original_state,previous_journal
from catalog_host_support import systemctl,start_and_enroll,UNITS
from catalog_checks import verify_recovered
from catalog_writer import Journal,Writer
from catalog_delta import Source
from initial_guard import Guard,host_s3
from initial_schema import read_from_connection
from initial_service_state import stopped
from manifest import require,digest,require_database
from coordination import locked,ROOT
import initial_db_facts as facts


class Reapply(Work):
    starting_bytes=HOST_START_BYTES
    history_count=22

    def __init__(self,stage,binding,phase):
        validate_binding(binding)
        require(phase in PHASE_SECONDS,'REAPPLY_PHASE')
        super().__init__(stage,binding)
        self.phase=phase;self.wall_started=time.time()
        self.dataset=dataset(binding['request_id'],binding['run_id'])
        self.journal_binding=dict(self.journal_binding,dataset=self.dataset)

    def budget(self):
        elapsed=time.monotonic()-self.started;wall=time.time()-self.wall_started
        require(0<=elapsed<PHASE_SECONDS[self.phase] and 0<=wall<PHASE_SECONDS[self.phase],'REAPPLY_HOST_DEADLINE')

    def resources(self):
        require(digest(self.stage/'source-products.sqlite')==self.binding['source_sha256'],'CATALOG_SOURCE_CHANGED')
        self.source=Source(self.stage/'source-products.sqlite')
        self.lease=Guard(host_s3(self.stage),lease_binding(self.binding,self.phase),read_attempts=2,budget_check=self.budget,
                         minimum_reserve=RDS_RESERVE_BYTES)

    def guard(self):
        self.budget()
        if self.require_lease:
            require(self.lease is not None,'CATALOG_LEASE_REQUIRED');self.lease()
        require(shutil.disk_usage(self.stage).free>2*1024**3,'CATALOG_HOST_DISK_RESERVE')
        if time.monotonic()-self.checked>=10:
            stopped(UNITS,systemctl)
            require(self.host.protected()==self.state['previous']['protected'],'CATALOG_PROTECTED_INPUT_CHANGED')
            self.checked=time.monotonic()

    def baseline_columns(self,names):return ['`'+name+'`' for name in names]

    def validate_candidate(self,candidate):
        before=self.host.baseline['manifest']
        require(before['migrations']==candidate['migrations'] and
                {r['version'] for r in candidate['migrations']}=={str(i) for i in range(1,22)} and
                next(r['sha256'] for r in candidate['migrations'] if r['version']=='21')==self.binding['sql_sha256'],
                'REAPPLY_MIGRATIONS_CHANGED')
        require(before['configuration']==candidate['configuration'],'REAPPLY_APPLICATION_CONFIGURATION_CHANGED')

    def prepare_schema(self):
        self.verify_schema()  # V21 is already installed; no Flyway or DDL is run.

    def verify_schema(self):
        with self.connect() as conn:
            observed=read_from_connection(conn)
            require(observed==self.state['schema'],'REAPPLY_SCHEMA_CHANGED')
            self.image_collations(conn)
            require_database(self.state['candidate'],observed['history'])
            require(facts.fulltext_definition(conn)==self.state['fulltext'] and
                    facts.search_fingerprint(conn)==self.state['search'],'CATALOG_SEARCH_PRESERVATION')
        return observed

    def image_collations(self,conn):
        with conn.cursor() as cur:
            cur.execute("SELECT COLUMN_NAME,CHARACTER_SET_NAME,COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='jjikmuk' AND TABLE_NAME='products' AND COLUMN_NAME IN ('image_role','image_display_notice','image_asset_sha256','image_assignment_run') ORDER BY COLUMN_NAME")
            observed=[list(row) for row in cur.fetchall()]
        require(observed==[['image_asset_sha256','ascii','ascii_general_ci'],['image_assignment_run','ascii','ascii_general_ci'],
                          ['image_display_notice','utf8mb4','utf8mb4_unicode_ci'],['image_role','utf8mb4','utf8mb4_unicode_ci']],
                'REAPPLY_IMAGE_COLLATION_CHANGED')

    def verify_previous_values(self):
        require(hashlib.sha256(json.dumps(self.state['schema'],sort_keys=True,separators=(',',':')).encode()).hexdigest()==SCHEMA_SHA,
                'REAPPLY_ORIGINAL_V21_SCHEMA_CHANGED')
        with self.connect() as conn:self.image_collations(conn)
        previous=original_state();codec=self.codec()
        try:
            with previous_journal(previous) as journal,self.connect(dictionary=True) as conn:
                result=verify_recovered(conn,self.source,journal,codec,'catalog-handoff-'+self.binding['request_id'],self.guard)
            require(result=={'products':1348425,'original_values_restored':True},'REAPPLY_CURRENT_VALUES_NOT_RESTORED')
        finally:codec.close()

    def recover(self,monitor_ready):
        if not self.state_path.exists():
            verify_service(self)
            return {'status':'VERIFIED','checks':{'preflight_failed_before_service_changes':True}}
        self.load();status=self.state['status']
        before_write={'FREEZE_INTENT','SERVICES_FROZEN','FROZEN_WITH_BASELINE','SNAPSHOT_VERIFIED','V21_VERIFIED'}
        after_write={'PRODUCT_APPLY_INTENT','PRODUCT_VALUES_VERIFIED','DB_VERIFIED','APP_SWITCH_INTENT','APP_VERIFIED_AND_ENROLLED'}
        require(status in before_write|after_write,'REAPPLY_RECOVERY_NO_REPLAY_OR_UNKNOWN_STATE')
        self.require_lease=False;self.record('RECOVERY_INTENT');systemctl('stop',*UNITS);self.guard()
        release=self.state['previous']
        self.host.database(release['manifest'])
        if status in after_write:
            require(monitor_ready is True,'CATALOG_RECOVERY_WRITES_REQUIRE_MONITOR')
            self.resources();self.require_lease=True;self.guard();self.verify_schema()
            journal=Journal(self.stage/'before-values.sqlite',self.journal_binding,recover=True);codec=self.codec()
            try:
                with self.connect(dictionary=True) as conn:
                    self.state['recovery_counts']=Writer(conn,self.source,codec,journal,self.dataset,self.guard).recover()
                with self.connect(dictionary=True) as conn:
                    self.state['recovery_verification']=verify_recovered(conn,self.source,journal,codec,self.dataset,self.guard)
            finally:codec.close();journal.close()
            self.verify_schema()
            require(self.preservation()==self.state['preservation'],'CATALOG_RECOVERY_PRESERVATION_FAILED')
        start_and_enroll(self.host,release,self.state['old_identity'],self.state['chatbot'],self.record)
        self.record('RECOVERED')
        return {'status':'VERIFIED','checks':{'old_product_values_restored':True,'existing_services_healthy':True,
                'original_history_retained':True},'hashes':{'backend_commit_sha256':hashlib.sha256(release['manifest']['commit'].encode()).hexdigest()}}


def main():
    entry=json.load(sys.stdin);require(set(entry)=={'binding','phase','snapshot'},'CATALOG_ENTRY_FIELDS')
    phase=entry['phase'];binding=entry['binding']
    require(binding.get('phase')==phase,'CATALOG_PHASE_BINDING')
    binding={k:v for k,v in binding.items() if k!='phase'};validate_binding(binding)
    require(phase in PHASE_SECONDS,'REAPPLY_PHASE')
    raw=(ROOT/'state.json').read_bytes();current=json.loads(raw);recovery_hash=None
    if phase=='freeze':previous_coordinator(current)
    elif phase=='apply':
        require(current=={'status':'VERIFIED','component':'db','operation_id':phase_id(binding,'freeze')},'REAPPLY_FREEZE_COORDINATOR')
    else:
        require(current.get('component')=='db' and current.get('operation_id') in {phase_id(binding,p) for p in ('freeze','apply')} and
                current.get('status') in ('MUTATION_INTENT','VERIFIED','REJECTED','MANUAL_RECOVERY_REQUIRED'),'REAPPLY_RECOVERY_COORDINATOR')
        if current['status'] in ('MUTATION_INTENT','MANUAL_RECOVERY_REQUIRED'):recovery_hash=hashlib.sha256(raw).hexdigest()
    with locked('db',phase_id(binding,phase),recovery_sha256=recovery_hash,expected_sha256=hashlib.sha256(raw).hexdigest()) as coordinator:
        work=Reapply(Path(__file__).absolute().parents[1],binding,phase)
        try:
            if phase=='freeze':verify_service(work)
            coordinator.record('MUTATION_INTENT')
            result=work.freeze() if phase=='freeze' else work.apply(entry['snapshot']) if phase=='apply' else work.recover(entry['snapshot']['monitor_ready'])
            coordinator.record('VERIFIED' if phase=='freeze' else 'ROLLED_BACK' if phase=='recover' else 'SUCCEEDED')
        finally:
            if work.source is not None:work.source.close()
    print(json.dumps(result))


if __name__=='__main__':
    try:main()
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) and re.fullmatch('[A-Z0-9_]{1,100}',str(error)) else type(error).__name__.upper()
        print(json.dumps({'status':'STOPPED','codes':[code]}));raise SystemExit(1)
