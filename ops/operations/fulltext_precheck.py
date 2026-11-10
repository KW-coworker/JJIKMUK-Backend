"""Fixed maintenance prerequisites. No application rows, DDL or secret output."""
import re
from readiness_probe import DB_HOST, CA, canonical, digest, need

PRIVILEGES = ('SELECT', 'INSERT', 'UPDATE', 'CREATE', 'ALTER', 'INDEX', 'REFERENCES')
INDEX = 'ft_products_search_keywords'


def summarize(ddl, indexes, variables, tables, grants, sessions):
    need(isinstance(ddl, str) and len(ddl) < 65536 and len(indexes) <= 257
         and len(tables) <= 101 and len(grants) <= 101, 'MAINTENANCE_METADATA_LIMIT')
    expected = [[INDEX, 1, 'search_keywords', 'FULLTEXT']]
    fulltext = [list(r) for r in indexes if r[3] == 'FULLTEXT']
    # Parse only the approved index line, never return the table definition or grants.
    lines = [line.strip().rstrip(',') for line in ddl.splitlines() if 'FULLTEXT KEY' in line]
    index_definition = re.compile(r'FULLTEXT KEY `ft_products_search_keywords` \(`search_keywords`\) /\*!50100 WITH PARSER `ngram` \*/')
    effective = set()
    restricted = False
    for row in grants:
        statement = row[0]
        need(isinstance(statement, str) and len(statement) < 32768, 'GRANT_METADATA_LIMIT')
        restricted = restricted or statement.startswith('REVOKE ')
        match = re.fullmatch(r'GRANT (.+) ON (\*\.\*|`jjikmuk`\.\*) TO .+', statement)
        if match:
            names = set(match[1].split(', '))
            effective.update(PRIVILEGES if 'ALL PRIVILEGES' in names else names)
    if restricted:
        effective.clear()
    checks = {'fulltext_exact_columns': fulltext == expected,
              'fulltext_exact_ngram_definition': len(lines) == 1 and bool(index_definition.fullmatch(lines[0])),
              'ngram_token_size_two': variables[0] == 2,
              'file_per_table_enabled': variables[1] == 1,
              'mysql_version_8_4_11': variables[2] == '8.4.11',
              'fulltext_only_optimization_disabled': variables[3] == 0,
              'no_partial_revoke_observed': not restricted,
              'all_required_direct_schema_privileges': set(PRIVILEGES) <= effective}
    checks.update({'privilege_' + name.lower(): name in effective for name in PRIVILEGES})
    counts = {'visible_other_db_sessions': sessions, 'schema_tables': len(tables)}
    for table, data, index, free, estimated in tables:
        if table in ('products', 'products_rollback'):
            for suffix, value in (('data_bytes', data), ('index_bytes', index), ('data_free_bytes', free), ('estimated_rows', estimated)):
                counts[table + '_' + suffix] = int(value or 0)
    counts['schema_data_index_bytes'] = sum(int(r[1] or 0) + int(r[2] or 0) for r in tables)
    return {'status': 'OK', 'checks': checks, 'counts': counts,
            'hashes': {'products_ddl': digest(ddl.encode()), 'index_metadata': digest(canonical(indexes))},
            'codes': ['READ_ONLY_MAINTENANCE_PREREQUISITES', 'DATA_FREE_IS_NOT_RDS_FREE_STORAGE',
                      'DIRECT_PRIVILEGES_ONLY_NOT_ROLE_EXPANSION', 'SESSION_VISIBILITY_IS_NOT_QUIESCENCE_PROOF']}


def query(connect, props):
    with connect(host=DB_HOST, port=3306, database='jjikmuk', user=props['spring.datasource.username'],
        password=props['spring.datasource.password'], ssl_ca=CA, ssl_verify_cert=True, ssl_verify_identity=True,
        connect_timeout=5, read_timeout=10, write_timeout=5, autocommit=True, local_infile=False) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute('SET SESSION MAX_EXECUTION_TIME=10000')
                cur.execute('START TRANSACTION READ ONLY')
                cur.execute('SHOW CREATE TABLE `jjikmuk`.`products`')
                ddl = cur.fetchone()[1]
                cur.execute('SELECT INDEX_NAME,SEQ_IN_INDEX,COLUMN_NAME,INDEX_TYPE FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY INDEX_NAME,SEQ_IN_INDEX LIMIT 258', ('jjikmuk', 'products'))
                indexes = cur.fetchmany(258)
                cur.execute('SELECT @@ngram_token_size,@@innodb_file_per_table,VERSION(),@@innodb_optimize_fulltext_only')
                variables = cur.fetchone()
                cur.execute('SELECT TABLE_NAME,DATA_LENGTH,INDEX_LENGTH,DATA_FREE,TABLE_ROWS FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME LIMIT 102', ('jjikmuk',))
                tables = cur.fetchmany(102)
                cur.execute('SHOW GRANTS FOR CURRENT_USER')
                grants = cur.fetchmany(102)
                cur.execute('SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE DB=%s AND ID<>CONNECTION_ID()', ('jjikmuk',))
                sessions = int(cur.fetchone()[0])
                return summarize(ddl, indexes, variables, tables, grants, sessions)
        finally:
            conn.rollback()
