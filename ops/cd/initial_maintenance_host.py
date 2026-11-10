"""Approved initial maintenance phases; immutable app inputs and private journals."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

if __name__ == '__main__':
    source = Path(__file__).resolve()
    assert re.fullmatch('/opt/jjikmuk-initial-[a-f0-9]{16}/bin/initial_maintenance_host.py', str(source))
    for path in [source, *source.parents]:
        st = path.lstat()
        assert not path.is_symlink() and st.st_uid == 0 and not st.st_mode & 0o022
    assert os.geteuid() == 0 and sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
    sys.path.insert(0, str(source.parent))

from manifest import require, digest, make_manifest
from host import Host, atomic_json, http_check, secure
from initial_contract import config, OLD_ARGV, OLD_SHA, OLD_JAR, DB_HOST, PROPS
from initial_db_host import JOURNAL_ROOT, OBSERVED_PROTECTED, OBSERVED_ENVIRONMENT, OBSERVED_PROPERTIES
from initial_guard import Guard, host_s3
from initial_ddl import guarded_sql
import initial_schema as schema
import initial_preservation as preservation
import initial_db_facts as facts
import readiness_probe as probe

UNITS = ('jjikmuk-backend.service', 'food-chatbot-team.service')
REQUIRED_BYTES = 5 * 1024**3


def systemctl(*args):
    result = subprocess.run(['/usr/bin/systemctl', *args], capture_output=True, timeout=90,
                            cwd='/', env={'PATH':'/usr/bin:/bin','LANG':'C'})
    require(result.returncode == 0, 'MAINTENANCE_SERVICE_COMMAND_FAILED')
    return result.stdout.decode().strip()


def old_host():
    host = Host.__new__(Host)
    host.config = config(); host.root = Path(host.config['root'])
    host.config['protected_paths'] = [p for p in host.config['protected_paths']
                                    if not p.startswith(('/opt/jjikmuk-cd', '/etc/jjikmuk-cd'))]
    return host


def stopped():
    for unit in UNITS:
        require(systemctl('show', unit, '--property=ActiveState', '--value') == 'inactive'
                and systemctl('show', unit, '--property=MainPID', '--value') == '0'
                and systemctl('show', unit, '--property=SubState', '--value') == 'dead', 'SERVICES_NOT_STOPPED')
        group=systemctl('show',unit,'--property=ControlGroup','--value')
        if group:
            require(group.startswith('/system.slice/') and '..' not in group,'SERVICE_CGROUP_PATH')
            directory=Path('/sys/fs/cgroup'+group)
            if directory.exists():
                require(all(not p.read_text().strip() for p in directory.rglob('cgroup.procs')),
                        'SERVICE_CGROUP_NOT_EMPTY')


def chatbot_runtime():
    pid=systemctl('show',UNITS[1],'--property=MainPID','--value')
    require(re.fullmatch('[1-9][0-9]*',pid),'CHATBOT_PID_REQUIRED')
    folder=Path('/proc')/pid
    env=dict(part.split(b'=',1) for part in (folder/'environ').read_bytes().split(b'\0') if b'=' in part)
    for key in (b'INVOCATION_ID',b'JOURNAL_STREAM',b'SYSTEMD_EXEC_PID',b'NOTIFY_SOCKET',b'WATCHDOG_PID',b'WATCHDOG_USEC'):
        env.pop(key,None)
    digestor=hashlib.sha256((folder/'cmdline').read_bytes())
    for key,value in sorted(env.items()):digestor.update(b'\0'+key+b'='+value)
    return {'sha256':digestor.hexdigest(),'uid':folder.stat().st_uid,'cwd':os.readlink(folder/'cwd')}


def chatbot_files():
    unit = UNITS[1]
    paths = [systemctl('show',unit,'--property=FragmentPath','--value')]
    paths += systemctl('show',unit,'--property=DropInPaths','--value').split()
    envs = systemctl('show',unit,'--property=EnvironmentFiles','--value')
    pattern = r'(/[^\s]+) \(ignore_errors=(?:yes|no)\)'
    require(not re.sub(pattern,'',envs).strip(), 'CHATBOT_ENVIRONMENT_PATH_SYNTAX')
    paths += re.findall(pattern,envs)
    result = {}
    for name in paths:
        secure(name)
        p=Path(name);st=p.stat()
        require(p.is_file() and st.st_size < 1024**2, 'CHATBOT_INPUT_SIZE')
        result[name]=[st.st_uid,st.st_gid,st.st_mode,digest(p)]
    return result


def connect(stage,*,read_timeout=5):
    from package_install import WHEEL_NAME, WHEEL_SHA
    from database_probe import properties
    path=stage/'vendor'/WHEEL_NAME;secure(path)
    require(digest(path)==WHEEL_SHA,'INITIAL_DB_VENDOR_CHANGED')
    if str(path) not in sys.path:sys.path.insert(0,str(path))
    import pymysql
    secure(PROPS)
    require(digest(Path(PROPS))==OBSERVED_PROPERTIES,'DATABASE_PROPERTIES_CHANGED')
    p=properties(PROPS)
    return pymysql.connect(host=DB_HOST, port=3306, database='jjikmuk',
        user=p['spring.datasource.username'], password=p['spring.datasource.password'],
        ssl_ca='/opt/food-chatbot/rds-global-bundle.pem', ssl_verify_cert=True, ssl_verify_identity=True,
        connect_timeout=5, read_timeout=read_timeout, write_timeout=5, autocommit=True, local_infile=False)


def private_state():
    path=JOURNAL_ROOT/'state.json';secure(path)
    require(path.stat().st_size < 1024**2,'MAINTENANCE_STATE_SIZE')
    return json.loads(path.read_bytes())


def set_state(state,status):
    state['status']=status
    atomic_json(JOURNAL_ROOT/'state.json',state)


def require_inputs(state):
    trusted_certificates()
    require(probe.jar_digest()==OLD_SHA and old_host().protected()==state['protected']
            and chatbot_files()==state['chatbot_files']
            and digest(Path('/opt/food-chatbot/rds-institution-trust.p12'))==state['truststore_sha256'],
            'FROZEN_APPLICATION_INPUT_CHANGED')


def trusted_certificates():
    probe.trusted_ca()
    path=Path('/opt/food-chatbot/rds-institution-trust.p12')
    secure(path)
    require(path.is_file() and 0<path.stat().st_size<1024**2,'JAVA_TRUSTSTORE_SIZE')


def restore_services(state):
    require_inputs(state)
    state['restore_origin']=state['status']
    set_state(state,'RESTORE_INTENT')
    try:
        for unit in reversed(UNITS):systemctl('start',unit)
        host=old_host()
        for _ in range(45):
            try:
                inputs=probe.database_inputs()
                require(probe.jar_digest()==OLD_SHA and host.environment(int(inputs[0][0]),OLD_ARGV)==state['environment_sha256'],
                        'RESTORED_BACKEND_RUNTIME_CHANGED')
                for check in host.config['health_checks']:http_check(check)
                require(chatbot_runtime()==state['chatbot_runtime'],'RESTORED_CHATBOT_RUNTIME_CHANGED')
                probe.unchanged(inputs);require_inputs(state)
                return
            except Exception:
                time.sleep(2)
        raise ValueError('OLD_SERVICE_RESTORE_HEALTH_FAILED')
    except BaseException:
        for unit in UNITS:
            try:systemctl('stop',unit)
            except Exception:pass
        try:stopped()
        except Exception:set_state(state,'RESTORE_FAILED_STOP_UNCONFIRMED')
        else:set_state(state,'RESTORE_FAILED_SERVICES_STOPPED')
        raise


def capture_data(stage, state, guard):
    conn=connect(stage,read_timeout=190)
    identity=conn.thread_id()
    import pymysql
    try:
        return preservation.capture(conn,state['projection'],state['history_rank'],guard,
                                    cursor_class=pymysql.cursors.SSCursor)
    finally:
        if conn.open:conn.close()
        from initial_flyway import settle
        settle(lambda:connect(stage),[identity],lambda event:record(state,event),cancel=True)


def record(state,event):
    state.setdefault('operations',[]).append(event)
    require(len(state['operations'])<=200,'MAINTENANCE_OPERATION_LIMIT')
    atomic_json(JOURNAL_ROOT/'state.json',state)


def phase_guard(stage,binding,seconds):
    lease=Guard(host_s3(stage),binding)
    deadline=time.monotonic()+seconds
    def check():
        require(time.monotonic()<deadline,'MAINTENANCE_PHASE_DEADLINE')
        lease()
    check()
    return check


def freeze(stage,binding):
    require(not JOURNAL_ROOT.exists() and not JOURNAL_ROOT.is_symlink(),'INITIAL_DB_JOURNAL_EXISTS_NO_RETRY')
    require(not Path('/opt/jjikmuk-cd').exists() and not Path('/etc/jjikmuk-cd').exists()
            and not Path('/var/lib/jjikmuk-operations').exists(),'INITIAL_INSTALL_ALREADY_PRESENT')
    require(binding['required_bytes']==REQUIRED_BYTES,'MAINTENANCE_FIXED_RESERVE')
    guard=phase_guard(stage,binding,600)
    manifest=make_manifest(stage/'backend.jar',binding['commit'],'1','1')
    require(manifest['jar_sha256']==binding['jar_sha256'],'INITIAL_JAR_CHANGED')
    schema.validate_source(manifest)
    host=old_host();protected=host.protected();host.require_protected_references(protected)
    inputs=probe.database_inputs()
    environment=host.environment(int(inputs[0][0]),OLD_ARGV)
    require(probe.jar_digest()==OLD_SHA and hashlib.sha256(facts.canonical(protected)).hexdigest()==OBSERVED_PROTECTED
            and environment==OBSERVED_ENVIRONMENT and hashlib.sha256(inputs[2]).hexdigest()==OBSERVED_PROPERTIES,
            'OBSERVED_INPUTS_CHANGED')
    before=schema.metadata(stage);schema.verify_schema(manifest,before,False,fulltext_maintenance=True)
    trusted_certificates()
    with connect(stage) as conn:
        facts.require_observation_privileges(conn)
        definition=facts.fulltext_definition(conn)
        with conn.cursor() as cur:
            cur.execute('SELECT DATA_LENGTH+INDEX_LENGTH FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s',('jjikmuk','products'))
            table_bytes=int(cur.fetchone()[0])
        require(3*table_bytes+1024**3 <= REQUIRED_BYTES,'TABLE_GREW_BEYOND_REVIEWED_RESERVE')
    for check in host.config['health_checks']:http_check(check)
    chat_files=chatbot_files()
    require(systemctl('show',UNITS[1],'--property=ActiveState','--value')=='active','CHATBOT_NOT_ACTIVE')
    probe.unchanged(inputs);guard()
    schema.extract_runtime(stage/'backend.jar',stage)
    JOURNAL_ROOT.mkdir(mode=0o700);os.chmod(JOURNAL_ROOT,0o700)
    state={'status':'STOP_INTENT','binding':binding,'stage':str(stage),'candidate':manifest,
           'protected':protected,'chatbot_files':chat_files,'chatbot_runtime':chatbot_runtime(),
           'environment_sha256':environment,
           'truststore_sha256':digest(Path('/opt/food-chatbot/rds-institution-trust.p12')),
           'fulltext_definition':definition,'before_schema':before,'projection':preservation.projection(before)}
    atomic_json(JOURNAL_ROOT/'state.json',state)
    try:
        for unit in UNITS:systemctl('stop',unit)
        stopped();guard();require_inputs(state)
        with connect(stage) as conn:
            facts.quiescent(conn)
            frozen_schema=schema.read_from_connection(conn)
            schema.verify_schema(manifest,frozen_schema,False,fulltext_maintenance=True)
            require(frozen_schema==before,'SCHEMA_CHANGED_DURING_FREEZE')
            state['before_schema']=frozen_schema
            state['projection']=preservation.projection(frozen_schema)
            state['history_rank']=facts.history_bound(conn)
            state['logical']=facts.logical_extras(conn)
            state['search']=facts.search_fingerprint(conn)
        state['data']=capture_data(stage,state,guard)
        with connect(stage) as conn:facts.quiescent(conn)
        stopped();require_inputs(state);guard()
        state['frozen_epoch']=int(time.time())
        set_state(state,'FROZEN_NO_DB_WRITES')
        return {'status':'SUCCEEDED','checks':{'writers_quiescent':True,'original_data_recorded':True,
                'app_files_unchanged':True},'counts':{'frozen_epoch':state['frozen_epoch'],
                'tables':len(state['data']),'history_rank':state['history_rank']}}
    except BaseException:
        # This phase issues no database writes. Restore the unchanged applications only.
        set_state(state,'FREEZE_FAILED_NO_DB_WRITES')
        restore_services(state)
        set_state(state,'FREEZE_FAILED_OLD_SERVICES_RESTORED')
        raise


def verify_binding(stage,binding,state):
    require(state['stage']==str(stage) and state['binding']==binding,'MAINTENANCE_PHASE_BINDING_CHANGED')
    require(digest(stage/'backend.jar')==binding['jar_sha256'],'INITIAL_JAR_CHANGED')
    require_inputs(state)


def verify_preserved(stage,state,guard):
    stopped();guard()
    after=schema.metadata(stage)
    schema.verify_schema(state['candidate'],after,True)
    schema.verify_preservation(state['before_schema'],after)
    with connect(stage) as conn:
        facts.quiescent(conn)
        facts.verify_logical(state['logical'],facts.logical_extras(conn))
        require(facts.fulltext_definition(conn)==state['fulltext_definition'],'FULLTEXT_DEFINITION_CHANGED')
        require(facts.search_fingerprint(conn)==state['search'],'GENERAL_SEARCH_CHANGED')
    preservation.verify(state['data'],capture_data(stage,state,guard))
    with connect(stage) as conn:facts.quiescent(conn)
    stopped();guard();require_inputs(state)
    atomic_json(JOURNAL_ROOT/'after-schema.json',after)


def apply(stage,binding,backup):
    from datetime import datetime,timezone
    from database_probe import properties
    from initial_flyway import apply as flyway_apply
    state=private_state();verify_binding(stage,binding,state)
    require(state['status']=='FROZEN_NO_DB_WRITES','MAINTENANCE_APPLY_STATE_NO_REPLAY')
    created=datetime.fromisoformat(backup['created_at']).timestamp()
    require(re.fullmatch('jjikmuk-ops-initial-db-[1-9][0-9]{0,19}',backup['id'])
            and backup['arn']=='arn:aws:rds:ap-northeast-2:076767081522:snapshot:'+backup['id']
            and state['frozen_epoch']<=created<=datetime.now(timezone.utc).timestamp(),
            'FROZEN_SNAPSHOT_REQUIRED')
    guard=phase_guard(stage,binding,1200);stopped()
    state['snapshot']=backup
    with connect(stage) as conn:facts.quiescent(conn)
    # Snapshot was taken after the captured baseline; reject any intervening write.
    preservation.verify(state['data'],capture_data(stage,state,guard))
    with connect(stage) as conn:
        facts.quiescent(conn)
        require(schema.read_from_connection(conn)==state['before_schema'],'SCHEMA_CHANGED_DURING_SNAPSHOT')
        require(facts.logical_extras(conn)==state['logical'],'LOGICAL_OPTIONS_CHANGED_DURING_SNAPSHOT')
        require(facts.fulltext_definition(conn)==state['fulltext_definition'],'FULLTEXT_CHANGED_DURING_SNAPSHOT')
    set_state(state,'MAINTENANCE_APPLY_INTENT')
    def execute(sql):
        stopped();guard();require_inputs(state)
        with connect(stage,read_timeout=610) as conn:
            facts.quiescent(conn)
            guarded_sql(conn,lambda:connect(stage),sql,guard,lambda event:record(state,event),timeout=600)
    try:
        execute('ALTER TABLE products DROP INDEX ft_products_search_keywords, ALGORITHM=INPLACE')
        set_state(state,'FULLTEXT_DROPPED')
        execute('OPTIMIZE TABLE products')
        set_state(state,'PRODUCTS_REBUILT')
        with connect(stage) as conn:facts.quiescent(conn)
        require_inputs(state)
        flyway_apply(stage,properties(PROPS),guard,lambda:connect(stage),lambda event:record(state,event))
        set_state(state,'ORIGINAL_V17_V20_APPLIED')
        execute('ALTER TABLE products ADD FULLTEXT KEY ft_products_search_keywords (search_keywords) WITH PARSER ngram')
        set_state(state,'FULLTEXT_RESTORED')
        verify_preserved(stage,state,guard)
        set_state(state,'DB_VERIFIED_SERVICES_STOPPED')
        restore_services(state)
        set_state(state,'DB_PREPARED')
        return {'status':'SUCCEEDED','checks':{'v17_v20_applied':True,'original_data_preserved':True,
            'fulltext_search_preserved':True,'old_application_restored':True,'free_health_checks_passed':True},
            'counts':{'migrations_applied':4,'paid_ai_calls':0},
            'hashes':{'candidate_jar':binding['jar_sha256'],'after_schema':digest(JOURNAL_ROOT/'after-schema.json')}}
    except BaseException:
        # DDL auto-commits. Preserve the last known phase; never claim an SQL rollback.
        state['failure_observed']=True
        atomic_json(JOURNAL_ROOT/'state.json',state)
        raise


def recover(stage,binding):
    state=private_state();verify_binding(stage,binding,state)
    origin=state['status']
    require(state['status'] in ('FROZEN_NO_DB_WRITES','FREEZE_FAILED_NO_DB_WRITES',
            'DB_VERIFIED_SERVICES_STOPPED','FREEZE_FAILED_OLD_SERVICES_RESTORED','DB_PREPARED'),
            'DDL_STATE_REQUIRES_REVIEW_KEEP_SERVICES_STOPPED')
    # Only before any DDL or after all preservation checks. An uncertain DDL outcome
    # cannot start services merely because the runner wants to clean up.
    restore_services(state)
    set_state(state,'DB_PREPARED' if origin in ('DB_VERIFIED_SERVICES_STOPPED','DB_PREPARED')
              else 'OLD_SERVICES_RESTORED_WITHOUT_DB_WRITES')
    return {'status':'SUCCEEDED','checks':{'old_services_restored':True}}


def main():
    import fcntl
    stage=Path(__file__).resolve().parents[1]
    request=json.loads(sys.stdin.read(16385))
    require(set(request)=={'phase','binding','snapshot'},'MAINTENANCE_REQUEST_FIELDS')
    binding=request['binding']
    require(set(binding)=={'commit','jar_sha256','archive_sha256','request_id','required_bytes'}
            and re.fullmatch('[a-f0-9]{40}',binding['commit'])
            and all(re.fullmatch('[a-f0-9]{64}',binding[k]) for k in ('jar_sha256','archive_sha256'))
            and re.fullmatch('[a-f0-9]{32}',binding['request_id'])
            and binding['required_bytes']==REQUIRED_BYTES,'MAINTENANCE_BINDING_FIELDS')
    lock=stage/'maintenance.lock'
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        secure(lock)
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if request['phase']=='freeze':
            require(request['snapshot'] is None,'FREEZE_SNAPSHOT_UNEXPECTED')
            return freeze(stage,binding)
        if request['phase']=='apply':return apply(stage,binding,request['snapshot'])
        require(request['phase']=='recover' and request['snapshot'] is None,'MAINTENANCE_PHASE')
        return recover(stage,binding)
    finally:os.close(fd)


if __name__=='__main__':
    try:print(json.dumps(main()))
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) else type(error).__name__.upper()
        if not re.fullmatch('[A-Z][A-Z0-9_]{0,79}',code):code='MAINTENANCE_FAILED_KEEP_RECORDS'
        print(json.dumps({'status':'STOPPED','codes':[code]}))
