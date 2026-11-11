"""Only fixed statement categories and numeric engine counters leave this reader."""
import time

STATUS=('Innodb_buffer_pool_read_requests','Innodb_buffer_pool_reads','Innodb_data_reads',
        'Innodb_data_writes','Innodb_rows_read','Innodb_rows_updated','Innodb_row_lock_current_waits')


def classify(query):
    query=' '.join((query or '').upper().split())
    if query.startswith('UPDATE PRODUCTS P JOIN JJIKMUK_CATALOG_BATCH'):return 'PRODUCT_UPDATE'
    if query.startswith('INSERT INTO PRODUCT_ATTRIBUTE_SNAPSHOTS'):return 'SNAPSHOT_INSERT'
    if query.startswith('SELECT COALESCE(MAX(ID),0)'):return 'SNAPSHOT_MAX'
    if query.startswith('SELECT') and 'FROM PRODUCTS WHERE PRODUCT_ID>' in query:return 'PRODUCT_SCAN'
    if query.startswith('SELECT COUNT(*) AS N FROM PRODUCTS P JOIN JJIKMUK_CATALOG_BATCH'):return 'BATCH_READBACK'
    if query.startswith('SELECT') and 'FROM PRODUCT_ATTRIBUTE_SNAPSHOTS WHERE ID IN' in query:return 'PRIOR_SNAPSHOT_READ'
    if query.startswith('INSERT INTO JJIKMUK_CATALOG_BATCH'):return 'BATCH_INSERT'
    if query.startswith('DELETE FROM JJIKMUK_CATALOG_BATCH'):return 'BATCH_DELETE'
    if query.startswith('SELECT') and 'FROM PRODUCT_ATTRIBUTE_SNAPSHOTS WHERE ID>' in query:return 'NEW_SNAPSHOT_READ'
    if query in ('COMMIT','ROLLBACK'):return 'TRANSACTION_END'
    return 'OTHER'


def explain_current(cur,connection_id,result):
    assert type(connection_id) is int and 0<connection_id<2**63
    try:
        cur.execute('EXPLAIN FOR CONNECTION '+str(connection_id))
        rows=cur.fetchall()
    except Exception:
        # The statement can end before EXPLAIN, or privileges may deny it.
        result['plan_unavailable']=result.get('plan_unavailable',0)+1
        return
    assert len(rows)<=20
    for row in rows:
        table=row.get('table');access=str(row.get('type','')).lower();estimate=row.get('rows')
        if table not in ('p','b','products','jjikmuk_catalog_batch') or access not in ('all','index','range','eq_ref','ref','const','system'):continue
        label='product' if table in ('p','products') else 'batch'
        key='plan_'+label+'_'+access;result[key]=result.get(key,0)+1
        if estimate is not None:
            estimate=int(estimate);assert 0<=estimate<2**63
            result['plan_'+label+'_max_rows']=max(result.get('plan_'+label+'_max_rows',0),estimate)


def collect(conn,sleep=time.sleep):
    result={};previous=None;explained=False
    with conn.cursor() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        for sample in range(5):
            cur.execute("SELECT ID,TIME,INFO FROM information_schema.PROCESSLIST WHERE USER=SUBSTRING_INDEX(CURRENT_USER(),'@',1) AND ID<>CONNECTION_ID() AND COMMAND<>'Sleep' LIMIT 20")
            for row in cur.fetchall():
                key=classify(row['INFO']);seconds=int(row['TIME']);assert 0<=seconds<2**63
                result['samples_'+key]=result.get('samples_'+key,0)+1
                result['seconds_'+key]=max(result.get('seconds_'+key,0),seconds)
                if key=='PRODUCT_UPDATE' and not explained:
                    explained=True;explain_current(cur,int(row['ID']),result)
            cur.execute('SHOW GLOBAL STATUS WHERE Variable_name IN ('+','.join(['%s']*len(STATUS))+')',STATUS)
            current={r['Variable_name']:int(r['Value']) for r in cur.fetchall() if r['Variable_name'] in STATUS}
            assert all(0<=v<2**63 for v in current.values())
            gauge=current.get('Innodb_row_lock_current_waits')
            if gauge is not None:result['max_row_lock_current_waits']=max(result.get('max_row_lock_current_waits',0),gauge)
            if previous is not None:
                for key,value in current.items():
                    if key!='Innodb_row_lock_current_waits' and key in previous and value>=previous[key]:result['delta_'+key]=result.get('delta_'+key,0)+value-previous[key]
            previous=current
            if sample<4:sleep(2)
        result['observations']=5
    conn.rollback()
    return result
