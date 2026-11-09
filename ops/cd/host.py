"""Linux host adapter. Installed root-owned separately; never downloaded as release code."""
from contextlib import contextmanager
import json
import hashlib
import os
import re
import shutil
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

from manifest import digest, make_manifest, read_json, require, require_database, require_same_schema, validate_manifest


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(value, f, sort_keys=True); f.flush(); os.fsync(f.fileno())
    os.replace(temp, path)
    if os.name == 'posix':
        fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)


def command(args, timeout=30, stdin=None):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False, input=stdin,
                            env={**os.environ, 'AWS_MAX_ATTEMPTS': '1', 'AWS_PAGER': ''})
    require(result.returncode == 0, 'HOST_COMMAND_FAILED')
    return result.stdout.strip()


def secure(path):
    path = Path(path)
    require(path.is_absolute(), 'ABSOLUTE_PATH_REQUIRED')
    for part in [path, *path.parents]:
        s = part.lstat()
        require(not part.is_symlink() and s.st_uid == 0 and not s.st_mode & 0o022, 'UNTRUSTED_HOST_PATH')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


def http_check(check):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(check['url'], timeout=5) as response:
            status = response.status
            body = response.read(65537)
    except urllib.error.HTTPError as error:
        status, body = error.code, b''
    require(status == check['status'], 'HTTP_STATUS')
    if check.get('json_data'):
        require(len(body) <= 65536, 'HTTP_BODY_SIZE')
        parsed = json.loads(body)
        require(isinstance(parsed, dict) and parsed.get('data') is not None, 'HTTP_JSON_DATA')


