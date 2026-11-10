"""Private host-only schema/search facts for the approved maintenance."""
import hashlib
import json
import re
import time
from manifest import require


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def require_observation_privileges(conn):
    """Require complete trigger/event visibility in this project's schema."""
    with conn.cursor() as cur:
        cur.execute('SELECT CURRENT_ROLE()')
        role = cur.fetchone()[0]
        if role == 'NONE':
            cur.execute('SHOW GRANTS FOR CURRENT_USER')
        else:
            require(role == '`rds_superuser_role`@`%`', 'UNREVIEWED_ACTIVE_DB_ROLE')
            cur.execute('SHOW GRANTS FOR CURRENT_USER USING `rds_superuser_role`@`%`')
        rows = cur.fetchmany(102)
    require(len(rows) <= 101 and not any(row[0].startswith('REVOKE ') for row in rows),
            'DB_METADATA_PRIVILEGES_RESTRICTED')
    project_rights = set()
    for row in rows:
        match = re.fullmatch(r'GRANT (.+) ON (\*\.\*|`jjikmuk`\.\*) TO .+', row[0])
        if match:
            names = set(match[1].split(', '))
            project_rights.update({'TRIGGER','EVENT'} if 'ALL PRIVILEGES' in names else names)
    require({'TRIGGER','EVENT'} <= project_rights, 'PROJECT_METADATA_VISIBILITY_NOT_PROVEN')


def project_events_clear(conn):
    require_observation_privileges(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA=%s AND STATUS='ENABLED'", ('jjikmuk',))
        require(int(cur.fetchone()[0]) == 0, 'PROJECT_SCHEDULED_EVENT_PRESENT')


def logical_extras(conn):
    require_observation_privileges(conn)
    with conn.cursor() as cur:
        cur.execute('SELECT TABLE_NAME,TABLE_COLLATION,TABLE_COMMENT,CREATE_OPTIONS,AUTO_INCREMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME LIMIT 102', ('jjikmuk',))
        tables = cur.fetchmany(102)
        cur.execute('SELECT TABLE_NAME,COLUMN_NAME,CHARACTER_SET_NAME,COLLATION_NAME,GENERATION_EXPRESSION,COLUMN_COMMENT FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,ORDINAL_POSITION LIMIT 4097', ('jjikmuk',))
        columns = cur.fetchmany(4097)
        cur.execute('SELECT TRIGGER_NAME,EVENT_MANIPULATION,ACTION_TIMING,EVENT_OBJECT_TABLE,ACTION_STATEMENT FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s ORDER BY TRIGGER_NAME LIMIT 102', ('jjikmuk',))
        triggers = cur.fetchmany(102)
    require(len(tables) <= 101 and len(columns) <= 4096 and len(triggers) <= 101, 'MAINTENANCE_FACT_LIMIT')
    return json.loads(canonical({'tables': tables, 'columns': columns,
                                'triggers_sha256': hashlib.sha256(canonical(triggers)).hexdigest()}))


def verify_logical(before, after):
    tables = {r[0]: r for r in after['tables']}
    columns = {(r[0], r[1]): r for r in after['columns']}
    require(all(tables.get(r[0]) == r for r in before['tables']), 'EXISTING_TABLE_OPTIONS_CHANGED')
    require(all(columns.get((r[0], r[1])) == r for r in before['columns']), 'EXISTING_COLUMN_ATTRIBUTES_CHANGED')
    require(before['triggers_sha256'] == after['triggers_sha256'], 'EXISTING_TRIGGER_CHANGED')


def fulltext_definition(conn):
    from fulltext_definition import summarize
    with conn.cursor() as cur:
        cur.execute('SHOW CREATE TABLE `jjikmuk`.`products`')
        result = summarize(cur.fetchone()[1])
    require(result['checks']['normalized_exact_ngram_definition'], 'EXACT_FULLTEXT_DEFINITION_REQUIRED')
    return result['hashes']['index_line']


def search_fingerprint(conn):
    result = {}
    with conn.cursor() as cur:
        cur.execute('SET SESSION MAX_EXECUTION_TIME=10000')
        for term in ('조리퐁', '새우깡', '오레오', '단백질칩', 'OREO', '딸기우유'):
            cur.execute('SELECT barcode FROM products WHERE MATCH(search_keywords) AGAINST (%s IN BOOLEAN MODE) ORDER BY barcode LIMIT 50', (term,))
            rows = cur.fetchall()
            result[term] = {'rows': len(rows), 'sha256': hashlib.sha256(canonical(rows)).hexdigest()}
    require(any(x['rows'] for x in result.values()), 'SEARCH_BASELINE_EMPTY')
    return result


def project_idle(conn, *, guard=lambda:None, timeout=30):
    """Known apps must already be stopped; the owner confirmed no other operators.

    This observes our own DB account and project events, not global quiescence.
    Unexpected writes from outside that operating contract are detected by the
    existing pre/post preservation checks; these checks are not a write lock.
    """
    require(0 <= timeout <= 30, 'PROJECT_DRAIN_TIMEOUT_INVALID')
    deadline = time.monotonic() + timeout
    while True:
        guard()
        project_events_clear(conn)
        with conn.cursor() as cur:
            # Same-account sessions are visible without PROCESS. Do not filter
            # by default DB: qualified jjikmuk writes can use another default.
            cur.execute('SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID<>CONNECTION_ID() AND USER=SUBSTRING_INDEX(CURRENT_USER(),%s,1)', ('@',))
            sessions = int(cur.fetchone()[0])
        if sessions == 0:return
        require(time.monotonic() < deadline, 'PROJECT_ACCOUNT_CONNECTIONS_REMAIN')
        time.sleep(1)


def history_bound(conn):
    with conn.cursor() as cur:
        cur.execute('SELECT MAX(installed_rank),COUNT(*) FROM flyway_schema_history')
        rank, count = cur.fetchone()
    require(type(rank) is int and 17 <= rank <= 101 and count == 17, 'ORIGINAL_HISTORY_BOUND')
    return rank
