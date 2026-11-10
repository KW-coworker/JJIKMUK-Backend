"""Read-only engine/index prerequisites for unchanged V17 INSTANT statements."""
import re
from readiness_probe import DB_HOST, CA, canonical, digest, need

TABLES = ('products', 'products_rollback', 'products_staging', 'users', 'family_profiles')


def summarize(version, tables, columns, indexes):
    need(len(tables) <= 5 and len(columns) <= 10 and len(indexes) <= 256, 'COMPATIBILITY_METADATA_LIMIT')
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)(?:\D|$)', version)
    need(match is not None, 'MYSQL_VERSION_FORMAT')
    report = {'status': 'OK', 'checks': {}, 'counts': {},
              'hashes': {'compatibility_metadata': digest(canonical([version, tables, columns, indexes]))},
              'codes': ['READ_ONLY_V17_COMPATIBILITY_NO_DDL']}
    report['counts'].update(dict(zip(('mysql_major', 'mysql_minor', 'mysql_patch'), map(int, match.groups()))))
    metadata = {r[0]: r for r in tables}
    for table in TABLES[:3]:
        row = metadata.get(table)
        fulltext = [r for r in indexes if r[0] == table and r[6] == 'FULLTEXT']
        report['checks'][table + '.present'] = row is not None
        report['checks'][table + '.fulltext_present'] = bool(fulltext)
        report['counts'][table + '.fulltext_columns'] = len(fulltext)
        # Absence of FULLTEXT alone is not a proof of all INSTANT row-size/version limits.
        report['checks'][table + '.known_instant_blocker'] = row is not None and (
            row[1] != 'InnoDB' or row[2] == 'Compressed' or bool(fulltext))
    for table in ('users', 'family_profiles'):
        rows = [r for r in columns if r[0] == table and r[1] == 'id']
        unique = {}
        for r in indexes:
            if r[0] == table and r[2] == 0:
                unique.setdefault(r[1], []).append(r)
        key = any(len(rows) == 1 and rows[0][3] == 1 and rows[0][4] == 'id' and rows[0][5] is None
                  for rows in unique.values())
        report['checks'][table + '.fk_parent_compatible'] = (len(rows) == 1 and rows[0][2:4] == ['bigint', 'NO']
            and key and metadata.get(table, [None, None])[1] == 'InnoDB')
    report['checks']['v17_blocked_by_existing_structure'] = any(
        report['checks'][t + '.known_instant_blocker'] for t in TABLES[:3])
    return report


def query(connect, props):
    with connect(host=DB_HOST, port=3306, database='jjikmuk', user=props['spring.datasource.username'],
        password=props['spring.datasource.password'], ssl_ca=CA, ssl_verify_cert=True, ssl_verify_identity=True,
        connect_timeout=5, read_timeout=10, write_timeout=5, autocommit=True, local_infile=False) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute('SET SESSION MAX_EXECUTION_TIME=10000')
                cur.execute('START TRANSACTION READ ONLY')
                cur.execute('SELECT VERSION()')
                version = cur.fetchone()[0]
                cur.execute('SELECT TABLE_NAME,ENGINE,ROW_FORMAT FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (%s,%s,%s,%s,%s) ORDER BY TABLE_NAME', ('jjikmuk', *TABLES))
                tables = [list(r) for r in cur.fetchmany(6)]
                cur.execute('SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (%s,%s) AND COLUMN_NAME=%s ORDER BY TABLE_NAME', ('jjikmuk', 'users', 'family_profiles', 'id'))
                columns = [list(r) for r in cur.fetchmany(11)]
                cur.execute('SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART,INDEX_TYPE FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN (%s,%s,%s,%s,%s) ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX LIMIT 257', ('jjikmuk', *TABLES))
                indexes = [list(r) for r in cur.fetchmany(257)]
                return summarize(version, tables, columns, indexes)
        finally:
            conn.rollback()
