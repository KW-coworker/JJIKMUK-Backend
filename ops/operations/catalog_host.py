"""Fixed three-phase catalog maintenance on the existing backend host."""
import hashlib,json,os,re,shutil,sys,time
from datetime import datetime,timezone
from pathlib import Path
sys.dont_write_bytecode=True
if __name__=='__main__':
    path=Path(__file__).absolute()
    assert re.fullmatch('/opt/jjikmuk-catalog-[a-f0-9]{16}/bin/catalog_host.py',str(path))
    assert os.geteuid()==0 and sys.flags.isolated and sys.flags.no_site
    for part in [path,*path.parents]:
        st=part.lstat();assert not part.is_symlink() and st.st_uid==0 and not st.st_mode&0o022
    sys.path[:0]=[str(path.parent),'/opt/jjikmuk-cd/bin']
from manifest import require,digest,make_manifest,require_database
from host import Host,atomic_json,read_host_state,http_check
from deploy import load_config
from coordination import locked,ROOT as COORDINATION
from initial_guard import Guard,host_s3
from initial_schema import read_from_connection,extract_runtime
from initial_service_state import stopped
import initial_db_facts as facts
from catalog_host_support import UNITS,systemctl,chatbot_state,extract_classes,migrate,prepare_release,start_and_enroll
from catalog_delta import Source,VALUES
from catalog_writer import Writer,Journal,plain
from catalog_codec import Codec
from catalog_checks import manifests,schema,verify_values,verify_recovered
from catalog_preservation import capture


