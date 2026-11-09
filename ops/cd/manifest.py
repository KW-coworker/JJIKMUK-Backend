"""Artifact identity and schema checks. No credentials, networking, or SQL execution."""
import hashlib
import json
from pathlib import Path
import re
import zipfile
import zlib

REPOSITORY = 'KW-coworker/JJIKMUK-Backend'
MIGRATION = re.compile(r'BOOT-INF/classes/db/migration/V([1-9][0-9]*)__([A-Za-z0-9_]+)\.sql')


def require(ok, code):
    if not ok: raise ValueError(code)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''): h.update(part)
    return h.hexdigest()


def checksum(data):
    # Flyway CRC32 over UTF-8 lines, without line endings or the initial BOM.
    value = 0
    for line in re.split(r'\r\n|\r|\n', data.decode('utf-8-sig')):
        value = zlib.crc32(line.encode('utf-8'), value)
    return value if value < 2**31 else value - 2**32


def content_profile(jar):
    jar = Path(jar)
    require(0 < jar.stat().st_size <= 256 * 1024 * 1024, 'JAR_SIZE')
    migrations, configuration = [], {}
    with zipfile.ZipFile(jar) as z:
        require(len(z.namelist()) == len(set(z.namelist())), 'DUPLICATE_ZIP_ENTRY')
        require(len(z.namelist()) <= 20000, 'ZIP_ENTRY_LIMIT')
        for name, limit in [('META-INF/MANIFEST.MF', 65536),
                            ('BOOT-INF/classes/org/jjikmuk/backend/domain/chat/AiChatClient.class', 1024*1024)]:
            require(z.getinfo(name).file_size <= limit, 'ZIP_METADATA_SIZE')
        require(b'JarLauncher' in z.read('META-INF/MANIFEST.MF'), 'NOT_BOOT_JAR')
        grant = z.read('BOOT-INF/classes/org/jjikmuk/backend/domain/chat/AiChatClient.class')
        require(b'chatbot.developer-test-auto-consent' in grant, 'DEVELOPER_GRANT_MISSING')
        for name in sorted(z.namelist()):
            if name.startswith('BOOT-INF/classes/') and name.endswith(('.properties', '.yaml', '.yml')):
                require(z.getinfo(name).file_size <= 1024*1024 and len(configuration) < 100, 'CONFIGURATION_SIZE')
                data = z.read(name)
                # Only the reviewed OFF-default grant alias may differ at initial adoption.
                if name == 'BOOT-INF/classes/application.properties':
                    lines = [line for line in data.decode('utf-8').splitlines()
                             if line.strip() and not line.lstrip().startswith('#')]
                    alias = 'chatbot.developer-test-auto-consent=${CHATBOT_DEVELOPER_TEST_AUTO_CONSENT:false}'
                    require(lines.count(alias) <= 1, 'DUPLICATE_GRANT_PROPERTY')
                    data = '\n'.join(line for line in lines if line != alias).encode('utf-8')
                configuration[name] = hashlib.sha256(data).hexdigest()
            if not name.startswith('BOOT-INF/classes/db/migration/') or name.endswith('/'): continue
            match = MIGRATION.fullmatch(name)
            require(match is not None and z.getinfo(name).file_size < 1024 * 1024, 'UNSUPPORTED_MIGRATION')
            data = z.read(name)
            require(b'${' not in data, 'MIGRATION_PLACEHOLDERS_UNSUPPORTED')
            migrations.append({'version': match[1], 'script': name.rsplit('/', 1)[1],
                               'sha256': hashlib.sha256(data).hexdigest(), 'checksum': checksum(data)})
    return {'jar_sha256': digest(jar), 'jar_bytes': jar.stat().st_size,
            'developer_grant_supported': True, 'migrations': migrations, 'configuration': configuration}


def make_manifest(jar, commit, run_id, attempt):
    result = {'format': 1, 'repository': REPOSITORY, 'commit': commit, 'run_id': run_id,
              'attempt': attempt, **content_profile(jar)}
    validate_manifest(result)
    return result


def validate_manifest(m):
    require(m.get('format') == 1 and m.get('repository') == REPOSITORY, 'MANIFEST_FORMAT')
    for name, pattern in [('commit', r'[0-9a-f]{40}'), ('jar_sha256', r'[0-9a-f]{64}'),
                          ('run_id', r'[1-9][0-9]{0,19}'), ('attempt', r'[1-9][0-9]{0,3}')]:
        require(isinstance(m.get(name), str) and re.fullmatch(pattern, m[name]) is not None, 'MANIFEST_IDENTIFIER')
    require(type(m.get('jar_bytes')) is int and 0 < m['jar_bytes'] <= 256 * 1024 * 1024, 'JAR_SIZE')
    require(m.get('developer_grant_supported') is True, 'DEVELOPER_GRANT_MISSING')
    require(isinstance(m.get('configuration'), dict) and
            'BOOT-INF/classes/application.properties' in m['configuration'], 'CONFIGURATION_MISSING')
    rows = m.get('migrations')
    require(isinstance(rows, list) and 0 < len(rows) <= 100, 'MIGRATION_COUNT')
    require(len({x['version'] for x in rows}) == len(rows), 'DUPLICATE_MIGRATION_VERSION')
    for row in rows:
        require(re.fullmatch(r'[1-9][0-9]*', row['version']) is not None, 'MIGRATION_VERSION')
        require(re.fullmatch(r'V' + row['version'] + r'__[A-Za-z0-9_]+\.sql', row['script']) is not None, 'MIGRATION_SCRIPT')
        require(re.fullmatch(r'[0-9a-f]{64}', row['sha256']) is not None and type(row['checksum']) is int, 'MIGRATION_CHECKSUM')


def require_same_schema(previous, candidate):
    validate_manifest(previous); validate_manifest(candidate)
    require(previous['migrations'] == candidate['migrations'], 'SCHEMA_CHANGE_REQUIRES_SEPARATE_RELEASE')
    require(previous['configuration'] == candidate['configuration'], 'CONFIGURATION_CHANGE_REQUIRES_REVIEW')


def require_database(manifest, history):
    expected = {x['version']: (x['script'], x['checksum']) for x in manifest['migrations']}
    actual = {}
    for row in history:
        if row.get('type') == 'BASELINE':
            require(row.get('version') == '0' and row.get('success') is True, 'UNSUPPORTED_BASELINE')
            continue
        require(row.get('type') == 'SQL' and row.get('success') is True, 'FAILED_OR_UNSUPPORTED_MIGRATION')
        require(row['version'] not in actual, 'DUPLICATE_DATABASE_VERSION')
        actual[row['version']] = (row['script'], row['checksum'])
    require(actual == expected, 'DATABASE_HISTORY_MISMATCH')


def read_json(path):
    require(Path(path).stat().st_size <= 128 * 1024, 'JSON_TOO_LARGE')
    return json.loads(Path(path).read_text(encoding='utf-8'))
