"""Host-only V17-V20 preconditions and bounded Flyway execution; no SQL repair."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

if __name__ == '__main__':
    import re
    source = Path(__file__).resolve()
    assert re.fullmatch('/opt/jjikmuk-initial-[a-f0-9]{16}/bin/initial_schema.py', str(source))
    for path in [source, *source.parents]:
        st = path.lstat()
        assert not path.is_symlink() and st.st_uid == 0 and not st.st_mode & 0o022
    assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
    sys.path.insert(0, str(source.parent))

from manifest import digest, require, require_database
from initial_contract import DB_HOST, PROPS

SQL_HASHES = {
    '17': '7a0443f4db2855a16ed55c8ce2e9742435d34c6bea31795493c184bf3e50fb74',
    '18': '173087629c3fe95212efc6942f9849f3f0afc9d1345c33050ea324501bcd351b',
    '19': 'b6164216d558678654bbb2695a27db5a636650735b060e9623ee761eea5d83e5',
    '20': '3e86e540ea1a1a3bb9d6a24824c33e4aba4b476a232202c72962276b0f9a73a7',
}
NEW_TABLES = {'chat_conversations', 'chat_turns', 'account_analysis_selections',
              'account_analysis_selection_families'}


def validate_source(manifest):
    rows = {m['version']: m for m in manifest['migrations']}
    require(set(rows) == {str(i) for i in range(1, 21)}, 'INITIAL_MIGRATION_SET_CHANGED')
    require(all(rows[v]['sha256'] == expected for v, expected in SQL_HASHES.items()),
            'APPROVED_INITIAL_SQL_CHANGED')


def verify_schema(manifest, metadata, prepared, *, fulltext_maintenance=False):
    validate_source(manifest)
    columns, indexes, history = metadata['columns'], metadata['indexes'], metadata['history']
    require(0 < len(columns) <= 4096 and len(indexes) <= 4096 and len(history) <= 101
            and len(metadata['foreign_keys']) <= 4096,
            'SCHEMA_METADATA_LIMIT')
    pairs = {(r[0], r[1]): r for r in columns}
    tables = {r[0] for r in columns}
    engines = {r[0]: r for r in metadata['tables']}
    require({'products', 'products_rollback', 'users', 'family_profiles'} <= tables
            and 'products_staging' not in tables, 'INITIAL_TABLE_SET_CHANGED')
    expected = dict(manifest, migrations=[m for m in manifest['migrations'] if prepared or int(m['version']) <= 16])
    require(sum(r['type'] == 'BASELINE' for r in history) == 1, 'INITIAL_BASELINE_COUNT')
    require_database(expected, history)
    require((NEW_TABLES <= tables) if prepared else not (NEW_TABLES & tables), 'INITIAL_TABLE_STATE')
    for table in ('users', 'family_profiles'):
        row = pairs.get((table, 'id'))
        unique = {}
        for idx in indexes:
            if idx[0] == table and idx[2] == 0:
                unique.setdefault(idx[1], []).append(idx)
        require(row is not None and row[3:5] == ['bigint', 'NO']
                and any(len(rows) == 1 and rows[0][3:6] == [1, 'id', None] for rows in unique.values())
                and engines.get(table, [None, None])[1] == 'InnoDB', 'INITIAL_FK_PARENT_INCOMPATIBLE')
    if not prepared:
        for table in ('products', 'products_rollback'):
            require(engines.get(table, [None, None, None])[1:] == ['InnoDB', 'Dynamic'], 'V17_TABLE_ENGINE_REQUIRES_REVIEW')
            fulltext = [r for r in indexes if r[0] == table and r[6] == 'FULLTEXT']
            allowed = [['products', 'ft_products_search_keywords', 1, 1, 'search_keywords', None, 'FULLTEXT']]
            require(not fulltext or (fulltext_maintenance and table == 'products' and fulltext == allowed),
                    'V17_FULLTEXT_REQUIRES_SEPARATE_MAINTENANCE')
    for table, column, kind, nullable in [('products', 'nutrition_basis_raw', 'varchar(255)', 'YES'),
            ('products_rollback', 'nutrition_basis_raw', 'varchar(255)', 'YES'),
            ('users', 'profile_version', 'bigint', 'NO')]:
        row = pairs.get((table, column))
        require((row is not None and row[3] == kind and row[4] == nullable) if prepared else row is None,
                'INITIAL_COLUMN_STATE')
        if prepared:
            require(row[6] == ('0' if table == 'users' else None) and row[7] == '', 'INITIAL_COLUMN_DEFAULT')
    if prepared:
        from initial_schema_contract import verify_new_tables
        verify_new_tables(metadata)


def verify_preservation(before, after):
    # All pre-existing columns/indexes must remain byte-for-byte equal in metadata.
    columns = {(r[0], r[1]): r for r in after['columns']}
    require(all(columns.get((r[0], r[1])) == r for r in before['columns']), 'EXISTING_COLUMN_CHANGED')
    require(all(r in after['indexes'] for r in before['indexes']), 'EXISTING_INDEX_CHANGED')
    require(all(r in after['foreign_keys'] for r in before['foreign_keys']), 'EXISTING_FOREIGN_KEY_CHANGED')


def metadata(stage):
    """One unprivileged TLS metadata read; stdout stays inside this host process."""
    result = subprocess.run(['/usr/sbin/runuser', '-u', 'ubuntu', '--', '/usr/bin/python3.12',
        '-I', '-S', '-B', str(stage / 'bin/initial_schema.py'), '--read'],
        capture_output=True, timeout=40, cwd='/', env={'PATH': '/usr/bin:/bin', 'LANG': 'C'})
    require(result.returncode == 0 and not result.stderr and len(result.stdout) < 1024**2,
            'INITIAL_DB_METADATA_FAILED')
    return json.loads(result.stdout)


def read_metadata():
    import pwd
    require(os.geteuid() == pwd.getpwnam('ubuntu').pw_uid != 0, 'UNPRIVILEGED_DB_READ_REQUIRED')
    stage = Path(__file__).resolve().parents[1]
    from package_install import WHEEL_NAME, WHEEL_SHA
    wheel = stage / 'vendor' / WHEEL_NAME
    from host import secure
    secure(wheel)
    require(digest(wheel) == WHEEL_SHA, 'INITIAL_DB_VENDOR_CHANGED')
    sys.path.insert(0, str(wheel))
    import pymysql
    from database_probe import properties
    props = properties(PROPS)
    with pymysql.connect(host=DB_HOST, port=3306, database='jjikmuk',
        user=props['spring.datasource.username'], password=props['spring.datasource.password'],
        ssl_ca='/opt/food-chatbot/rds-global-bundle.pem', ssl_verify_cert=True, ssl_verify_identity=True,
        connect_timeout=5, read_timeout=10, write_timeout=5, autocommit=True, local_infile=False) as conn:
        return read_from_connection(conn)


def read_from_connection(conn):
    try:
        with conn.cursor() as cur:
            cur.execute('SET SESSION MAX_EXECUTION_TIME=10000')
            cur.execute('START TRANSACTION READ ONLY')
            cur.execute('SELECT TABLE_NAME,ENGINE,ROW_FORMAT FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME LIMIT 102', ('jjikmuk',))
            tables = cur.fetchmany(102)
            require(len(tables) <= 101, 'SCHEMA_TABLE_LIMIT')
            cur.execute('SELECT TABLE_NAME,COLUMN_NAME,ORDINAL_POSITION,COLUMN_TYPE,IS_NULLABLE,CHARACTER_MAXIMUM_LENGTH,COLUMN_DEFAULT,EXTRA FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,ORDINAL_POSITION LIMIT 4097', ('jjikmuk',))
            columns = cur.fetchmany(4097)
            cur.execute('SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART,INDEX_TYPE FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX LIMIT 4097', ('jjikmuk',))
            indexes = cur.fetchmany(4097)
            cur.execute('SELECT k.TABLE_NAME,k.CONSTRAINT_NAME,k.ORDINAL_POSITION,k.COLUMN_NAME,k.REFERENCED_TABLE_SCHEMA,k.REFERENCED_TABLE_NAME,k.REFERENCED_COLUMN_NAME,r.UPDATE_RULE,r.DELETE_RULE FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r ON k.CONSTRAINT_SCHEMA=r.CONSTRAINT_SCHEMA AND k.TABLE_NAME=r.TABLE_NAME AND k.CONSTRAINT_NAME=r.CONSTRAINT_NAME WHERE k.CONSTRAINT_SCHEMA=%s ORDER BY k.TABLE_NAME,k.CONSTRAINT_NAME,k.ORDINAL_POSITION LIMIT 4097', ('jjikmuk',))
            foreign_keys = cur.fetchmany(4097)
            cur.execute('SELECT version,script,checksum,success,type FROM flyway_schema_history ORDER BY installed_rank LIMIT 102')
            history = [dict(version=v, script=s, checksum=c, success=bool(ok), type=t)
                       for v, s, c, ok, t in cur.fetchmany(102)]
            return {'columns': columns, 'indexes': indexes, 'history': history, 'foreign_keys': foreign_keys, 'tables': tables}
    finally:
        conn.rollback()


def extract_runtime(jar, stage):
    """No application imports/startup. Only immutable libraries and SQL from the JAR."""
    import hashlib
    for name in ('lib', 'sql'):
        target = stage / name
        target.mkdir(mode=0o755)
        os.chmod(target, 0o755)
    with zipfile.ZipFile(jar) as z:
        for info in z.infolist():
            name = info.filename
            prefix = 'BOOT-INF/lib/' if name.startswith('BOOT-INF/lib/') else 'BOOT-INF/classes/db/migration/'
            if not name.startswith(prefix) or info.is_dir():
                continue
            short = name.removeprefix(prefix)
            require('/' not in short and '\\' not in short and 0 < info.file_size < 100*1024**2,
                    'INITIAL_RUNTIME_MEMBER')
            target = stage / ('lib' if prefix == 'BOOT-INF/lib/' else 'sql') / short
            with target.open('xb') as f:
                f.write(z.read(info))
                f.flush()
                os.fsync(f.fileno())
            os.chmod(target, 0o644)
    require((stage / 'lib/flyway-core-11.14.1.jar').is_file()
            and (stage / 'lib/flyway-mysql-11.14.1.jar').is_file()
            and (stage / 'lib/mysql-connector-j-9.7.0.jar').is_file(), 'INITIAL_DRIVER_VERSION_CHANGED')


def bounded_process(args, data, timeout):
    """Kill the whole child process group on timeout; caller's cgroup is a final bound."""
    import signal
    with subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, cwd='/', env={'PATH': '/usr/bin:/bin', 'LANG': 'C'}) as child:
        try:
            stdout, stderr = child.communicate(data, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.communicate(timeout=5)
            raise ValueError('SCHEMA_PROCESS_TIMEOUT_KEEP_RECORDS') from None
        return subprocess.CompletedProcess(args, child.returncode, stdout, stderr)


def apply(stage, props):
    data = b'\n'.join(base64.b64encode(props[k].encode()) for k in
                     ('spring.datasource.url', 'spring.datasource.username', 'spring.datasource.password')) + b'\n'
    result = bounded_process(['/usr/sbin/runuser', '-u', 'ubuntu', '--', '/usr/bin/java',
        '-Xms32m', '-Xmx192m', '-cp', str(stage / 'lib/*') + ':' + str(stage / 'bin/java'),
        'InitialSchema', str(stage)], data, 180)
    require(len(result.stdout) < 4096, 'SCHEMA_OUTPUT_LIMIT')
    try:
        report = json.loads(result.stdout)
    except Exception:
        raise ValueError('SCHEMA_OUTPUT_UNEXPECTED_KEEP_RECORDS') from None
    if result.returncode != 0:
        import re
        phase, kind = report.get('phase'), report.get('type')
        if phase in ('INPUT', 'INFO', 'MIGRATE', 'VALIDATE') and isinstance(kind, str) and re.fullmatch('[A-Z]{1,45}', kind):
            raise ValueError('SCHEMA_' + phase + '_' + kind)
        raise ValueError('SCHEMA_APPLY_STOPPED_KEEP_RECORDS_NO_RETRY')
    require(report == {'status': 'SCHEMA_PREPARED', 'migrations': 4}, 'SCHEMA_RESULT_UNEXPECTED')


if __name__ == '__main__':
    try:
        require(sys.argv[1:] == ['--read'], 'INITIAL_SCHEMA_MODE_REJECTED')
        print(json.dumps(read_metadata()))
    except Exception:
        raise SystemExit(1)