class Work:
    starting_bytes=6*1024**3
    history_count=21
    def __init__(self,stage,binding):
        self.stage,self.binding=stage,binding
        self.host=Host(load_config())
        self.lease=None;self.source=None;self.require_lease=True
        self.started=time.monotonic();self.checked=0
        self.state_path=stage/'state.json'
        self.dataset='catalog-handoff-'+binding['request_id']
        self.journal_binding={'dataset':self.dataset,'source_sha256':binding['source_sha256'],'commit':binding['commit']}

    def resources(self):
        require(digest(self.stage/'source-products.sqlite')==self.binding['source_sha256'],'CATALOG_SOURCE_CHANGED')
        self.source=Source(self.stage/'source-products.sqlite')
        self.lease=Guard(host_s3(self.stage),self.binding)

    def record(self,status):
        if isinstance(status,dict):
            self.state.setdefault('events',[]).append(status)
        else:self.state['status']=status
        atomic_json(self.state_path,self.state)

    def progress(self,*args):
        pass  # The new execution supplies non-sensitive, best-effort telemetry.

    def guard(self):
        if self.require_lease:
            require(self.lease is not None,'CATALOG_LEASE_REQUIRED');self.lease()
        require(time.monotonic()-self.started<2600,'CATALOG_PHASE_TIME_BUDGET')
        require(shutil.disk_usage(self.stage).free>2*1024**3,'CATALOG_HOST_DISK_RESERVE')
        if time.monotonic()-self.checked>=10:
            stopped(UNITS,systemctl)
            require(self.host.protected()==self.state['previous']['protected'],'CATALOG_PROTECTED_INPUT_CHANGED')
            self.checked=time.monotonic()

    def connect(self,*,dictionary=False):
        from database_probe import load_vendor,properties
        load_vendor();import pymysql
        db=self.host.config['database'];props=properties(db['properties_file'])
        require(props['spring.datasource.url']==db['expected_jdbc_url'] and db['name']=='jjikmuk' and
                db['host']=='jjikmuk-dev-db.cp22o82i4ex5.ap-northeast-2.rds.amazonaws.com','CATALOG_DB_TARGET')
        return pymysql.connect(host=db['host'],port=3306,database=db['name'],user=props['spring.datasource.username'],
            password=props['spring.datasource.password'],ssl_ca=db['ca_file'],ssl_verify_cert=True,ssl_verify_identity=True,
            connect_timeout=5,read_timeout=320,write_timeout=30,autocommit=False,local_infile=False,
            cursorclass=pymysql.cursors.DictCursor if dictionary else pymysql.cursors.Cursor)

    def preservation(self):
        self.progress('PRESERVATION',0,None)
        conn=self.connect()
        try:
            import pymysql
            return capture(conn,self.state['schema'],self.state['bounds'],self.guard,pymysql.cursors.SSCursor,self.progress)
        finally:
            # capture closes a failed streaming query without draining it. PyMySQL
            # __exit__ closes again and would hide the original error as Already closed.
            if conn.open:conn.close()

    def codec(self):
        return Codec(['/usr/bin/java','-Xms32m','-Xmx256m','-cp',str(self.stage/'classes')+':'+str(self.stage/'lib/*')+':'+str(self.stage/'bin/java'),'CatalogCodec'],guard=self.guard)

    def baseline(self):
        self.progress('BASELINE',0,self.source.meta['source_rows'])
        journal=Journal(self.stage/'before-values.sqlite',self.journal_binding)
        try:
            with self.connect(dictionary=True) as conn,conn.cursor() as cur:
                after=0;count=0
                names=['product_id','barcode',*VALUES,'product_group_key','attribute_snapshot_id']
                # V21 is not applied yet: these four are known absent and default to NULL.
                columns=self.baseline_columns(names)
                while True:
                    self.guard()
                    cur.execute('SELECT '+','.join(columns)+' FROM products WHERE product_id>%s ORDER BY product_id LIMIT 1000',(after,))
                    rows=[plain(r) for r in cur.fetchall()]
                    if not rows:break
                    for row in rows:
                        item=self.source.get(row['barcode'])
                        require(item['product_id']==row['product_id'],'CATALOG_FROZEN_PRODUCT_IDS')
                    journal.baseline(rows);count+=len(rows);after=rows[-1]['product_id']
                    self.progress('BASELINE',count,self.source.meta['source_rows'])
                    require(count<=self.source.meta['source_rows'],'CATALOG_BASELINE_ROW_LIMIT')
                require(count==self.source.meta['source_rows'],'CATALOG_BASELINE_ROW_COUNT')
        finally:journal.close()

    def baseline_columns(self,names):
        from catalog_delta import IMAGE_META
        return [('NULL AS `'+n+'`') if n in IMAGE_META else '`'+n+'`' for n in names]

    def validate_candidate(self,candidate):
        manifests(self.host.baseline['manifest'],candidate,self.binding['sql_sha256'])

    def prepare_schema(self):
        from database_probe import properties
        migrate(self.stage,properties(self.host.config['database']['properties_file']),self.guard,self.connect,self.record)

    def verify_previous_values(self):
        pass  # Initial V20 execution has no earlier product rollback to verify.

    def freeze(self):
        self.progress('SERVICE_CHECK')
        require(not self.state_path.exists(),'CATALOG_FREEZE_ALREADY_RECORDED')
        self.resources()
        require(self.host.baseline['manifest']['commit']==self.binding['previous_commit'],'CATALOG_PREVIOUS_RELEASE_CHANGED')
        self.host.runtime(self.host.baseline)
        for check in self.host.config['health_checks']:http_check(check)
        candidate=make_manifest(self.stage/'backend.jar',self.binding['commit'],self.binding['run_id'],'1')
        require(candidate['jar_sha256']==self.binding['jar_sha256'],'CATALOG_CANDIDATE_HASH')
        self.validate_candidate(candidate)
        require(shutil.disk_usage(self.stage).free>=self.starting_bytes,'CATALOG_HOST_START_RESERVE')
        # No chatbot CD enrollment is introduced by a product-data task.
        require(not Path('/opt/jjikmuk-chatbot/baseline.json').exists(),'CATALOG_CHATBOT_SCHEMA_ENROLLMENT_REQUIRED')
        self.state={'binding':self.binding,'previous':self.host.baseline,'candidate':candidate,
                    'old_identity':self.host.identity(),'chatbot':chatbot_state(),'events':[]}
        self.record('FREEZE_INTENT')
        self.progress('SERVICE_FREEZE')
        systemctl('stop',*UNITS);self.guard()
        self.state['frozen_epoch']=int(time.time())
        self.progress('METADATA')
        with self.connect() as conn:
            facts.project_idle(conn,guard=self.guard)
            self.state['schema']=read_from_connection(conn)
            require_database(self.state['previous']['manifest'],self.state['schema']['history'])
            self.state['logical']=facts.logical_extras(conn)
            self.state['fulltext']=facts.fulltext_definition(conn)
            self.state['search']=facts.search_fingerprint(conn)
            with conn.cursor() as cur:
                cur.execute('SELECT COALESCE(MAX(id),0) FROM product_attribute_snapshots');snap=cur.fetchone()[0]
                cur.execute('SELECT MAX(installed_rank),COUNT(*) FROM flyway_schema_history');rank,count=cur.fetchone()
                require(count==self.history_count and type(rank) is int,'CATALOG_OLD_HISTORY_BOUND')
                cur.execute("SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='jjikmuk' AND EVENT_OBJECT_TABLE IN ('products','product_attribute_snapshots')")
                require(cur.fetchone()[0]==0,'CATALOG_PRODUCT_TRIGGERS_REQUIRE_REVIEW')
            self.state['bounds']={'snapshot_id':snap,'history_rank':rank}
        self.record('SERVICES_FROZEN')
        extract_runtime(self.stage/'backend.jar',self.stage);extract_classes(self.stage/'backend.jar',self.stage)
        self.verify_previous_values()
        self.state['preservation']=self.preservation();self.baseline()
        self.progress('RELEASE_PREPARE')
        self.state['candidate_release']=prepare_release(self.host,self.stage,candidate)
        self.record('FROZEN_WITH_BASELINE')
        self.progress('FROZEN')
        return {'status':'VERIFIED','checks':{'services_stopped':True,'baseline_saved':True,'no_db_writes':True},
                'counts':{'frozen_epoch':self.state['frozen_epoch']}}

    def load(self):
        self.state=read_host_state(self.state_path)
        require(self.state['binding']==self.binding,'CATALOG_OPERATION_BINDING')

    def verify_schema(self):
        with self.connect() as conn:
            after=read_from_connection(conn)
            require_database(self.state['candidate'],after['history'])
            with conn.cursor() as cur:
                cur.execute("SELECT COLUMN_NAME,CHARACTER_SET_NAME,COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='jjikmuk' AND TABLE_NAME='products' AND COLUMN_NAME IN ('image_role','image_display_notice','image_asset_sha256','image_assignment_run') ORDER BY COLUMN_NAME")
                attrs=[list(r) for r in cur.fetchall()]
            schema(self.state['schema'],after,attrs)
            require(facts.fulltext_definition(conn)==self.state['fulltext'] and facts.search_fingerprint(conn)==self.state['search'],
                    'CATALOG_SEARCH_PRESERVATION')
        return after

    def apply(self,backup):
        self.load();require(self.state['status']=='FROZEN_WITH_BASELINE','CATALOG_APPLY_NO_REPLAY')
        self.resources()
        self.guard()
        require(re.fullmatch('jjikmuk-ops-initial-db-[1-9][0-9]{0,19}',backup['id']) and
                backup['arn']=='arn:aws:rds:ap-northeast-2:076767081522:snapshot:'+backup['id'] and
                self.state['frozen_epoch']<=datetime.fromisoformat(backup['created_at']).timestamp()<=datetime.now(timezone.utc).timestamp(),
                'CATALOG_FROZEN_BACKUP_REQUIRED')
        self.state['snapshot']=backup;self.record('SNAPSHOT_VERIFIED')
        require(self.preservation()==self.state['preservation'],'CATALOG_PREWRITE_PRESERVATION')
        with self.connect() as conn:
            facts.project_idle(conn,guard=self.guard)
            require(read_from_connection(conn)==self.state['schema'],'CATALOG_PREWRITE_SCHEMA_CHANGED')
        self.prepare_schema()
        self.verify_schema();self.record('V21_VERIFIED')
        journal=Journal(self.stage/'before-values.sqlite',self.journal_binding,recover=True);codec=self.codec()
        try:
            with self.connect(dictionary=True) as conn:
                self.record('PRODUCT_APPLY_INTENT')
                self.progress('PRODUCT_APPLY',0,self.source.meta['source_rows'])
                self.state['counts']=Writer(conn,self.source,codec,journal,self.dataset,self.guard,self.progress).run()
            with self.connect(dictionary=True) as conn:
                self.progress('PRODUCT_VERIFY',0,self.source.meta['source_rows'])
                self.state['value_verification']=verify_values(conn,self.source,journal,codec,self.dataset,self.guard,self.progress)
        finally:codec.close();journal.close()
        self.record('PRODUCT_VALUES_VERIFIED')
        self.verify_schema()
        require(self.preservation()==self.state['preservation'],'CATALOG_POSTWRITE_PRESERVATION')
        self.record('DB_VERIFIED')
        self.progress('SERVICE_VERIFY')
        start_and_enroll(self.host,self.state['candidate_release'],self.state['old_identity'],self.state['chatbot'],self.record)
        self.record('SUCCEEDED')
        return {'status':'SUCCEEDED','checks':{'source_values_applied':True,'original_data_preserved':True,
            'search_preserved':True,'backend_and_chatbot_healthy':True,'new_images_have_metadata':True},
            'counts':self.state['counts'],'hashes':{'backend_commit_sha256':hashlib.sha256(self.binding['commit'].encode()).hexdigest()}}

    def recover(self,monitor_ready):
        if not self.state_path.exists():
            if 'followup' in self.binding:
                from catalog_followup_host import verify_previous
                verify_previous(self)
            require(self.host.baseline['manifest']['commit']==self.binding['previous_commit'],'CATALOG_NO_STATE_RELEASE_CHANGED')
            self.host.verify(self.host.baseline,'')
            return {'status':'VERIFIED','checks':{'preflight_failed_before_service_changes':True}}
        self.load();original_status=self.state['status']
        require(original_status not in ('SUCCEEDED','RECOVERY_INTENT','RECOVERED'),'CATALOG_RECOVERY_NO_REPLAY')
        self.require_lease=False
        self.record('RECOVERY_INTENT');systemctl('stop',*UNITS);self.guard()
        before_ddl=original_status in {'FREEZE_INTENT','SERVICES_FROZEN','FROZEN_WITH_BASELINE','SNAPSHOT_VERIFIED'}
        if before_ddl:
            require(self.host.protected()==self.state['previous']['protected'],'CATALOG_RECOVERY_INPUT_CHANGED')
            release=self.state['previous']
            self.host.database(release['manifest'])
        else:
            from initial_flyway import owned_ids,settle
            import pwd
            ids=owned_ids(self.stage/'flyway-owned/connections',pwd.getpwnam('ubuntu').pw_uid)
            settle(self.connect,ids,lambda event:self.record(event),cancel=True)
            with self.connect() as conn:observed=read_from_connection(conn)
            if observed==self.state['schema']:
                release=self.state['previous'];self.host.database(release['manifest'])
            else:
                # Unknown/partial DDL or a failed Flyway entry remains stopped. No repair or replay.
                self.verify_schema();release=self.state['candidate_release']
                require(monitor_ready is True,'CATALOG_RECOVERY_WRITES_REQUIRE_MONITOR')
                self.resources();self.require_lease=True;self.guard()
                journal=Journal(self.stage/'before-values.sqlite',self.journal_binding,recover=True);codec=self.codec()
                try:
                    with self.connect(dictionary=True) as conn:
                        self.state['recovery_counts']=Writer(conn,self.source,codec,journal,self.dataset,self.guard).recover()
                    with self.connect(dictionary=True) as conn:
                        self.state['recovery_verification']=verify_recovered(conn,self.source,journal,codec,self.dataset,self.guard)
                finally:codec.close();journal.close()
                require(self.preservation()==self.state['preservation'],'CATALOG_RECOVERY_PRESERVATION_FAILED')
        start_and_enroll(self.host,release,self.state['old_identity'],self.state['chatbot'],self.record)
        self.record('RECOVERED')
        return {'status':'VERIFIED','checks':{'old_product_values_restored':True,'existing_services_healthy':True,
                'original_history_retained':True},'hashes':{'backend_commit_sha256':hashlib.sha256(release['manifest']['commit'].encode()).hexdigest()}}


