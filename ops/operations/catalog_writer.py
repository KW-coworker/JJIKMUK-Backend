"""Bounded product changes with a durable before-image and append-only observations.

Connections, source binding, service freeze, backup, storage guard and the pure
Kotlin codec are supplied by the maintenance host. This module never reconnects
or retries writes after an uncertain commit.
"""
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from catalog_delta import VALUES, changes, canonical, normalized, need

MUTABLE = (*VALUES, 'product_group_key')
ACTOR = 'APPROVED_HANDOFF_20261111'
RULE = 'catalog-observation-v1'


def plain(row):
    return {k: int.from_bytes(v, 'big') if isinstance(v, bytes) else v for k, v in row.items()}


def saved_values(row):
    return {name: row[name] for name in MUTABLE}


def baseline_hash(row):
    return hashlib.sha256(canonical([row['product_id'],row['barcode'],
        [row.get(name) for name in (*MUTABLE,'attribute_snapshot_id')]])).digest()


class Journal:
    def __init__(self, path, binding, *, recover=False):
        self.path = Path(path)
        if not recover:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        need(self.path.is_file() and not self.path.is_symlink(), 'CATALOG_JOURNAL_PATH')
        self.db = sqlite3.connect(self.path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA cache_size=-32768')
        if not recover:
            self.db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            self.db.execute('CREATE TABLE baseline(product_id INTEGER PRIMARY KEY,digest BLOB NOT NULL)')
            self.db.execute('CREATE TABLE changes(product_id INTEGER PRIMARY KEY,barcode TEXT NOT NULL, '
                'old_values TEXT NOT NULL,new_values TEXT NOT NULL,previous_id INTEGER, '
                'new_payload_hash TEXT NOT NULL,status TEXT NOT NULL)')
            self.db.execute('INSERT INTO metadata VALUES (?,?)', ('binding', canonical(binding).decode()))
            self.db.commit()
            fd = os.open(self.path.parent, os.O_RDONLY) if os.name == 'posix' else None
            if fd is not None:
                try: os.fsync(fd)
                finally: os.close(fd)
        need(json.loads(self.db.execute('SELECT value FROM metadata WHERE key=?', ('binding',)).fetchone()[0]) == binding,
             'CATALOG_JOURNAL_BINDING')

    def prepare(self, rows):
        self.db.executemany('INSERT INTO changes VALUES (?,?,?,?,?,?,?)', rows)
        self.db.commit()  # FULL rollback-journal fsync finishes BEFORE MySQL writes.

    def baseline(self, rows):
        self.db.executemany('INSERT INTO baseline VALUES (?,?)',[(r['product_id'],baseline_hash(r)) for r in rows])
        self.db.commit()

    def require_baseline(self,row):
        found=self.db.execute('SELECT digest FROM baseline WHERE product_id=?',(row['product_id'],)).fetchone()
        need(found is not None and found[0]==baseline_hash(row),'CATALOG_BEFORE_VALUES_CHANGED')

    def mark(self, ids, status):
        self.db.executemany('UPDATE changes SET status=? WHERE product_id=?', [(status, i) for i in ids])
        self.db.commit()

    def close(self): self.db.close()


class Writer:
    def __init__(self, connection, source, codec, journal, dataset, guard,progress=lambda *args:None):
        need(re.fullmatch(r'catalog-handoff-[a-f0-9]{32}', dataset), 'CATALOG_DATASET')
        self.connection, self.source, self.codec = connection, source, codec
        self.journal, self.dataset, self.guard = journal, dataset, guard
        self.counts = collections.Counter()
        self.progress=progress
        self.fields = [n for n, _ in source.columns]
        need(len(self.fields) == 54 and all(re.fullmatch('[a-z][a-z0-9_]{0,63}', n) for n in self.fields), 'CATALOG_SOURCE_COLUMNS')

    def setup(self):
        with self.connection.cursor() as cur:
            cur.execute('SET SESSION innodb_lock_wait_timeout=10,lock_wait_timeout=10,MAX_EXECUTION_TIME=120000')
            cur.execute('SELECT COUNT(*) AS n FROM product_attribute_snapshots WHERE dataset_version IN (%s,%s)',
                        (self.dataset, self.dataset+'-rollback'))
            need(cur.fetchone()['n'] == 0, 'CATALOG_DATASET_ALREADY_PRESENT')
            columns = ','.join('`'+k+'`' for k in ('product_id','barcode',*MUTABLE,'attribute_snapshot_id'))
            cur.execute('CREATE TEMPORARY TABLE jjikmuk_catalog_batch ENGINE=InnoDB AS SELECT '+columns+' FROM products WHERE 1=0')
            cur.execute('ALTER TABLE jjikmuk_catalog_batch ADD PRIMARY KEY(product_id)')
        self.connection.commit()

    def previous(self, cur, rows):
        ids = sorted({r['attribute_snapshot_id'] for r in rows if r['attribute_snapshot_id'] is not None})
        if not ids: return {}
        cur.execute('SELECT id,product_id,payload_hash,payload_json,previous_snapshot_id,dataset_version,observed_by FROM product_attribute_snapshots WHERE id IN ('+
                    ','.join(['%s']*len(ids))+')', ids)
        found = {r['id']:r for r in cur.fetchall()}
        need(set(found)==set(ids), 'CATALOG_PRIOR_SNAPSHOT_MISSING')
        for row in rows:
            prior = found.get(row['attribute_snapshot_id'])
            need(prior is None or prior['product_id']==row['product_id'], 'CATALOG_PRIOR_SNAPSHOT_IDENTITY')
            if prior:
                need(hashlib.sha256(prior['payload_json'].encode()).hexdigest()==prior['payload_hash'],
                     'CATALOG_PRIOR_SNAPSHOT_HASH')
        return found

    def write_batch(self, cur, rows, encoded, dataset, reason):
        need(0 < len(rows) <= 500 and len(rows)==len(encoded), 'CATALOG_BATCH_BOUND')
        cur.execute('SELECT NOW(6) AS observed_at')
        observed_at=cur.fetchone()['observed_at']
        cur.execute('SELECT COALESCE(MAX(id),0) AS n FROM product_attribute_snapshots')
        previous_max=cur.fetchone()['n']
        inserts = [(r['product_id'],r['attribute_snapshot_id'],dataset,observed_at,ACTOR,RULE,reason,
                    e['changed_fields'],e['payload_hash'],e['payload_json']) for r,e in zip(rows,encoded)]
        cur.executemany('INSERT INTO product_attribute_snapshots '
            '(product_id,previous_snapshot_id,dataset_version,observed_at,observed_by,rule_version,change_reason,changed_fields,payload_hash,payload_json) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', inserts)
        ids = [r['product_id'] for r in rows]
        cur.execute('SELECT id,product_id,payload_hash,dataset_version,observed_by FROM product_attribute_snapshots '
                    'WHERE id>%s ORDER BY id LIMIT 501', (previous_max,))
        snapshots = cur.fetchall()
        need(len(snapshots)==len(rows) and {r['product_id'] for r in snapshots}==set(ids) and
             all(r['dataset_version']==dataset and r['observed_by']==ACTOR for r in snapshots), 'CATALOG_NEW_SNAPSHOT_IDENTITY')
        mapping = {r['product_id']:r for r in snapshots}
        columns = ('product_id','barcode',*MUTABLE,'attribute_snapshot_id')
        values = []
        for row, item in zip(rows, encoded):
            snapshot = mapping[row['product_id']]
            need(snapshot['payload_hash']==item['payload_hash'], 'CATALOG_NEW_SNAPSHOT_HASH')
            row = dict(row, product_group_key=item['group_key'], attribute_snapshot_id=snapshot['id'])
            values.append(tuple(row[k] for k in columns))
        cur.execute('DELETE FROM jjikmuk_catalog_batch')
        cur.executemany('INSERT INTO jjikmuk_catalog_batch ('+','.join('`'+k+'`' for k in columns)+
                        ') VALUES ('+','.join(['%s']*len(columns))+')', values)
        cur.execute('UPDATE products p JOIN jjikmuk_catalog_batch b ON p.product_id=b.product_id AND p.barcode=b.barcode SET '+
                    ','.join('p.`'+k+'`=b.`'+k+'`' for k in (*MUTABLE,'attribute_snapshot_id')))
        need(cur.rowcount==len(rows), 'CATALOG_PRODUCT_UPDATE_COUNT')
        cur.execute('SELECT COUNT(*) AS n FROM products p JOIN jjikmuk_catalog_batch b ON p.product_id=b.product_id '
                    'AND BINARY p.barcode=BINARY b.barcode WHERE '+
                    ' AND '.join('BINARY p.`'+k+'` <=> BINARY b.`'+k+'`' for k in (*MUTABLE,'attribute_snapshot_id')))
        need(cur.fetchone()['n']==len(rows), 'CATALOG_BATCH_READBACK')

    def run(self):
        self.setup()
        after = 0
        while True:
            self.guard()
            self.connection.begin()
            try:
                with self.connection.cursor() as cur:
                    cur.execute('SELECT '+','.join('`'+x+'`' for x in self.fields)+
                        ' FROM products WHERE product_id>%s ORDER BY product_id LIMIT 500 FOR UPDATE', (after,))
                    rows = [plain(r) for r in cur.fetchall()]
                    if not rows:
                        self.connection.rollback(); break
                    need(len({r['product_id'] for r in rows})==len(rows), 'CATALOG_PRODUCT_IDS')
                    modified = []
                    old_rows = []
                    for row in rows:
                        self.journal.require_baseline(row)
                        delta = changes(row, self.source.get(row['barcode']), self.source.columns)
                        if delta:
                            modified.append(dict(row, **delta)); old_rows.append(row)
                            self.counts.update(delta.keys())
                    prior = self.previous(cur, old_rows)
                    if modified:
                        payloads = self.codec([{'row':r, 'previous':prior[r['attribute_snapshot_id']]['payload_json']
                            if r['attribute_snapshot_id'] is not None else None} for r in modified])
                        prepared = []
                        for old,new,payload in zip(old_rows,modified,payloads):
                            if old['image_url']==new['image_url']:
                                payload['group_key']=old['product_group_key']
                            new['product_group_key'] = payload['group_key']
                            prepared.append((old['product_id'],old['barcode'],canonical(saved_values(old)).decode(),
                                canonical(saved_values(new)).decode(),old['attribute_snapshot_id'],payload['payload_hash'],'PREPARED'))
                        self.journal.prepare(prepared)
                        self.guard()
                        self.write_batch(cur,modified,payloads,self.dataset,'Apply owner-supplied 2026-11-09 product handoff')
                    self.guard()
                    self.connection.commit()
                    if modified:self.journal.mark([r['product_id'] for r in modified], 'COMMITTED')
                    self.counts['scanned'] += len(rows)
                    self.counts['changed'] += len(modified)
                    need(self.counts['scanned'] <= self.source.meta['source_rows'], 'CATALOG_ROW_BOUND')
                    after = rows[-1]['product_id']
                    self.progress('PRODUCT_APPLY',self.counts['scanned'],self.source.meta['source_rows'])
            except BaseException:
                try:self.connection.rollback()
                except Exception:self.connection.close()
                raise
        need(self.counts['scanned']==self.source.meta['source_rows'], 'CATALOG_PRODUCT_COUNT')
        return dict(self.counts)

    def recover(self):
        """Observe every uncertain batch; never infer commit success from a local flag."""
        with self.connection.cursor() as cur:
            columns = ','.join('`'+k+'`' for k in ('product_id','barcode',*MUTABLE,'attribute_snapshot_id'))
            cur.execute('CREATE TEMPORARY TABLE jjikmuk_catalog_batch ENGINE=InnoDB AS SELECT '+columns+' FROM products WHERE 1=0')
            cur.execute('ALTER TABLE jjikmuk_catalog_batch ADD PRIMARY KEY(product_id)')
        self.connection.commit()
        after = 0
        restored = unchanged = 0
        while True:
            records = self.journal.db.execute('SELECT * FROM changes WHERE product_id>? ORDER BY product_id LIMIT 500', (after,)).fetchall()
            if not records: break
            self.guard()
            self.connection.begin()
            try:
                with self.connection.cursor() as cur:
                    ids=[r[0] for r in records]
                    cur.execute('SELECT '+','.join('`'+x+'`' for x in self.fields)+' FROM products WHERE product_id IN ('+
                                ','.join(['%s']*len(ids))+') ORDER BY product_id FOR UPDATE',ids)
                    rows = [plain(r) for r in cur.fetchall()]
                    need([r['product_id'] for r in rows]==ids, 'CATALOG_RECOVERY_PRODUCTS')
                    prior=self.previous(cur,rows)
                    wanted=[];already_returned=[]
                    for row,record in zip(rows,records):
                        product_id,barcode,old_json,new_json,previous_id,new_hash,_=record
                        old,new=json.loads(old_json),json.loads(new_json)
                        need(row['barcode']==barcode,'CATALOG_RECOVERY_BARCODE')
                        # Immutable 42 fields must still identify the owner-supplied product.
                        from catalog_delta import identity
                        need(identity(row,self.source.columns)==self.source.get(barcode)['identity_hash'], 'CATALOG_RECOVERY_IDENTITY')
                        current=saved_values(row)
                        snapshot=prior.get(row['attribute_snapshot_id'])
                        if current==old and row['attribute_snapshot_id']==previous_id:
                            unchanged+=1; continue
                        need(snapshot is not None,'CATALOG_RECOVERY_POINTER')
                        history=snapshot
                        if current==old and history['dataset_version']==self.dataset+'-rollback' and history['observed_by']==ACTOR:
                            already_returned.append((row,record,snapshot));continue
                        need(current==new and snapshot['payload_hash']==new_hash and
                             history['previous_snapshot_id']==previous_id and history['dataset_version']==self.dataset and
                             history['observed_by']==ACTOR, 'CATALOG_RECOVERY_DRIFT')
                        self.journal.require_baseline(dict(row,**old,attribute_snapshot_id=previous_id))
                        wanted.append(dict(row,**old))
                    if already_returned:
                        encoded=self.codec([{'row':r,'previous':None} for r,_,_ in already_returned])
                        parent_rows=[dict(r,attribute_snapshot_id=s['previous_snapshot_id']) for r,_,s in already_returned]
                        parents=self.previous(cur,parent_rows)
                        for (row,record,snapshot),payload in zip(already_returned,encoded):
                            parent=parents.get(snapshot['previous_snapshot_id'])
                            need(snapshot['payload_json']==payload['payload_json'] and snapshot['payload_hash']==payload['payload_hash'] and
                                 parent is not None and parent['dataset_version']==self.dataset and parent['observed_by']==ACTOR and
                                 parent['payload_hash']==record[5] and parent['previous_snapshot_id']==record[4],
                                 'CATALOG_RECOVERY_OBSERVATION_CHAIN')
                            self.journal.require_baseline(dict(row,attribute_snapshot_id=record[4]))
                        restored+=len(already_returned)
                    if wanted:
                        payloads=self.codec([{'row':r,'previous':prior[r['attribute_snapshot_id']]['payload_json']} for r in wanted])
                        # Restore the exact historical group key, including a legacy null.
                        for row,payload in zip(wanted,payloads):payload['group_key']=row['product_group_key']
                        self.guard()
                        self.write_batch(cur,wanted,payloads,self.dataset+'-rollback','Restore pre-handoff values; retain all observations')
                    self.guard();self.connection.commit()
                    self.journal.mark(ids,'RESTORED_OR_NOT_COMMITTED')
                    restored+=len(wanted);after=ids[-1]
                    self.progress('RECOVERY',restored+unchanged,None)
            except BaseException:
                try:self.connection.rollback()
                except Exception:self.connection.close()
                raise
        return {'restored':restored,'never_committed':unchanged}