class Host:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['root'])
        self.journal = {}
        secure(self.root)
        secure(self.root / 'releases'); secure(self.root / 'runs')
        secure(self.root / 'baseline.json')
        self.baseline = read_json(self.root / 'baseline.json')

    def release_path(self, release):
        m = release['manifest']
        from manifest import validate_manifest
        validate_manifest(m)
        return self.root / 'releases' / f"{m['commit']}-{m['run_id']}-{m['attempt']}"

    def existing(self, request):
        for path in (self.root / 'runs').glob('*.json'):
            item = read_json(path)
            require(item['status'] in {'SUCCEEDED', 'ROLLED_BACK'}, 'UNRESOLVED_RUN')
        path = self.root / 'runs' / (request['run_key'] + '.json')
        if path.exists():
            self.journal = read_json(path)
            require(self.journal['request'] == request, 'RUN_ID_CONFLICT')
            require(self.journal['status'] == 'SUCCEEDED', 'FAILED_RUN_REQUIRES_NEW_APPROVAL')
            require(self.baseline['manifest']['commit'] == request['commit'] and
                    self.baseline['manifest']['jar_sha256'] == request['jar_sha256'], 'OLD_RUN_NOT_CURRENT')
            self.runtime(self.baseline)
            return self.journal

    def prepare(self, request):
        # Root-owned staging is immutable per run. Never overwrite an uncertain attempt.
        folder = self.root / 'releases' / f"{request['commit']}-{request['run_id']}-{request['attempt']}"
        folder.mkdir(mode=0o755)
        prefix = f"{self.config['prefix']}/{request['commit']}/{request['run_id']}-{request['attempt']}"
        for name, version in [('manifest.json', request['manifest_version']), ('backend.jar', request['jar_version'])]:
            metadata = json.loads(command([self.config['aws'], 's3api', 'head-object', '--region', self.config['region'],
                    '--bucket', self.config['bucket'], '--key', prefix + '/' + name,
                    '--version-id', version, '--output', 'json'], 30))
            limit = 128*1024 if name == 'manifest.json' else m['jar_bytes']
            require(0 < metadata['ContentLength'] <= limit, 'S3_OBJECT_SIZE')
            require(shutil.disk_usage(folder).free >= limit + 2*1024**3, 'DISK_RESERVE_REQUIRED')
            command([self.config['aws'], 's3api', 'get-object', '--region', self.config['region'],
                     '--bucket', self.config['bucket'], '--key', prefix + '/' + name,
                     '--version-id', version, str(folder / name)], 120)
            os.chmod(folder / name, 0o644)
            if name == 'manifest.json':
                m = read_json(folder / name); validate_manifest(m)
                require((m['commit'],m['run_id'],m['attempt'],m['jar_sha256']) ==
                        (request['commit'],request['run_id'],request['attempt'],request['jar_sha256']), 'ARTIFACT_IDENTITY')
        actual = make_manifest(folder / 'backend.jar', request['commit'], request['run_id'], request['attempt'])
        require(m == actual and m['jar_sha256'] == request['jar_sha256'], 'ARTIFACT_MISMATCH')
        return {'manifest': m, 'protected': self.baseline['protected'],
                'environment_sha256': self.baseline['environment_sha256']}

    def protected(self):
        result = {}
        for raw in self.config['protected_paths']:
            path = Path(raw)
            paths = [path] + sorted(path.rglob('*')) if path.is_dir() else [path]
            # The pinned CLI distribution contains ~7,600 files, all protected.
            require(len(paths) < 10000, 'PROTECTED_PATH_LIMIT')
            total = 0
            for entry in paths:
                require(not entry.is_symlink(), 'PROTECTED_SYMLINK_UNSUPPORTED')
                s = entry.stat()
                if entry.is_file():
                    total += s.st_size
                    require(s.st_size <= 256*1024*1024 and total <= 1024**3,'PROTECTED_BYTES_LIMIT')
                result[str(entry)] = [s.st_uid, s.st_gid, s.st_mode,
                                      digest(entry) if entry.is_file() else 'directory']
        return result

    def unit(self, property_name):
        return command(['systemctl', 'show', self.config['service'], '--property=' + property_name, '--value'], 5)

    def identity(self): return self.unit('InvocationID')

    def require_protected_references(self, protected):
        files = self.unit('EnvironmentFiles')
        pattern = r'(/[^\s]+) \(ignore_errors=(?:yes|no)\)'
        require(not re.sub(pattern, '', files).strip(), 'UNSUPPORTED_ENVIRONMENT_FILES_SYNTAX')
        referenced = re.findall(pattern, files) + [self.unit('FragmentPath')] + self.unit('DropInPaths').split()
        require(all(p in protected for p in referenced), 'UNPROTECTED_SYSTEMD_INPUT')

    def runtime(self, release):
        folder = self.release_path(release)
        secure(folder / 'backend.jar'); secure(folder / 'manifest.json')
        require(digest(folder / 'backend.jar') == release['manifest']['jar_sha256'], 'RUNNING_JAR_HASH')
        require((self.root / 'current').resolve(strict=True) == folder, 'CURRENT_POINTER_CHANGED')
        require(self.unit('ActiveState') == 'active', 'SERVICE_NOT_ACTIVE')
        pid = int(self.unit('MainPID')); require(pid > 0, 'SERVICE_NO_PID')
        args = [x.decode('utf-8') for x in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0') if x]
        require(args == self.config['expected_argv'], 'SERVICE_ARGUMENTS_CHANGED')
        require(Path(f'/proc/{pid}/cwd').resolve() == Path(self.config['working_directory']), 'WORKING_DIRECTORY_CHANGED')
        require('-Dchatbot.developer-test-auto-consent=true' in args, 'DEVELOPER_GRANT_DISABLED')
        require(self.environment(pid, args) == release['environment_sha256'], 'PROCESS_ENVIRONMENT_CHANGED')
        require(self.protected() == release['protected'], 'PROTECTED_CONFIG_CHANGED')
        self.require_protected_references(release['protected'])

    def environment(self, pid, args):
        from database_probe import properties
        values = dict(x.decode('utf-8').split('=', 1) for x in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if b'=' in x)
        for key in ['INVOCATION_ID', 'JOURNAL_STREAM', 'SYSTEMD_EXEC_PID', 'NOTIFY_SOCKET', 'WATCHDOG_PID', 'WATCHDOG_USEC']:
            values.pop(key, None)
        ddl_env = {'SPRING_JPA_HIBERNATE_DDL_AUTO','SPRING_JPA_HIBERNATE_DDLAUTO'}
        require(not any(k in values for k in ['SPRING_APPLICATION_JSON','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS']), 'UNSUPPORTED_JVM_ENV_OVERRIDE')
        require(not any(a.startswith(('-Dspring.', '--spring.')) for a in args), 'UNSUPPORTED_SPRING_ARGUMENT_OVERRIDE')
        props = properties(self.config['database']['properties_file'])
        from runtime_contract import validate_overrides
        validate_overrides(values, props, self.config.get('runtime_contract'))
        primary = Path(self.config['working_directory']) / 'application-local.properties'
        require(Path(self.config['database']['properties_file']) == primary and
                not (primary.parent / 'backend/application-local.properties').exists(), 'UNSUPPORTED_ADDITIONAL_PROPERTIES')
        require(not any(k.startswith(('spring.config.', 'spring.profiles.')) for k in props), 'UNSUPPORTED_CONFIG_IMPORT')
        for key, env_key in [('product.import.enabled','PRODUCT_IMPORT_ENABLED'),
                             ('product.import.rollback.enabled','PRODUCT_IMPORT_ROLLBACK_ENABLED'),
                             ('recommendation.import.enabled','RECOMMENDATION_IMPORT_ENABLED'),
                             ('product.search.evaluation.enabled','PRODUCT_SEARCH_EVALUATION_ENABLED'),
                             ('recommendation.evaluation.enabled','RECOMMENDATION_EVALUATION_ENABLED'),
                             ('product.search.backfill.enabled','PRODUCT_SEARCH_BACKFILL_ENABLED'),
                             ('product.data-model.backfill.enabled','PRODUCT_DATA_MODEL_BACKFILL_ENABLED')]:
            require(props.get(key, 'false').lower() == 'false' and values.get(env_key, 'false').lower() == 'false', 'STARTUP_IMPORT_ENABLED')
            require(not any(a.startswith(('-D'+key+'=', '--'+key+'=')) for a in args), 'STARTUP_IMPORT_ARGUMENT')
        require(props.get('spring.jpa.hibernate.ddl-auto','validate') == 'validate' and
                values.get('HIBERNATE_DDL_AUTO','validate') == 'validate' and
                all(values.get(k,'validate') == 'validate' for k in ddl_env), 'DDL_MODE_NOT_VALIDATE')
        expected = {'spring.flyway.enabled':str(self.config['runtime_contract']['flyway_enabled']).lower(), 'spring.flyway.locations':'classpath:db/migration',
                    'spring.flyway.baseline-on-migrate':'true','spring.flyway.baseline-version':'0'}
        require(all(k in expected and v == expected[k] for k,v in props.items() if k.startswith('spring.flyway.')), 'FLYWAY_OVERRIDE')
        return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()

    def database(self, manifest):
        user = self.unit('User')
        require(user == self.config['db_user'] and user not in ['', 'root'], 'UNPRIVILEGED_PROBE_REQUIRED')
        require(self.config['db_python']=='/usr/bin/python3.12','ISOLATED_SYSTEM_PYTHON_REQUIRED')
        secure(self.config['db_python'])
        output = command(['/usr/sbin/runuser', '-u', user, '--', self.config['db_python'], '-I', '-S', '-B',
                          str(Path(__file__).with_name('database_probe.py'))], 35,
                         json.dumps({'database':self.config['database']}))
        require_database(manifest, json.loads(output))

    def preflight(self, previous, candidate):
        self.runtime(previous)
        require_same_schema(previous['manifest'], candidate['manifest'])
        self.database(candidate['manifest'])

    def rollback_preflight(self, previous, candidate):
        require(self.protected() == previous['protected'], 'PROTECTED_CONFIG_CHANGED')
        require(digest(self.release_path(previous) / 'backend.jar') == previous['manifest']['jar_sha256'], 'PREVIOUS_JAR_CHANGED')
        self.database(previous['manifest'])

    def record(self, request, status):
        self.journal = {'request': request, 'status': status, 'transition': self.transition}
        atomic_json(self.root / 'runs' / (request['run_key'] + '.json'), self.journal)

    def activate(self, release):
        folder = self.release_path(release)
        temp = self.root / 'current.next'
        temp.symlink_to(folder, target_is_directory=True)
        os.replace(temp, self.root / 'current')
        fd = os.open(self.root, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)

    def restart(self): command(['systemctl', 'restart', self.config['service']], 90)

    def verify(self, release, old_identity):
        deadline = time.monotonic() + 180
        while True:
            try:
                require(bool(self.identity()) and self.identity() != old_identity, 'OLD_PROCESS_STILL_RUNNING')
                self.runtime(release)
                for check in self.config['health_checks']: http_check(check)
                self.database(release['manifest'])
                return
            except Exception:
                if time.monotonic() >= deadline: raise ValueError('HEALTH_DEADLINE') from None
                time.sleep(3)

    def commit(self, release):
        atomic_json(self.root / 'baseline.json', release)
        self.baseline = release


@contextmanager
def deployment_lock(root):
    import fcntl
    with (Path(root) / 'deployment.lock').open('a') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