def main():
    entry=json.load(sys.stdin);require(set(entry)=={'binding','phase','snapshot'},'CATALOG_ENTRY_FIELDS')
    stage=Path(__file__).absolute().parents[1];binding=entry['binding']
    require(binding['phase'] == entry['phase'],'CATALOG_PHASE_BINDING')
    binding={k:v for k,v in binding.items() if k!='phase'}
    phase=entry['phase'];require(phase in ('freeze','apply','recover'),'CATALOG_PHASE')
    operation=phase_id(binding,phase)
    recovery_hash=None
    if phase=='freeze' and 'followup' in binding:
        from catalog_followup_host import recovery_hash as previous_recovery_hash
        recovery_hash=previous_recovery_hash(binding,(COORDINATION/'state.json').read_bytes())
    if phase=='recover':
        raw=(COORDINATION/'state.json').read_bytes();state=json.loads(raw)
        allowed={phase_id(binding,name) for name in ('freeze','apply')}
        require(state.get('component')=='db' and state.get('operation_id') in allowed and
                state.get('status') in ('MUTATION_INTENT','VERIFIED','REJECTED','MANUAL_RECOVERY_REQUIRED'),'CATALOG_RECOVERY_COORDINATOR_CHANGED')
        if state['status'] in ('MUTATION_INTENT','MANUAL_RECOVERY_REQUIRED'):recovery_hash=hashlib.sha256(raw).hexdigest()
    with locked('db',operation,recovery_sha256=recovery_hash) as coordinator:
        work=Work(stage,binding)
        try:
            if phase=='freeze' and 'followup' in binding:
                from catalog_followup_host import verify_previous
                verify_previous(work)
            coordinator.record('MUTATION_INTENT')
            result=work.freeze() if phase=='freeze' else work.apply(entry['snapshot']) if phase=='apply' else work.recover(entry['snapshot']['monitor_ready'])
            coordinator.record('VERIFIED' if phase=='freeze' else 'ROLLED_BACK' if phase=='recover' else 'SUCCEEDED')
        finally:
            if work.source is not None:work.source.close()
    print(json.dumps(result))


def phase_id(binding,phase):
    return hashlib.sha256((binding['request_id']+':'+binding['run_id']+':'+phase).encode()).hexdigest()


if __name__=='__main__':
    try:main()
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) and re.fullmatch('[A-Z0-9_]{1,100}',str(error)) else type(error).__name__.upper()
        print(json.dumps({'status':'STOPPED','codes':[code]}));raise SystemExit(1)
