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

PROVENANCE_COLUMNS = {
    'content_revision_sha256':'char(64)', 'ingested_content_revision_sha256':'char(64)',
    'label_covered_fact_groups':'json', 'label_lineage_status':'varchar(16)',
    'label_observed_at':'datetime(6)', 'label_source_id':'varchar(128)',
    'label_source_record_id':'varchar(256)', 'label_source_type':'varchar(32)',
    'upstream_revision':'varchar(256)', 'upstream_updated_at':'datetime(6)'}


class FieldSummary:
    """Column stream hashes are comparable only with equal ordered product keys."""
    def __init__(self,columns):
        from catalog_compare import NON_IDENTITY, canonical, normalized, present
        self.fields=[(name,kind) for name,kind in columns if name not in NON_IDENTITY]
        encoder=json.JSONEncoder(ensure_ascii=False,separators=(',',':'),allow_nan=False)
        self.canonical=lambda value:encoder.encode(value).encode('utf-8')
        self.normalized=normalized
        self.hashes={name:hashlib.sha256() for name,_ in self.fields}
        self.nonnull={name:0 for name,_ in self.fields}
        self.keys=hashlib.sha256();self.rows=0
        self.present=present;self.images=0;self.bases=0
    def consume(self,row):
        need(type(row['product_id']) is int and row['product_id']>0 and
             isinstance(row['barcode'],str) and row['barcode'],'PRODUCT_KEY')
        self.keys.update(self.canonical([row['barcode'],row['product_id']])+b'\n')
        for name,kind in self.fields:
            value=self.normalized(row[name],kind)
            self.hashes[name].update(self.canonical(value)+b'\n')
            self.nonnull[name]+=value is not None
        self.rows+=1
        self.images+=self.present(row.get('image_url'))
        self.bases+=self.present(row.get('nutrition_basis_raw'))
    def finish(self):
        return {'counts':{'operating_rows':self.rows,'operating_image_filled':self.images,
                          'operating_basis_filled':self.bases,**{'nonnull.'+k:v for k,v in self.nonnull.items()}},
                'hashes':{'ordered_product_keys':self.keys.hexdigest(),
                          **{'field.'+k:v.hexdigest() for k,v in self.hashes.items()}}}


def field_differences(source,operating):
    need(source['counts']['operating_rows']==operating['counts']['operating_rows'] and
         source['hashes']['ordered_product_keys']==operating['hashes']['ordered_product_keys'],
         'FIELD_COMPARISON_KEYS_OR_ORDER_CHANGED')
    left={k:v for k,v in source['hashes'].items() if k.startswith('field.')}
    right={k:v for k,v in operating['hashes'].items() if k.startswith('field.')}
    need(set(left)==set(right),'FIELD_COMPARISON_COLUMNS_CHANGED')
    return sorted(k.removeprefix('field.') for k in left if left[k]!=right[k])


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
    wanted = {**dict(expected), **PROVENANCE_COLUMNS}
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


def compare_connection(conn, comparison, cursor_class, migrations, clock=time.monotonic, *, fields_only=False):
    from catalog_compare import IMAGE_META
    from manifest import require_database
    started = clock()
    cursor = None
    failed = False
    summary = FieldSummary(comparison.columns) if fields_only else None
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
        # Provenance is retained independently; only its binding presence is counted.
        compared = {name for name,_ in comparison.columns}
        selected = [name for name in actual if name in compared or name=='ingested_content_revision_sha256']
        bound_rows = basis_bound = image_bound = 0
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
                if summary is not None:
                    summary.consume(row)
                    bound_rows += row.get('ingested_content_revision_sha256') is not None
                    need(summary.rows<=2000000,'OPERATING_ROW_LIMIT')
                    continue
                before_basis = comparison.counts['basis_fill_candidate']
                before_image = (comparison.counts['image_fill_representative_candidate']+
                                comparison.counts['image_fill_category_candidate'])
                comparison.consume(row)
                if row.get('ingested_content_revision_sha256') is not None:
                    bound_rows += 1
                    basis_bound += comparison.counts['basis_fill_candidate']-before_basis
                    image_bound += (comparison.counts['image_fill_representative_candidate']+
                                    comparison.counts['image_fill_category_candidate']-before_image)
                need(comparison.counts['operating_rows'] <= 2000000, 'OPERATING_ROW_LIMIT')
        cursor.close(); cursor = None
        report = summary.finish() if summary is not None else comparison.finish()
        report['status'] = 'VERIFIED'
        report['counts'].update(image_columns_present=len(set(actual)&set(IMAGE_META)),
            fulltext_columns=sum(r[1]=='FULLTEXT' for r in indexes),
            successful_migrations=sum(r['type']=='SQL' for r in history),
            recognized_ai_columns=len(set(actual)&set(PROVENANCE_COLUMNS)),
            existing_ingestion_binding_rows=bound_rows,
            db_connections=1, db_writes=0, paid_ai_calls=0)
        if summary is None:
            report['counts'].update(basis_fill_with_ingestion_binding=basis_bound,
                                    image_fill_with_ingestion_binding=image_bound)
        report['hashes']['product_schema'] = hashlib.sha256(json.dumps([actual,indexes],sort_keys=True).encode()).hexdigest()
        report['checks'] = {'read_only_snapshot':True,'no_application_rows_exported':True,
            'existing_values_preserved_in_plan':True,
            'db_history_matches_installed_backend':True}
        report['checks']['per_column_fingerprints_only' if fields_only else 'exact_product_identity_required']=True
        report['checks']['existing_ai_columns_recognized']=True
        report['checks']['no_provenance_values_exported']=True
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
    purpose=config.get('purpose','compare');need(purpose in ('compare','fields'),'UNKNOWN_READ_PURPOSE')
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
        return compare_connection(conn,comparison,pymysql.cursors.SSCursor,config['migrations'],fields_only=purpose=='fields')
    finally:
        comparison.close()


if __name__ == '__main__':
    try:
        print(json.dumps(main()))
    except BaseException as error:
        code = str(error) if isinstance(error,ValueError) and re.fullmatch('[A-Z_]{1,70}',str(error)) else 'READONLY_COMPARISON_FAILED'
        print(json.dumps({'status':'STOPPED','codes':[code]}))
        raise SystemExit(1)
