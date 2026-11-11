"""Read only the stopped second catalog run, including bounded startup diagnostics."""
from connection import HOSTS, canonical, sha
from bootstrap import need
from run import read_object, execute
from maintenance_gate import Gate

REQUEST = 'a5291163ee0a456b85366e6075d8fce6'
RUN = '42942707829'
RECEIPT_SHA = 'bfaa2162ac56995135a9c6bb9c5bb07130e56ccde592d7fa080329560ccecae2'

HOST_SCRIPT = r'''
import fcntl, hashlib, json, os, re, shutil, signal, sqlite3, subprocess, sys
from pathlib import Path
from contextlib import closing
sys.dont_write_bytecode = True
sys.path.insert(0, '/opt/jjikmuk-cd/bin')
from host import secure
from manifest import require, digest

class InspectionDeadline(BaseException): pass
def deadline(*unused): raise InspectionDeadline()

def state_code(prefix, value):
    require(re.fullmatch('[A-Z][A-Z0-9_]{0,49}',value), 'STATE_INSPECTION_STATUS')
    return prefix+value

def log_codes(text):
    # Return only known diagnostic categories, never free-form log messages.
    patterns = {
        'STARTUP_FAILED': r'APPLICATION FAILED TO START',
        'JPA_SCHEMA_VALIDATION': r'Schema-validation|SchemaManagementException',
        'MISSING_TABLE': r'missing table|Table .* doesn.t exist',
        'MISSING_COLUMN': r'missing column|Unknown column',
        'COLUMN_TYPE_MISMATCH': r'wrong column type',
        'ENUM_CONVERSION': r'No enum constant',
        'DATABASE_CONNECTION': r'JDBCConnectionException|CommunicationsException|HikariPool.*Exception',
        'BEAN_CREATION': r'BeanCreationException|UnsatisfiedDependencyException',
        'CLASS_NOT_FOUND': r'ClassNotFoundException|NoClassDefFoundError',
        'JAR_ACCESS': r'Unable to access jarfile|Error opening zip file|Unable to access jar',
        'OUT_OF_MEMORY': r'OutOfMemoryError|oom-kill|OOMKilled',
        'ADDRESS_IN_USE': r'Address already in use|Port .* already in use',
        'RUNTIME_TIMEOUT': r'runtime time limit|Result: timeout|result .timeout.|Failed with result .timeout.',
        'STARTUP_TIMEOUT': r'Start operation timed out|start operation timed out',
        'EXIT_CODE_FAILURE': r'Failed with result .exit-code.',
        'ACCESS_DENIED': r'Permission denied|Access denied',
    }
    return [key for key, pattern in patterns.items() if re.search(pattern, text)]

def journal_counts(path, expected):
    sidecars = [path.with_name(path.name+suffix) for suffix in ('-journal','-wal','-shm')]
    counts = {'journal_readable':0,'journal_sidecars':sum(int(item.exists()) for item in sidecars)}
    if counts['journal_sidecars']:
        return counts, ['SQLITE_SIDECAR_PRESERVED']
    with path.open('rb') as stream:
        header = stream.read(100)
    if not (len(header) == 100 and header[:16] == b'SQLite format 3\x00' and header[18:20] == b'\x01\x01'):
        return counts, ['SQLITE_FORMAT_REVIEW_REQUIRED']
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as journal:
            journal.execute('PRAGMA query_only=ON')
            journal.execute('PRAGMA busy_timeout=1000')
            require(json.loads(journal.execute("SELECT value FROM metadata WHERE key='binding'").fetchone()[0]) == expected,
                    'STATE_INSPECTION_JOURNAL_BINDING')
            counts['baseline_rows'] = journal.execute('SELECT COUNT(*) FROM baseline').fetchone()[0]
            for status, number in journal.execute('SELECT status,COUNT(*) FROM changes GROUP BY status'):
                require(status in ('PREPARED','COMMITTED','RESTORED_OR_NOT_COMMITTED'), 'STATE_INSPECTION_JOURNAL_STATUS')
                counts['journal_'+status.lower()] = number
            counts['journal_rows'] = journal.execute('SELECT COUNT(*) FROM changes').fetchone()[0]
            counts['journal_readable'] = 1
    except sqlite3.Error:
        return counts, ['SQLITE_READ_UNAVAILABLE']
    return counts, []

signal.signal(signal.SIGALRM, deadline)
signal.alarm(300)
try:
    require(os.geteuid() == 0 and sys.flags.isolated and sys.flags.no_site, 'STATE_INSPECTION_RUNTIME')
    stage = Path('/opt/jjikmuk-catalog-' + binding['archive_sha256'][:16])
    secure(stage)
    for name, meta in envelope['files'].items():
        path = stage / name
        secure(path)
        require(path.stat().st_size == meta['bytes'] and digest(path) == meta['sha256'], 'STATE_INSPECTION_CODE')
    from coordination import ROOT
    for path in (ROOT, ROOT/'host.lock', ROOT/'state.json'): secure(path)
    with (ROOT/'host.lock').open('r') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        raw_coord = (ROOT/'state.json').read_bytes()
        coord = json.loads(raw_coord)
        operation = hashlib.sha256((binding['request_id']+':'+binding['run_id']+':recover').encode()).hexdigest()
        require(coord.get('component') == 'db' and coord.get('operation_id') == operation, 'STATE_INSPECTION_COORDINATOR')
        for phase in ('freeze', 'apply', 'recover'):
            unit = 'jjikmuk-catalog-'+phase+'-'+binding['archive_sha256'][:16]
            value = subprocess.run(['/usr/bin/systemctl','is-active',unit],capture_output=True,timeout=5)
            require(value.stdout.strip() in (b'inactive',b'failed',b'unknown'), 'STATE_INSPECTION_UNIT_RUNNING')
        sys.path.insert(0, str(stage/'bin'))
        from catalog_host import Work
        from initial_schema import read_from_connection
        work = Work(stage, binding)
        work.load()
        raw_state = (stage/'state.json').read_bytes()
        counts = {'host_free_bytes':shutil.disk_usage(stage).free}
        hashes = {'state_sha256':hashlib.sha256(raw_state).hexdigest(),
                  'coordination_sha256':hashlib.sha256(raw_coord).hexdigest(),
                  'baseline_commit':hashlib.sha256(work.host.baseline['manifest']['commit'].encode()).hexdigest()}
        codes = []
        for prefix, value in [('STATE_',work.state['status']),('COORD_',coord['status'])]:
            codes.append(state_code(prefix,value))
        for group in ('counts','recovery_counts','value_verification','recovery_verification'):
            values = work.state.get(group,{})
            for key, value in values.items():
                if type(value) is int and 0 <= value < 2**63:
                    require(re.fullmatch('[a-z_]{1,45}',key), 'STATE_INSPECTION_COUNT')
                    counts[group+'_'+key] = value
        current = (work.host.root/'current').resolve(strict=True)
        counts['pointer_previous'] = int(current == work.host.release_path(work.state['previous']))
        counts['pointer_candidate'] = int(current == work.host.release_path(work.state['candidate_release']))
        counts['protected_unchanged'] = int(work.host.protected() == work.state['previous']['protected'])
        require(work.host.config['db_user'] == 'ubuntu', 'STATE_INSPECTION_SERVICE_USER')
        for label, release in [('previous',work.state['previous']),('candidate',work.state['candidate_release'])]:
            folder = work.host.release_path(release)
            secure(folder);secure(folder/'backend.jar')
            counts[label+'_directory_mode'] = folder.stat().st_mode & 0o777
            counts[label+'_jar_mode'] = (folder/'backend.jar').stat().st_mode & 0o777
            readable = subprocess.run(['/usr/sbin/runuser','-u','ubuntu','--','/usr/bin/test','-r',str(folder/'backend.jar')],capture_output=True,timeout=5)
            require(readable.returncode in (0,1), 'STATE_INSPECTION_ACCESS_CHECK')
            counts[label+'_jar_service_readable'] = int(readable.returncode == 0)
        journal_path = stage/'before-values.sqlite'
        secure(journal_path)
        hashes['journal_sha256'] = digest(journal_path)
        counts['journal_bytes'] = journal_path.stat().st_size
        expected = {'dataset':work.dataset,'source_sha256':binding['source_sha256'],'commit':binding['commit']}
        observed, journal_codes = journal_counts(journal_path, expected)
        counts.update(observed); codes.extend(journal_codes)
        with work.connect() as conn:
            schema = read_from_connection(conn)
            counts['schema_matches_before'] = int(schema == work.state['schema'])
            counts['v21_success'] = sum(int(row['version']=='21' and row['success']) for row in schema['history'])
            counts['failed_migrations'] = sum(int(not row['success']) for row in schema['history'])
            hashes['schema_sha256'] = hashlib.sha256(json.dumps(schema,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        for label, unit in [('backend','jjikmuk-backend.service'),('chatbot','food-chatbot-team.service'),
                            ('apply','jjikmuk-catalog-apply-'+binding['archive_sha256'][:16]),
                            ('recover','jjikmuk-catalog-recover-'+binding['archive_sha256'][:16])]:
            value = subprocess.run(['/usr/bin/systemctl','show',unit,'--property=ActiveState,SubState,Result,ExecMainStatus,NRestarts'],capture_output=True,text=True,timeout=5)
            props = dict(line.split('=',1) for line in value.stdout.splitlines() if '=' in line)
            counts[label+'_active'] = int(props.get('ActiveState')=='active')
            counts[label+'_activating'] = int(props.get('ActiveState')=='activating')
            for key in ('ExecMainStatus','NRestarts'):
                raw = props.get(key,'')
                if re.fullmatch('[0-9]{1,12}',raw): counts[label+'_'+key] = int(raw)
            for key in ('ActiveState','SubState','Result'):
                raw = props.get(key,'')
                if re.fullmatch('[a-z-]{1,35}',raw): codes.append((label+'_'+key+'_'+raw).upper().replace('-','_'))
            log = subprocess.run(['/usr/bin/journalctl','-u',unit,'--since','2026-11-11 02:00:00 UTC','-n','180','--no-pager','-o','cat'],capture_output=True,timeout=10)
            require(log.returncode == 0 and len(log.stdout) <= 512*1024, 'STATE_INSPECTION_LOG_BOUND')
            codes.extend(label.upper()+'_'+code for code in log_codes(log.stdout.decode('utf-8',errors='replace')))
        require(digest(journal_path) == hashes['journal_sha256'] and (stage/'state.json').read_bytes() == raw_state and
                (ROOT/'state.json').read_bytes() == raw_coord, 'STATE_INSPECTION_RECORD_CHANGED')
        codes = sorted(set(codes))
        require(len(codes) <= 50 and len(counts) <= 100, 'STATE_INSPECTION_REPORT_BOUND')
        print(json.dumps({'status':'VERIFIED','checks':{'read_only':True,'records_unchanged':True},
                          'counts':counts,'hashes':hashes,'codes':codes}))
except (Exception, InspectionDeadline) as error:
    code = str(error) if isinstance(error,ValueError) and re.fullmatch('[A-Z0-9_]{1,70}',str(error)) else type(error).__name__.upper()
    print(json.dumps({'status':'STOPPED','codes':[code]}));sys.exit(1)
'''


