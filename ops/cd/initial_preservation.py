"""Frozen-DB data proof over original columns only; emits no row values.

The caller must quiesce writers, supply a live maintenance guard and keep this
result in the private host journal. This module performs no database writes.
"""
import hashlib
import re
import time
from manifest import require


def identifier(name):
    require(isinstance(name, str) and re.fullmatch('[a-z][a-z0-9_]{0,63}', name), 'PRESERVATION_IDENTIFIER')
    return '`' + name + '`'


def projection(metadata):
    result = {}
    for row in metadata['columns']:
        table, column = row[:2]
        identifier(table); identifier(column)
        result.setdefault(table, {'columns': [], 'primary_key': []})['columns'].append(column)
    require(0 < len(result) <= 101, 'PRESERVATION_TABLE_LIMIT')
    for row in metadata['indexes']:
        table, index, _, position, column = row[:5]
        if index == 'PRIMARY':
            require(table in result and column in result[table]['columns'], 'PRESERVATION_KEY')
            result[table]['primary_key'].append((position, column))
    for shape in result.values():
        require(0 < len(shape['columns']) <= 256 and shape['primary_key'], 'PRESERVATION_PRIMARY_KEY_REQUIRED')
        ordered = sorted(shape['primary_key'])
        require([n for n, _ in ordered] == list(range(1, len(ordered) + 1)), 'PRESERVATION_KEY_ORDER')
        shape['primary_key'] = [name for _, name in ordered]
    return result


def row_hash_sql(table, shape, history_rank):
    table_sql = identifier(table)
    columns = shape['columns']; keys = shape['primary_key']
    require(columns and keys and len(columns) == len(set(columns)) and set(keys) <= set(columns),
            'PRESERVATION_PROJECTION')
    # Fixed-width cell hashes distinguish NULL, empty, case and binary contents.
    # Values never leave MySQL; only per-row hashes traverse the TLS connection.
    cells = ["IF(" + identifier(c) + " IS NULL,'N',CONCAT('V',SHA2(CAST(" + identifier(c) + " AS BINARY),256)))"
             for c in columns]
    sql = 'SELECT SHA2(CONCAT(' + ','.join(cells) + '),256) FROM ' + table_sql
    parameters = ()
    if table == 'flyway_schema_history':
        require(type(history_rank) is int and 0 < history_rank <= 101 and 'installed_rank' in columns,
                'PRESERVATION_HISTORY_BOUND')
        sql += ' WHERE `installed_rank`<=%s'
        parameters = (history_rank,)
    sql += ' ORDER BY ' + ','.join(identifier(c) for c in keys)
    return sql, parameters


def capture(connection, original_projection, history_rank, guard, *, cursor_class, clock=time.monotonic):
    require(callable(guard), 'LIVE_MAINTENANCE_GUARD_REQUIRED')
    started = clock()
    result = {}
    try:
        with connection.cursor() as cur:
            cur.execute('SET SESSION MAX_EXECUTION_TIME=180000')
            cur.execute('START TRANSACTION READ ONLY')
        for table, shape in sorted(original_projection.items()):
            guard()
            require(clock() - started < 900, 'PRESERVATION_DEADLINE')
            sql, parameters = row_hash_sql(table, shape, history_rank)
            count, digest = 0, hashlib.sha256()
            with connection.cursor(cursor_class) as cur:
                cur.execute(sql, parameters)
                while True:
                    rows = cur.fetchmany(1024)
                    if not rows:
                        break
                    guard()
                    require(clock() - started < 900, 'PRESERVATION_DEADLINE')
                    for row in rows:
                        require(len(row) == 1 and isinstance(row[0], str)
                                and re.fullmatch('[a-f0-9]{64}', row[0]), 'PRESERVATION_ROW_DIGEST')
                        digest.update(row[0].encode('ascii'))
                    count += len(rows)
                    require(count <= 3_000_000, 'PRESERVATION_ROW_LIMIT')
            result[table] = {'rows': count, 'sha256': digest.hexdigest()}
        guard()
        return result
    finally:
        connection.rollback()


def verify(before, after):
    require(before and before == after, 'ORIGINAL_DATA_PRESERVATION_FAILED')
