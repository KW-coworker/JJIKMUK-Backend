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
    if query in ('COMMIT','ROLLBACK'):return 'TRANSACTION_END'
    return 'OTHER'


def collect(conn,sleep=time.sleep):
    result={};previous=None
    with conn.cursor() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        for sample in range(5):
            cur.execute("SELECT TIME,INFO FROM information_schema.PROCESSLIST WHERE USER=SUBSTRING_INDEX(CURRENT_USER(),'@',1) AND ID<>CONNECTION_ID() AND COMMAND<>'Sleep' LIMIT 20")
            for row in cur.fetchall():
                key=classify(row['INFO']);seconds=int(row['TIME']);assert 0<=seconds<2**63
                result['samples_'+key]=result.get('samples_'+key,0)+1
                result['seconds_'+key]=max(result.get('seconds_'+key,0),seconds)
            cur.execute('SHOW GLOBAL STATUS WHERE Variable_name IN ('+','.join(['%s']*len(STATUS))+')',STATUS)
            current={r['Variable_name']:int(r['Value']) for r in cur.fetchall() if r['Variable_name'] in STATUS}
            assert all(0<=v<2**63 for v in current.values())
            if previous is not None:
                for key,value in current.items():
                    if key in previous and value>=previous[key]:result['delta_'+key]=result.get('delta_'+key,0)+value-previous[key]
            previous=current
            if sample<4:sleep(2)
        result['observations']=5
    conn.rollback()
    return result
