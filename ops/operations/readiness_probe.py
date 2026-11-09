"""One approved commissioning observation. No application imports or mutation.

The document stages this probe and a hash-pinned wheel in a new /opt directory.
Only the DB child (uid ubuntu) imports that wheel. No pip, HTTP health/AI calls,
service changes, migrations, application row reads, or raw configuration output.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from urllib.parse import urlsplit, parse_qsl
from readiness_paths import checked_path

BACKEND = 'jjikmuk-backend.service'
CHATBOT = 'food-chatbot-team.service'
WORKDIR = '/home/ubuntu/JJIKMUK-Backend'
PROPS = WORKDIR + '/application-local.properties'
JAR = '/opt/jjikmuk-github/releases/20261103-developer-test-consent/backend.jar'
JAR_SHA = 'e3dc8ec36dca14dd7d9edfde1c6ed5e5a083073d7b6f00e62159af7f8382f2f1'
ARGV = ['/usr/bin/java', '-Xms128m', '-Xmx768m',
        '-Dchatbot.developer-test-auto-consent=true', '-jar', JAR]
DB_HOST = 'jjikmuk-dev-db.cp22o82i4ex5.ap-northeast-2.rds.amazonaws.com'
CA = '/opt/food-chatbot/rds-global-bundle.pem'
WHEEL = 'pymysql-1.2.3-py3-none-any.whl'
WHEEL_SHA = '14f1c68e2ed859243ae5ca41ffbe677027fc46bc136a9f0be8a4e928e5e7415a'
FIELDS = {'User', 'MainPID', 'ActiveState', 'WorkingDirectory', 'FragmentPath', 'EnvironmentFiles', 'DropInPaths'}


class ProbeStop(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise ProbeStop(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()


def open_regular(path):
    # Bind each directory component before opening the next; no parent-symlink race.
    p = Path(path)
    need(p.is_absolute() and '..' not in p.parts and len(p.parts) > 1, 'INPUT_PATH')
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in p.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        return os.open(p.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)


def read(path, limit, proc=False):
    fd = open_regular(path)
    with os.fdopen(fd, 'rb') as stream:
        a = os.fstat(stream.fileno())
        need(stat.S_ISREG(a.st_mode) and (proc or a.st_size <= limit), 'INPUT_LIMIT')
        raw = stream.read(limit + 1)
        b = os.fstat(stream.fileno())
    need(len(raw) <= limit and (a.st_ino, a.st_size, a.st_mtime_ns, a.st_ctime_ns) ==
         (b.st_ino, b.st_size, b.st_mtime_ns, b.st_ctime_ns), 'INPUT_CHANGED')
    return raw


def jar_digest():
    fd = open_regular(JAR)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 256 * 1024**2, 'JAR_SIZE')
        h = hashlib.sha256()
        remaining = before.st_size
        while remaining:
            block = stream.read(min(1024**2, remaining))
            need(bool(block), 'JAR_CHANGED')
            h.update(block)
            remaining -= len(block)
        after = os.fstat(stream.fileno())
    need((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
         (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'JAR_CHANGED')
    return h.hexdigest()


def unit(service, field):
    need(service in {BACKEND, CHATBOT} and field in FIELDS, 'UNIT_QUERY_REJECTED')
    p = subprocess.run(['/usr/bin/systemctl', 'show', service, '--property=' + field, '--value'],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                       timeout=5, cwd='/', env={'PATH': '/usr/bin:/bin', 'LANG': 'C'})
    need(p.returncode == 0 and len(p.stdout) <= 16384, 'UNIT_QUERY_FAILED')
    return p.stdout.decode().strip()


def process(service):
    need(unit(service, 'ActiveState') == 'active', 'SERVICE_NOT_ACTIVE')
    pid = unit(service, 'MainPID')
    need(re.fullmatch('[1-9][0-9]{0,8}', pid), 'PID_INVALID')
    args = read('/proc/' + pid + '/cmdline', 65536, True)
    start = read('/proc/' + pid + '/stat', 65536, True).rsplit(b') ', 1)[-1].split()[19]
    return pid, args, start


def backend_identity():
    import pwd
    state = process(BACKEND)
    need(unit(BACKEND, 'User') == 'ubuntu' and unit(BACKEND, 'WorkingDirectory') == WORKDIR,
         'BACKEND_IDENTITY_CHANGED')
    need(state[1] == b'\0'.join(x.encode() for x in ARGV) + b'\0', 'BACKEND_ARGV_CHANGED')
    need(os.stat('/proc/' + state[0]).st_uid == pwd.getpwnam('ubuntu').pw_uid != 0 and
         os.readlink('/proc/' + state[0] + '/cwd') == WORKDIR, 'BACKEND_PROCESS_CHANGED')
    return state


def environment(pid):
    raw = read('/proc/' + pid + '/environ', 262144, True)
    values = {}
    for row in raw.split(b'\0'):
        if not row:
            continue
        key, sep, value = row.decode().partition('=')
        need(sep and key and key not in values, 'ENVIRONMENT_AMBIGUOUS')
        values[key] = value
    return raw, values


def properties(raw):
    values = {}
    for row in raw.decode('utf-8-sig').splitlines():
        line = row.strip()
        if not line or line.startswith(('#', '!')):
            continue
        need('=' in line and '\\' not in line and '${' not in line, 'PROPERTIES_UNSUPPORTED')
        key, value = (x.strip() for x in line.split('=', 1))
        need(re.fullmatch('[A-Za-z0-9_.-]{1,160}', key) and key not in values, 'PROPERTIES_AMBIGUOUS')
        values[key] = value
    return values


def jdbc_options(query):
    pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True)
    options = dict(pairs)
    trust = {'trustCertificateKeyStoreUrl', 'trustCertificateKeyStoreType',
             'trustCertificateKeyStorePassword', 'fallbackToSystemTrustStore'}
    need(len(pairs) == len(options) and set(options) <= trust |
         {'serverTimezone', 'useSSL', 'allowPublicKeyRetrieval', 'characterEncoding', 'useUnicode',
          'sslMode', 'requireSSL', 'verifyServerCertificate'}, 'JDBC_OPTIONS_REQUIRES_REVIEW')
    # Recognize only the institution's existing Java trust profile. PyMySQL below
    # independently verifies its fixed PEM CA and hostname; it never uses this store.
    need(options.get('sslMode') == 'VERIFY_IDENTITY' and
         options.get('trustCertificateKeyStoreUrl') == 'file:/opt/food-chatbot/rds-institution-trust.p12' and
         options.get('trustCertificateKeyStoreType') == 'PKCS12' and
         options.get('fallbackToSystemTrustStore') == 'false' and
         0 < len(options.get('trustCertificateKeyStorePassword', '')) <= 1024,
         'JDBC_TRUST_PROFILE_REQUIRES_REVIEW')


def database_inputs():
    before = backend_identity()
    raw_env, values = environment(before[0])
    raw_props = read(PROPS, 65536)
    props = properties(raw_props)
    # A different source of JDBC credentials/host must not silently be ignored.
    allowed_spring = {'SPRING_MAIL_USERNAME', 'SPRING_MAIL_PASSWORD', 'SPRING_FLYWAY_ENABLED',
                      'SPRING_SQL_INIT_MODE', 'SPRING_JPA_HIBERNATE_DDL_AUTO', 'SPRING_JPA_HIBERNATE_DDLAUTO'}
    need(all(k in allowed_spring for k in values if re.sub('[^a-z0-9]', '', k.lower()).startswith('spring')),
         'SPRING_OVERRIDE_REQUIRES_REVIEW')
    need(not any(k in values for k in ('JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS')),
         'JAVA_OVERRIDE_REQUIRES_REVIEW')
    need(not any(re.sub('[^a-z0-9]', '', k.lower()).startswith(('springconfig', 'springprofiles')) for k in props),
         'PROPERTY_IMPORT_REQUIRES_REVIEW')
    url = props.get('spring.datasource.url', '')
    target = urlsplit(url.removeprefix('jdbc:'))
    need(url.startswith('jdbc:mysql://') and target.hostname == DB_HOST and (target.port or 3306) == 3306
         and target.path == '/jjikmuk' and not target.username and not target.password and not target.fragment,
         'DATABASE_TARGET_REJECTED')
    jdbc_options(target.query)
    need(bool(props.get('spring.datasource.username')) and bool(props.get('spring.datasource.password')),
         'DATABASE_CREDENTIALS_MISSING')
    return before, raw_env, raw_props, values, props


def unchanged(inputs):
    state, raw_env, raw_props, _, _ = inputs
    need(backend_identity() == state and environment(state[0])[0] == raw_env and
         read(PROPS, 65536) == raw_props, 'INPUTS_CHANGED_DURING_OBSERVATION')


def metadata(report, key, path):
    need(len(report['paths']) < 40 and len(report['counts']) < 90, 'METADATA_REPORT_LIMIT')
    report['paths'][key] = checked_path(path)
    try:
        info = Path(path).lstat()
    except FileNotFoundError:
        report['checks'][key + '.exists'] = False
        return path, None
    report['checks'][key + '.exists'] = True
    report['checks'][key + '.symlink'] = stat.S_ISLNK(info.st_mode)
    report['counts'][key + '.uid'] = info.st_uid
    report['counts'][key + '.mode'] = stat.S_IMODE(info.st_mode)
    return path, (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode, info.st_size, info.st_mtime_ns)


def service_metadata(report, prefix, service):
    state = process(service)
    observed = []
    def add(key, path):
        observed.append(metadata(report, key, path))
    work = unit(service, 'WorkingDirectory')
    add(prefix + '.working_directory', work)
    add(prefix + '.fragment', unit(service, 'FragmentPath'))
    text = unit(service, 'EnvironmentFiles')
    pattern = r'(/[^\s]+) \(ignore_errors=(?:yes|no)\)'
    need(not re.sub(pattern, '', text).strip(), 'ENVIRONMENT_FILE_SYNTAX')
    envs, drops = re.findall(pattern, text), unit(service, 'DropInPaths').split()
    need(len(envs) <= 24 and len(drops) <= 24, 'SERVICE_REFERENCE_LIMIT')
    for group, paths in [('env', envs), ('dropin', drops)]:
        for index, path in enumerate(paths):
            add(prefix + '.' + group + '_' + str(index), path)
    args = state[1].split(b'\0')
    add(prefix + '.executable', args[0].decode())
    add(prefix + '.executable_resolved', str(Path(args[0].decode()).resolve(strict=True)))
    report['hashes'][prefix + '.argv'] = digest(state[1])
    report['checks'][prefix + '.user_ubuntu'] = unit(service, 'User') == 'ubuntu'
    if prefix == 'chatbot':
        # Metadata only: .env can override path defaults, so never assert effective RAG readiness here.
        need(work.startswith(('/opt/food-chatbot/releases/', '/opt/jjikmuk-github/releases/',
                              '/opt/jjikmuk-chatbot/releases/')), 'CHATBOT_WORKDIR_REJECTED')
        add('chatbot.dotenv', work + '/.env')
        _, env = environment(state[0])
        for key, name, default in [('CHROMA_DB_DIR', 'rag_index', work + '/app/chroma_db'),
                                   ('RAG_DOCS_DIR', 'rag_docs', work + '/app/knowledge')]:
            value = env.get(key, default)
            add('chatbot.' + name, value)
        report['checks']['chatbot.rag_effective_configuration_verified'] = False
        req = read(work + '/requirements.txt', 65536)
        report['hashes']['chatbot.requirements'] = digest(req)
    need(process(service) == state, 'SERVICE_CHANGED_DURING_OBSERVATION')
    return state, observed


def query_schema(connect, props, contract):
    report = {'status': 'OK', 'checks': {}, 'hashes': {}, 'counts': {}, 'codes': []}
    with connect(host=DB_HOST, port=3306, database='jjikmuk', user=props['spring.datasource.username'],
                 password=props['spring.datasource.password'], ssl_ca=CA, ssl_verify_cert=True,
                 ssl_verify_identity=True, connect_timeout=5, read_timeout=10, write_timeout=5,
                 autocommit=True, local_infile=False) as conn:
        try:
            with conn.cursor() as cur:
                for query in ('SET SESSION MAX_EXECUTION_TIME=10000', 'SET SESSION lock_wait_timeout=5',
                              'START TRANSACTION READ ONLY'):
                    cur.execute(query)
                cur.execute('SELECT TABLE_NAME,COLUMN_NAME,ORDINAL_POSITION,COLUMN_TYPE,IS_NULLABLE,CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,ORDINAL_POSITION LIMIT 4097', ('jjikmuk',))
                columns = cur.fetchmany(4097)
                need(0 < len(columns) <= 4096, 'SCHEMA_COLUMN_LIMIT')
                cur.execute('SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART,INDEX_TYPE FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX LIMIT 4097', ('jjikmuk',))
                indexes = cur.fetchmany(4097)
                need(len(indexes) <= 4096, 'SCHEMA_INDEX_LIMIT')
                pairs = {(r[0], r[1]): r for r in columns}
                policy = pairs.get(('chatbot_logs', 'policy_version'))
                report['checks']['db.chatbot_policy_version_256'] = bool(policy and type(policy[5]) is int and policy[5] >= 256)
                for version, required in contract['required_columns'].items():
                    report['checks']['db.v' + version + '_columns_present'] = all(tuple(p) in pairs for p in required)
                report['hashes']['db.columns_indexes'] = digest(canonical([columns, indexes]))
                report['counts'].update(db_columns=len(columns), db_indexes=len(indexes), database_connections=1)
                history = []
                if any(r[0] == 'flyway_schema_history' for r in columns):
                    cur.execute('SELECT version,script,checksum,success,type FROM flyway_schema_history ORDER BY installed_rank LIMIT 102')
                    history = cur.fetchmany(102)
                    need(len(history) <= 101, 'SCHEMA_HISTORY_LIMIT')
                report['counts']['db_history_rows'] = len(history)
                actual = {}
                valid = bool(history)
                for version, script, checksum, success, kind in history:
                    if kind == 'BASELINE':
                        valid = valid and version == '0' and success == 1
                        continue
                    valid = valid and kind == 'SQL' and success == 1 and version not in actual
                    actual[version] = [script, checksum]
                expected = {m['version']: [m['script'], m['checksum']] for m in contract['migrations']}
                report['checks']['db.history_matches_candidate'] = bool(valid and actual == expected)
                for v in ('18', '19', '20'):
                    report['checks']['db.v' + v + '_history_matches'] = v in expected and actual.get(v) == expected[v]
                report['hashes']['db.history'] = digest(canonical(history))
        finally:
            conn.rollback()
    return report


def load_pinned_vendor(stage):
    wheel = stage / WHEEL
    for p in [wheel, *wheel.parents]:
        s = p.lstat()
        need(not p.is_symlink() and s.st_uid == 0 and not s.st_mode & 0o022, 'DB_VENDOR_UNTRUSTED')
    raw = read(wheel, 46740)
    need(len(raw) == 46740 and digest(raw) == WHEEL_SHA, 'DB_VENDOR_HASH')
    sys.path.insert(0, str(wheel))


def trusted_ca():
    for path in [Path(CA), *Path(CA).parents]:
        s = path.lstat()
        need(not path.is_symlink() and s.st_uid == 0 and not s.st_mode & 0o022, 'DB_CA_UNTRUSTED')
    need(bool(read(CA, 262144)), 'DB_CA_EMPTY')


def observe(contract, stage, contract_sha):
    report = {'status': 'OK', 'checks': {'deployment_ready': False}, 'hashes': {}, 'counts': {}, 'codes': [] , 'paths': {}}
    need(os.geteuid() == 0 and jar_digest() == JAR_SHA, 'RUNNING_JAR_CHANGED')
    inputs = database_inputs()
    report['hashes']['backend.jar'] = JAR_SHA
    report['checks']['backend.flyway_disabled'] = inputs[3].get('SPRING_FLYWAY_ENABLED', inputs[4].get('spring.flyway.enabled', 'true')) == 'false'
    report['checks']['backend.sql_init_never'] = inputs[3].get('SPRING_SQL_INIT_MODE', inputs[4].get('spring.sql.init.mode')) == 'never'
    report['checks']['backend.cd_paths_absent'] = not any(os.path.lexists(p) for p in ('/opt/jjikmuk-cd', '/etc/jjikmuk-cd'))
    snapshots = {}
    for prefix, service in [('backend', BACKEND), ('chatbot', CHATBOT)]:
        try:
            section = {'paths': {}, 'checks': {}, 'counts': {}, 'hashes': {}}
            identity = service_metadata(section, prefix, service)
            snapshots[prefix] = identity, canonical(section)
            for key in section:
                report[key].update(section[key])
        except Exception:
            report['codes'].append(prefix.upper() + '_METADATA_REQUIRES_REVIEW')
    need(len(report['paths']) <= 40 and len(report['counts']) <= 85 and
         len(report['checks']) <= 85, 'METADATA_REPORT_LIMIT')
    child = "import sys,runpy;sys.path.insert(0," + repr(str(stage)) + ");sys.argv=[" + repr(str(stage/'readiness_probe.py')) + ",'--database'," + repr(contract_sha) + "];runpy.run_path(sys.argv[0],run_name='__main__')"
    result = subprocess.run(['/usr/sbin/runuser', '-u', 'ubuntu', '--', '/usr/bin/python3.12', '-I', '-S', '-B', '-c', child],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=65, cwd='/',
                            env={'PATH': '/usr/bin:/bin', 'LANG': 'C'}, stdin=subprocess.DEVNULL)
    need(len(result.stdout) <= 8192, 'DB_REPORT_LIMIT')
    if result.returncode:
        report['checks']['db.read_succeeded'] = False
        report['codes'].append('DATABASE_READ_FAILED_NO_RETRY')
    else:
        db = json.loads(result.stdout)
        for key in ('checks', 'hashes', 'counts'):
            report[key].update(db[key])
        report['checks']['db.read_succeeded'] = True
    unchanged(inputs)
    for prefix, service in [('backend', BACKEND), ('chatbot', CHATBOT)]:
        if prefix in snapshots:
            section = {'paths': {}, 'checks': {}, 'counts': {}, 'hashes': {}}
            identity = service_metadata(section, prefix, service)
            need((identity, canonical(section)) == snapshots[prefix], 'SERVICE_REFERENCES_CHANGED')
    need(jar_digest() == JAR_SHA, 'RUNNING_JAR_CHANGED')
    report['checks']['observation_stable'] = True
    report['checks']['complete_service_metadata'] = len(snapshots) == 2
    report['counts'].update(service_restarts=0, application_writes=0, database_mutations=0, paid_ai_calls=0)
    space = os.statvfs('/opt')
    report['counts']['free_bytes'] = space.f_bavail * space.f_frsize
    report['codes'].extend(['OBSERVATION_ONLY_NOT_DEPLOYMENT_APPROVAL', 'RAG_HTTP_BACKUP_NOT_VERIFIED'])
    return report


def main():
    try:
        need(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode, 'ISOLATED_RUNTIME_REQUIRED')
        stage = Path(__file__).parent
        mode, expected = sys.argv[1:]
        need(mode in {'--observe', '--database'} and re.fullmatch('[a-f0-9]{64}', expected), 'FIXED_MODE_REQUIRED')
        raw = read(stage / 'contract.json', 16384)
        need(digest(raw) == expected, 'CONTRACT_CHANGED')
        contract = json.loads(raw)
        if mode == '--database':
            import pwd
            need(os.geteuid() == pwd.getpwnam('ubuntu').pw_uid != 0, 'UNPRIVILEGED_DB_REQUIRED')
            inputs = database_inputs()
            trusted_ca()
            load_pinned_vendor(stage)
            import pymysql
            report = query_schema(pymysql.connect, inputs[4], contract)
            unchanged(inputs)
        else:
            report = observe(contract, stage, expected)
        encoded = json.dumps(report)
        need(len(encoded.encode()) <= 16000, 'REPORT_LIMIT')
        print(encoded)
    except ProbeStop as error:
        print(json.dumps({'status': 'PREFLIGHT_FAILED', 'codes': [str(error)]}))
        raise SystemExit(1)
    except Exception:
        print('{"status":"PREFLIGHT_FAILED","codes":["READINESS_FAILED_DETAILS_WITHHELD"]}')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
