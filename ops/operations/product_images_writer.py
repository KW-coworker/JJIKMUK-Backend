"""Image-only bounded transactions, durable before-images, and no blind commit retry."""
import hashlib
import json
import sqlite3
import zlib

from product_image_patch import plain, require

FIELDS = ('image_url', 'product_group_key', 'attribute_snapshot_id')
ACTOR = 'USER_IMAGE_URLS_20261112'


def pack(value):
    return zlib.compress(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                    separators=(',', ':')).encode(), 1)


def unpack(value):
    return json.loads(zlib.decompress(value))


class Journal:
    def __init__(self, path, binding):
        fresh = not path.exists()
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA cache_size=-16384')
        if fresh:
            self.db.execute('CREATE TABLE binding(value TEXT NOT NULL)')
            self.db.execute('INSERT INTO binding VALUES(?)', (binding,))
            self.db.execute('CREATE TABLE batches(first_id INTEGER PRIMARY KEY,last_id INTEGER NOT NULL,'
                            'checked INTEGER NOT NULL,status TEXT NOT NULL,before_values BLOB NOT NULL,after_values BLOB,writer_session INTEGER NOT NULL)')
            self.db.commit()
        require(self.db.execute('SELECT value FROM binding').fetchall() == [(binding,)], 'IMAGES_JOURNAL_BINDING')

    def prepare(self, selected, before, writer_session):
        self.db.execute('INSERT INTO batches VALUES(?,?,?,?,?,NULL,?)',
                        (selected[0]['product_id'],selected[-1]['product_id'],len(selected),'PREPARED',pack(before),writer_session))
        self.db.commit()

    def intent(self, first, after):
        changed=self.db.execute("UPDATE batches SET after_values=?,status='COMMITTING' WHERE first_id=? AND status='PREPARED'", (pack(after),first))
        require(changed.rowcount == 1, 'IMAGES_JOURNAL_INTENT')
        self.db.commit()

    def finish(self, first, status='COMMITTED'):
        require(status in ('COMMITTED','ROLLED_BACK'), 'IMAGES_JOURNAL_STATUS')
        self.db.execute('UPDATE batches SET status=? WHERE first_id=?', (status,first)); self.db.commit()

    def close(self): self.db.close()


def rows_by_id(cur, ids, *, lock=False):
    require(0 < len(ids) <= 500 and len(set(ids)) == len(ids), 'IMAGES_ID_BOUND')
    cur.execute('SELECT * FROM products WHERE product_id IN ('+','.join(['%s']*len(ids))+') ORDER BY product_id'+
                (' FOR UPDATE' if lock else ''), ids)
    rows = [plain(r) for r in cur.fetchall()]
    require([r['product_id'] for r in rows] == sorted(ids), 'IMAGES_PRODUCT_ID_MISSING_OR_DUPLICATE')
    return rows


def previous(cur, rows):
    ids = sorted({r['attribute_snapshot_id'] for r in rows if r['attribute_snapshot_id'] is not None})
    if not ids: return {}
    cur.execute('SELECT id,product_id,payload_hash,payload_json FROM product_attribute_snapshots WHERE id IN ('+
                ','.join(['%s']*len(ids))+')', ids)
    found = {r['id']:r for r in cur.fetchall()}
    require(set(found)==set(ids), 'IMAGES_PREVIOUS_SNAPSHOT_MISSING')
    for row in rows:
        old = found.get(row['attribute_snapshot_id'])
        require(old is None or old['product_id']==row['product_id'] and
                hashlib.sha256(old['payload_json'].encode()).hexdigest()==old['payload_hash'], 'IMAGES_PREVIOUS_SNAPSHOT_INVALID')
    return found


def reconcile(connection_factory, journal):
    """Read uncertain batches first; a missing checkpoint never means rollback."""
    for first,last,checked,status,before_blob,after_blob,writer_session in journal.db.execute(
            "SELECT * FROM batches WHERE status NOT IN ('COMMITTED','ROLLED_BACK') ORDER BY first_id").fetchall():
        before = unpack(before_blob); after = unpack(after_blob) if after_blob else None
        if not before:
            require(after in (None, []), 'IMAGES_EMPTY_INTENT_UNCERTAIN')
            journal.finish(first, 'COMMITTED' if after == [] else 'ROLLED_BACK'); continue
        connection=connection_factory()
        require(connection.thread_id()!=writer_session,'IMAGES_RECONCILE_REQUIRES_NEW_CONNECTION')
        try:
            with connection.cursor() as cur:cur.execute('SET SESSION innodb_lock_wait_timeout=5,lock_wait_timeout=5')
            connection.begin()
            with connection.cursor() as cur:current=rows_by_id(cur,[r['product_id'] for r in before],lock=True)
            if current==before:journal.finish(first,'ROLLED_BACK')
            elif after is not None and current==after:journal.finish(first)
            else:raise ValueError('IMAGES_UNCERTAIN_COMMIT_CONFLICT')
            connection.rollback()  # Read-only transaction: release locks after classification.
        finally:connection.close()


