"""Bounded schema metadata for the initial backend release; never mutates SQL."""
import json

from readiness_probe import DB_HOST, CA, canonical, digest, need

TABLES = ('chat_conversations', 'chat_turns', 'account_analysis_selections',
          'account_analysis_selection_families')


def summarize(columns, indexes, history, contract):
    need(0 < len(columns) <= 4096 and len(indexes) <= 4096 and len(history) <= 101,
         'SCHEMA_METADATA_LIMIT')
    pairs = {(r[0], r[1]) for r in columns}
    present = {r[0] for r in columns}
    expected = {m['version']: [m['script'], m['checksum']] for m in contract['migrations']}
    need(set(expected) == {str(n) for n in range(1, 21)}, 'SCHEMA_CONTRACT_CHANGED')
    actual, valid, baselines = {}, bool(history), 0
    for version, script, checksum, success, kind in history:
        if kind == 'BASELINE':
            baselines += 1
            valid = valid and baselines == 1 and version == '0' and success == 1
            continue
        valid = valid and kind == 'SQL' and success == 1 and version not in actual
        actual[version] = [script, checksum]
    checks = {
        'deployment_ready': False,
        'history_valid': bool(valid),
        'history_exact_v1_through_v17': bool(valid and actual == {v: expected[v] for v in map(str, range(1, 18))}),
        'history_exact_v1_through_v20': bool(valid and actual == expected),
        'users.profile_version_present': ('users', 'profile_version') in pairs,
    }
    counts = {'db_columns': len(columns), 'db_indexes': len(indexes), 'db_history_rows': len(history),
              'database_connections': 1, 'database_mutations': 0, 'service_restarts': 0,
              'application_writes': 0, 'paid_ai_calls': 0}
    history_hashes = {}
    for table in TABLES:
        checks[table + '.present'] = table in present
    for version in ('18', '19', '20'):
        required = {tuple(p) for p in contract['required_columns'][version]}
        counts['v' + version + '.required_columns_missing'] = len(required - pairs)
        checks['v' + version + '.history_present'] = version in actual
        checks['v' + version + '.history_matches'] = actual.get(version) == expected[version]
    # Diagnose every historical version in the same bounded read. A single
    # overall match flag cannot distinguish a missing release from edited SQL.
    for version, (script, checksum) in expected.items():
        row = actual.get(version)
        checks['v' + version + '.history_present'] = row is not None
        checks['v' + version + '.script_matches'] = row is not None and row[0] == script
        checks['v' + version + '.checksum_matches'] = row is not None and row[1] == checksum
        if row is not None:
            need(type(row[0]) is str and len(row[0]) <= 1024, 'HISTORY_SCRIPT_LIMIT')
            history_hashes['v' + version + '.script'] = digest(row[0].encode())
            if type(row[1]) is int:
                need(-(2**31) <= row[1] < 2**31, 'HISTORY_CHECKSUM_RANGE')
                counts['v' + version + '.checksum_u32'] = row[1] & 0xffffffff
    counts['history_baselines'] = baselines
    counts['history_sql_versions'] = len(actual)
    counts['history_unknown_versions'] = len(set(actual) - set(expected))
    for table in ('products', 'products_staging', 'products_rollback'):
        checks[table + '.present'] = table in present
        checks[table + '.nutrition_basis_raw_present'] = (table, 'nutrition_basis_raw') in pairs
    checks['exact_unapplied_v18_v19_v20_shape'] = (
        checks['history_exact_v1_through_v17'] and
        not any(t in present for t in TABLES) and ('users', 'profile_version') not in pairs)
    return {'status': 'OK', 'checks': checks, 'counts': counts,
            'hashes': {'schema_metadata': digest(canonical([columns, indexes])),
                       'migration_history': digest(canonical(history)), **history_hashes},
            'codes': ['SCHEMA_METADATA_ONLY_NO_DATABASE_CHANGES']}


def query(connect, props, contract):
    with connect(host=DB_HOST, port=3306, database='jjikmuk', user=props['spring.datasource.username'],
                 password=props['spring.datasource.password'], ssl_ca=CA, ssl_verify_cert=True,
                 ssl_verify_identity=True, connect_timeout=5, read_timeout=10, write_timeout=5,
                 autocommit=True, local_infile=False) as conn:
        try:
            with conn.cursor() as cur:
                for sql in ('SET SESSION MAX_EXECUTION_TIME=10000', 'SET SESSION lock_wait_timeout=5',
                            'START TRANSACTION READ ONLY'):
                    cur.execute(sql)
                cur.execute('SELECT TABLE_NAME,COLUMN_NAME,ORDINAL_POSITION,COLUMN_TYPE,IS_NULLABLE,CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,ORDINAL_POSITION LIMIT 4097', ('jjikmuk',))
                columns = cur.fetchmany(4097)
                cur.execute('SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART,INDEX_TYPE FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX LIMIT 4097', ('jjikmuk',))
                indexes = cur.fetchmany(4097)
                history = []
                if any(r[0] == 'flyway_schema_history' for r in columns):
                    cur.execute('SELECT version,script,checksum,success,type FROM flyway_schema_history ORDER BY installed_rank LIMIT 102')
                    history = cur.fetchmany(102)
                return summarize(columns, indexes, history, contract)
        finally:
            conn.rollback()