def document(saved):
    need(sha(canonical(saved)) == RECEIPT_SHA, 'STATE_INSPECTION_RECEIPT_CHANGED')
    script = 'binding='+repr(saved['binding'])+'\nenvelope='+repr(saved['envelope'])+'\n'+HOST_SCRIPT
    return {'schemaVersion':'2.2','parameters':{},'description':'Read exact stopped catalog state and sanitized startup categories',
            'mainSteps':[{'action':'aws:runShellScript','name':'report','inputs':{'timeoutSeconds':'360',
                'runCommand':["/usr/bin/python3.12 -I -S -B - <<'JJIKMUK_CATALOG_STATE'\n"+script+'\nJJIKMUK_CATALOG_STATE']}}]}


def inspect(api, ctx):
    need(ctx['request_id'] == REQUEST, 'STATE_INSPECTION_REQUEST')
    gate, _ = Gate(api['s3']).read()
    need(gate is not None and gate['request_id'] == REQUEST and gate['run_id'] == RUN and gate['state'] == 'WORKING', 'STATE_INSPECTION_GATE')
    saved = read_object(api['s3'],'receipts/catalog/'+RUN+'/binding.json')
    plan = {'format':1,'component':'db','operation':'inspect','approved':True,
            'approval_id':'USER_SOURCE_COMPATIBILITY_AND_DB_APPLY_20261111','document':document(saved)}
    result = execute(api,ctx,plan,sha(canonical(plan)),HOSTS['backend'])
    need(result['success'], 'STATE_INSPECTION_FAILED')
    return dict(result,request_id=REQUEST,commit=ctx['commit'])
