"""One bounded product SELECT; no DDL/DML, user tables, migrations or paid calls.

Run as ubuntu with isolated system Python. Input configuration arrives through
stdin from the root-owned audit launcher; credentials never leave the host.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit


def need(ok, code):
    if not ok:
        raise ValueError(code)


def trusted(path):
    p = Path(path)
    for part in [p, *p.parents]:
        s = part.lstat()
        need(not part.is_symlink() and s.st_uid == 0 and not s.st_mode & 0o022, 'UNTRUSTED_PROBE_PATH')
    return p


def query_columns(conn, expected):
    with conn.cursor() as cur:
        cur.execute('SELECT COLUMN_NAME,COLUMN_TYPE FROM information_schema.COLUMNS '
                    'WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION LIMIT 101',
                    ('jjikmuk', 'products'))
        actual = dict(cur.fetchmany(101))
    from catalog_compare import IMAGE_META
    wanted = dict(expected)
    need(len(actual) <= 100 and set(actual) <= set(wanted) and
         set(wanted)-set(IMAGE_META) <= set(actual), 'PRODUCT_SCHEMA_CHANGED')
    need(all(actual[k] == wanted[k] for k in actual), 'PRODUCT_COLUMN_TYPE_CHANGED')
    present = set(actual) & set(IMAGE_META)
    need(len(present) in (0,4), 'PARTIAL_IMAGE_SCHEMA')
    return actual


def product_query(columns):
    need(0 < len(columns) <= 100 and all(re.fullmatch('[a-z][a-z0-9_]{0,63}', c) for c in columns),
         'INVALID_COLUMN_NAME')
    return ('SELECT /*+ MAX_EXECUTION_TIME(240000) */ '+','.join('`'+c+'`' for c in columns)+
            ' FROM `products` ORDER BY `barcode` LIMIT 2000001')


def retire(conn, cursor):
    # Do not drain an unfinished stream on error/timeout. Closing the connection
    # and MAX_EXECUTION_TIME bound the server query; never retry automatically.
    conn.close()
    if cursor is not None:
        cursor.connection = None
        result = getattr(cursor, '_result', None)
        if result is not None:
            result.unbuffered_active = False


def compare_connection(conn, comparison, cursor_class, migrations, clock=time.monotonic):
    from catalog_compare import IMAGE_META
    from manifest import require_database
    started = clock()
    cursor = None
    failed = False
    try:
        with conn.cursor() as cur:
            cur.execute('SET SESSION MAX_EXECUTION_TIME=240000')
            cur.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cur.execute('SET SESSION TRANSACTION READ ONLY')
            cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            cur.execute('SELECT DATABASE(),@@version,@@transaction_read_only,@@transaction_isolation')
            name, version, readonly, isolation = cur.fetchone()
            need(name == 'jjikmuk' and version.startswith('8.4.') and readonly == 1 and
                 isolation == 'REPEATABLE-READ', 'READONLY_DATABASE_IDENTITY')
            cur.execute('SELECT version,script,checksum,success,type FROM flyway_schema_history '
                        'ORDER BY installed_rank LIMIT 102')
            rows = cur.fetchmany(102)
            need(len(rows) <= 101, 'HISTORY_LIMIT')
            history = [dict(version=v,script=s,checksum=c,success=bool(ok),type=t)
                       for v,s,c,ok,t in rows]
            require_database({'migrations': migrations}, history)
            cur.execute('SELECT INDEX_NAME,INDEX_TYPE,SEQ_IN_INDEX,COLUMN_NAME '
                        'FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s '
                        'ORDER BY INDEX_NAME,SEQ_IN_INDEX LIMIT 101', ('jjikmuk','products'))
            indexes = cur.fetchmany(101)
            need(len(indexes) <= 100 and [(r[2],r[3]) for r in indexes if r[0]=='PRIMARY'] == [(1,'barcode')],
                 'PRODUCT_PRIMARY_KEY_CHANGED')
        actual = query_columns(conn, comparison.columns)
        selected = list(actual)
        cursor = conn.cursor(cursor_class)
        cursor.execute(product_query(selected))
        while True:
            need(clock()-started < 480, 'COMPARISON_DEADLINE')
            rows = cursor.fetchmany(512)
            if not rows:
                break
            for value in rows:
                row = dict(zip(selected,value))
                for name in IMAGE_META:
                    row.setdefault(name,None)
                comparison.consume(row)
                need(comparison.counts['operating_rows'] <= 2000000, 'OPERATING_ROW_LIMIT')
        cursor.close(); cursor = None
        report = comparison.finish()
        report['status'] = 'VERIFIED'
        report['counts'].update(image_columns_present=len(set(actual)&set(IMAGE_META)),
            fulltext_columns=sum(r[1]=='FULLTEXT' for r in indexes),
            successful_migrations=sum(r['type']=='SQL' for r in history),
            db_connections=1, db_writes=0, paid_ai_calls=0)
        report['hashes']['product_schema'] = hashlib.sha256(json.dumps([actual,indexes],sort_keys=True).encode()).hexdigest()
        report['checks'] = {'read_only_snapshot':True,'no_application_rows_exported':True,
            'exact_product_identity_required':True,'existing_values_preserved_in_plan':True,
            'db_history_matches_installed_backend':True}
        conn.rollback()
        return report
    except BaseException:
        failed = True
        retire(conn,cursor)
        raise
    finally:
        if not failed:
            conn.close()


def main():
    need(os.geteuid() != 0 and sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,
         'UNPRIVILEGED_ISOLATED_PROBE_REQUIRED')
    stage = trusted(Path(__file__).resolve().parent)
    raw = sys.stdin.buffer.read(65537)
    need(len(raw)<=65536, 'INPUT_LIMIT')
    config = json.loads(raw)
    source = trusted(stage/'source-fingerprints.sqlite')
    digest = hashlib.sha256()
    with source.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            digest.update(block)
    need(digest.hexdigest() == config['source_sha256'], 'SOURCE_FINGERPRINT_HASH')
    sys.path[:0] = [str(stage), str(trusted('/opt/jjikmuk-cd/bin'))]
    import database_probe
    database_probe.load_vendor()
    import pymysql
    from catalog_compare import Comparison, SQL_SHA, SOURCE_ROWS
    db = config['database']
    need(db['host']=='jjikmuk-dev-db.cp22o82i4ex5.ap-northeast-2.rds.amazonaws.com' and db['name']=='jjikmuk'
         and db['properties_file']=='/home/ubuntu/JJIKMUK-Backend/application-local.properties'
         and db['ca_file']=='/opt/food-chatbot/rds-global-bundle.pem', 'FIXED_DATABASE_TARGET')
    props = database_probe.properties(db['properties_file'])
    need(props['spring.datasource.url']==db['expected_jdbc_url'], 'DATABASE_URL_CHANGED')
    target = urlsplit(db['expected_jdbc_url'].removeprefix('jdbc:'))
    need(db['expected_jdbc_url'].startswith('jdbc:mysql://') and target.hostname==db['host'] and
         (target.port or 3306)==3306 and target.path=='/jjikmuk' and not target.username and not target.password,
         'DATABASE_URL_TARGET')
    comparison = Comparison(source)
    try:
        need(comparison.meta['sql_sha256']==SQL_SHA and
             comparison.meta['counts']['source_rows']==SOURCE_ROWS, 'SOURCE_BINDING')
        conn = pymysql.connect(host=db['host'],port=3306,database='jjikmuk',
            user=props['spring.datasource.username'],password=props['spring.datasource.password'],
            ssl_ca=db['ca_file'],ssl_verify_cert=True,ssl_verify_identity=True,
            connect_timeout=5,read_timeout=30,write_timeout=5,autocommit=True,charset='utf8mb4')
        return compare_connection(conn,comparison,pymysql.cursors.SSCursor,config['migrations'])
    finally:
        comparison.close()


if __name__ == '__main__':
    try:
        print(json.dumps(main()))
    except BaseException as error:
        code = str(error) if isinstance(error,ValueError) and re.fullmatch('[A-Z_]{1,70}',str(error)) else 'READONLY_COMPARISON_FAILED'
        print(json.dumps({'status':'STOPPED','codes':[code]}))
        raise SystemExit(1)
