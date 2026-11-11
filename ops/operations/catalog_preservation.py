"""Preserve original tables and all non-target product fields; values stay private."""
import hashlib
import re
import time
from catalog_delta import need
from catalog_writer import MUTABLE
from initial_preservation import projection, row_hash_sql


def capture(conn, metadata, bounds, guard, cursor_class,progress=lambda *args:None):
    shapes=projection(metadata)
    shapes['products']['columns']=[n for n in shapes['products']['columns'] if n not in (*MUTABLE,'attribute_snapshot_id')]
    result={};started=time.monotonic()
    try:
        with conn.cursor() as cur:
            cur.execute('SET SESSION MAX_EXECUTION_TIME=300000')
            cur.execute('START TRANSACTION READ ONLY')
        for table,shape in sorted(shapes.items()):
            guard();need(time.monotonic()-started<900,'CATALOG_PRESERVATION_DEADLINE')
            sql,params=row_hash_sql(table,shape,bounds['history_rank'])
            if table=='product_attribute_snapshots':
                sql=sql.replace(' ORDER BY ',' WHERE `id`<=%s ORDER BY ')
                params=(bounds['snapshot_id'],)
            cur=conn.cursor(cursor_class);count=0;digest=hashlib.sha256()
            try:
                cur.execute(sql,params)
                while rows:=cur.fetchmany(2048):
                    guard();need(time.monotonic()-started<900,'CATALOG_PRESERVATION_DEADLINE')
                    for row in rows:
                        need(len(row)==1 and re.fullmatch('[a-f0-9]{64}',row[0]),'CATALOG_PRESERVATION_ROW')
                        digest.update(row[0].encode('ascii'))
                    count+=len(rows);need(count<=3_000_000,'CATALOG_PRESERVATION_ROW_BOUND')
            except BaseException:
                conn.close();cur.connection=None
                if getattr(cur,'_result',None) is not None:cur._result.unbuffered_active=False
                raise
            else:cur.close()
            result[table]={'rows':count,'sha256':digest.hexdigest()}
            progress('PRESERVATION',len(result),len(shapes))
        return result
    finally:
        if conn.open:conn.rollback()