class Writer:
    def __init__(self, connection, codec, journal, operation):
        require(len(operation)==64 and all(c in '0123456789abcdef' for c in operation), 'IMAGES_OPERATION')
        self.connection,self.codec,self.journal,self.operation=connection,codec,journal,operation

    def setup(self):
        with self.connection.cursor() as cur:
            cur.execute('SET SESSION innodb_lock_wait_timeout=5,lock_wait_timeout=5,MAX_EXECUTION_TIME=10000')
            cur.execute("SELECT INDEX_NAME,SEQ_IN_INDEX,COLUMN_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='products'")
            require(any(r['COLUMN_NAME']=='product_id' and r['SEQ_IN_INDEX']==1 for r in cur.fetchall()), 'IMAGES_PRODUCT_ID_INDEX_REQUIRED')
        self.connection.commit()

    def batch(self, selected):
        require(0<len(selected)<=500 and [r['product_id'] for r in selected]==sorted({r['product_id'] for r in selected}), 'IMAGES_BATCH_BOUND')
        first,last=selected[0]['product_id'],selected[-1]['product_id']
        existing=self.journal.db.execute('SELECT status FROM batches WHERE first_id=?',(first,)).fetchone()
        require(existing is None, 'IMAGES_BATCH_ALREADY_RECORDED')
        c=self.connection; commit_attempted=False
        try:
            with c.cursor() as cur:
                cur.execute('DROP TEMPORARY TABLE IF EXISTS jjikmuk_image_batch')
                cur.execute('CREATE TEMPORARY TABLE jjikmuk_image_batch (PRIMARY KEY(product_id)) ENGINE=InnoDB AS '
                            'SELECT product_id,barcode,image_url,product_group_key,attribute_snapshot_id FROM products WHERE 1=0')
            c.begin()
            with c.cursor() as cur:
                current=rows_by_id(cur,[r['product_id'] for r in selected],lock=True)
                before=[];wanted=[]
                for row,item in zip(current,selected):
                    if row['image_url']==item['image_url']:continue
                    require(all(row[k] is None for k in ('image_role','image_display_notice','image_asset_sha256','image_assignment_run')), 'IMAGES_EXISTING_ROLE_METADATA')
                    before.append(row);wanted.append(dict(row,image_url=item['image_url']))
                old=previous(cur,before)
                values=self.codec([{'row':r,'previous':old[r['attribute_snapshot_id']]['payload_json'] if r['attribute_snapshot_id'] is not None else None} for r in wanted]) if wanted else []
                require(len(values)==len(wanted),'IMAGES_CODEC_COUNT')
                for value in values:
                    require(hashlib.sha256(value['payload_json'].encode()).hexdigest()==value['payload_hash'] and
                            len(value['group_key'])==64,'IMAGES_CODEC_HASH')
                self.journal.prepare(selected,before,c.thread_id())
                if wanted:
                    dataset='image-urls-'+self.operation[:32]+'-'+str(first)
                    cur.executemany('INSERT INTO product_attribute_snapshots '
                        '(product_id,previous_snapshot_id,dataset_version,observed_at,observed_by,rule_version,change_reason,changed_fields,payload_hash,payload_json) '
                        'VALUES (%s,%s,%s,NOW(6),%s,%s,%s,%s,%s,%s)',
                        [(r['product_id'],r['attribute_snapshot_id'],dataset,ACTOR,'catalog-observation-v1',
                          'User supplied image URL list',v['changed_fields'],v['payload_hash'],v['payload_json']) for r,v in zip(wanted,values)])
                    ids=[r['product_id'] for r in wanted]
                    # The existing (product_id,id) index limits this to the selected products.
                    # Concurrent app observations for other products cannot contaminate this batch.
                    cur.execute('SELECT id,product_id,payload_hash FROM product_attribute_snapshots WHERE product_id IN ('+
                        ','.join(['%s']*len(ids))+') AND dataset_version=%s AND observed_by=%s', [*ids,dataset,ACTOR])
                    found=cur.fetchall();require(len(found)==len(wanted) and {r['product_id'] for r in found}==set(ids),'IMAGES_NEW_SNAPSHOT_IDENTITY')
                    mapping={r['product_id']:r for r in found}
                    for row,value in zip(wanted,values):
                        snap=mapping[row['product_id']];require(snap['payload_hash']==value['payload_hash'],'IMAGES_NEW_SNAPSHOT_HASH')
                        row.update(product_group_key=value['group_key'],attribute_snapshot_id=snap['id'])
                    cur.executemany('INSERT INTO jjikmuk_image_batch VALUES(%s,%s,%s,%s,%s)',
                                    [(r['product_id'],r['barcode'],*(r[k] for k in FIELDS)) for r in wanted])
                    cur.execute('UPDATE products p JOIN jjikmuk_image_batch b ON p.barcode=b.barcode AND p.product_id=b.product_id '
                                'SET p.image_url=b.image_url,p.product_group_key=b.product_group_key,p.attribute_snapshot_id=b.attribute_snapshot_id')
                    require(cur.rowcount==len(wanted),'IMAGES_UPDATED_COUNT')
                    require(rows_by_id(cur,ids)==wanted,'IMAGES_ALL_FIELDS_READBACK')
                self.journal.intent(first,wanted)
                commit_attempted=True;c.commit()
            if wanted:
                with c.cursor() as cur:require(rows_by_id(cur,[r['product_id'] for r in wanted])==wanted,'IMAGES_COMMITTED_READBACK')
                c.rollback()
            self.journal.finish(first)
            return {'checked':len(selected),'changed':len(wanted),'last_id':last}
        except BaseException:
            if not commit_attempted:
                try:c.rollback()
                except Exception:pass
            raise
