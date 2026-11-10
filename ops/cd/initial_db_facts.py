"""Private host-only schema/search facts for the approved maintenance."""
import hashlib
import json
from manifest import require


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def logical_extras(conn):
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


def quiescent(conn):
    with conn.cursor() as cur:
        # This also proves effective PROCESS access; observing only our own sessions is insufficient.
        cur.execute('SELECT COUNT(*) FROM information_schema.INNODB_TRX')
        transactions = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID<>CONNECTION_ID() AND (DB=%s OR DB IS NULL) AND USER NOT IN ('rdsadmin','event_scheduler','system user')", ('jjikmuk',))
        sessions = int(cur.fetchone()[0])
    require(transactions == 0 and sessions == 0, 'DATABASE_WRITERS_NOT_QUIESCENT')


def history_bound(conn):
    with conn.cursor() as cur:
        cur.execute('SELECT MAX(installed_rank),COUNT(*) FROM flyway_schema_history')
        rank, count = cur.fetchone()
    require(type(rank) is int and 17 <= rank <= 101 and count == 17, 'ORIGINAL_HISTORY_BOUND')
    return rank
