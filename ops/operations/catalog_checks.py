"""Exact additive image schema and owner-source postconditions."""
import hashlib
import json
from catalog_delta import IMAGE_META, VALUES, changes, need


def manifests(previous, candidate, sql_sha):
    before={r['version']:r for r in previous['migrations']}
    after={r['version']:r for r in candidate['migrations']}
    need(set(before)=={str(i) for i in range(1,21)} and set(after)==set(before)|{'21'},'CATALOG_MIGRATION_SET')
    need(all(after[k]==v for k,v in before.items()) and after['21']['sha256']==sql_sha,
         'CATALOG_EXISTING_MIGRATIONS_CHANGED')
    need(previous['configuration']==candidate['configuration'],'CATALOG_APPLICATION_CONFIGURATION_CHANGED')


def schema(before,after,image_attributes):
    old={(r[0],r[1]):r for r in before['columns']}
    new={(r[0],r[1]):r for r in after['columns']}
    need(not any(('products',n) in old for n in IMAGE_META),'CATALOG_IMAGE_SCHEMA_ALREADY_PRESENT')
    need(set(new)-set(old)=={('products',n) for n in IMAGE_META} and all(new.get(k)==v for k,v in old.items()),
         'CATALOG_SCHEMA_DELTA')
    for name,kind,length in [('image_role','varchar(32)',32),('image_display_notice','varchar(255)',255),
                             ('image_asset_sha256','char(64)',64),('image_assignment_run','varchar(64)',64)]:
        r=new[('products',name)]
        need(r[3:]==[kind,'YES',length,None,''],'CATALOG_IMAGE_COLUMN_DEFINITION')
    need(before['indexes']==after['indexes'] and before['foreign_keys']==after['foreign_keys'] and
         before['tables']==after['tables'],'CATALOG_EXISTING_SCHEMA_CHANGED')
    need(image_attributes==[
        ['image_asset_sha256','ascii','ascii_general_ci'],
        ['image_assignment_run','ascii','ascii_general_ci'],
        ['image_display_notice','utf8mb4','utf8mb4_unicode_ci'],
        ['image_role','utf8mb4','utf8mb4_unicode_ci']], 'CATALOG_IMAGE_COLLATION')


def verify_values(conn,source,journal,codec,dataset,guard,progress=lambda *args:None):
    """Read all product rows; reject missing/extra changes and broken observation pointers."""
    after=0;count=changed=0;columns=[n for n,_ in source.columns]
    from catalog_writer import saved_values,plain,Writer
    reader=Writer(conn,source,codec,journal,dataset,guard)
    while True:
        guard()
        with conn.cursor() as cur:
            cur.execute('SELECT '+','.join('`'+n+'`' for n in columns)+' FROM products WHERE product_id>%s ORDER BY product_id LIMIT 500',(after,))
            rows=[plain(r) for r in cur.fetchall()]
            if not rows:break
            target=[]
            for row in rows:
                need(not changes(row,source.get(row['barcode']),source.columns),'CATALOG_SOURCE_VALUES_NOT_APPLIED')
                record=journal.db.execute('SELECT barcode,new_values,new_payload_hash,old_values FROM changes WHERE product_id=?',(row['product_id'],)).fetchone()
                if record:
                    need(row['barcode']==record[0] and saved_values(row)==json.loads(record[1]),'CATALOG_CHANGED_VALUES_DRIFT')
                    target.append(row);changed+=1
                else:journal.require_baseline(row)
            prior=reader.previous(cur,target)
            if target:
                payloads=codec([{'row':r,'previous':None} for r in target])
                for row,encoded in zip(target,payloads):
                    snapshot=prior.get(row['attribute_snapshot_id'])
                    record=journal.db.execute('SELECT old_values,previous_id,new_payload_hash FROM changes WHERE product_id=?',(row['product_id'],)).fetchone()
                    old=json.loads(record[0])
                    expected_group=encoded['group_key'] if row['image_url']!=old['image_url'] else old['product_group_key']
                    need(snapshot is not None and snapshot['payload_json']==encoded['payload_json'] and
                         snapshot['payload_hash']==encoded['payload_hash'] and row['product_group_key']==expected_group and
                         snapshot['previous_snapshot_id']==record[1] and snapshot['payload_hash']==record[2],
                         'CATALOG_OBSERVATION_OR_GROUP_MISMATCH')
                    from catalog_writer import ACTOR
                    need(snapshot['dataset_version']==dataset and snapshot['observed_by']==ACTOR,'CATALOG_OBSERVATION_LINEAGE')
            count+=len(rows);need(count<=source.meta['source_rows'],'CATALOG_VERIFY_ROW_LIMIT')
            after=rows[-1]['product_id']
        conn.rollback()
        progress('PRODUCT_VERIFY',count,source.meta['source_rows'])
    need(count==source.meta['source_rows'] and changed==journal.db.execute('SELECT COUNT(*) FROM changes').fetchone()[0],
         'CATALOG_VERIFY_COUNTS')
    return {'products':count,'changed':changed}


def verify_recovered(conn,source,journal,codec,dataset,guard,progress=lambda *args:None):
    from catalog_writer import Writer,plain,saved_values,ACTOR
    from catalog_delta import identity
    reader=Writer(conn,source,codec,journal,dataset,guard)
    after=count=0
    while True:
        guard()
        with conn.cursor() as cur:
            cur.execute('SELECT '+','.join('`'+n+'`' for n,_ in source.columns)+' FROM products WHERE product_id>%s ORDER BY product_id LIMIT 500',(after,))
            rows=[plain(r) for r in cur.fetchall()]
            if not rows:break
            returned=[]
            for row in rows:
                item=source.get(row['barcode'])
                need(item['product_id']==row['product_id'] and identity(row,source.columns)==item['identity_hash'],'CATALOG_RECOVERY_PRODUCT_IDENTITY')
                record=journal.db.execute('SELECT old_values,previous_id,new_payload_hash FROM changes WHERE product_id=?',(row['product_id'],)).fetchone()
                if record:
                    need(saved_values(row)==json.loads(record[0]),'CATALOG_RECOVERY_VALUES_NOT_RESTORED')
                    journal.require_baseline(dict(row,attribute_snapshot_id=record[1]))
                    if row['attribute_snapshot_id']!=record[1]:returned.append((row,record))
                else:journal.require_baseline(row)
            if returned:
                snapshots=reader.previous(cur,[r for r,_ in returned])
                parents=reader.previous(cur,[dict(r,attribute_snapshot_id=snapshots[r['attribute_snapshot_id']]['previous_snapshot_id']) for r,_ in returned])
                payloads=codec([{'row':r,'previous':None} for r,_ in returned])
                for (row,record),payload in zip(returned,payloads):
                    snapshot=snapshots[row['attribute_snapshot_id']]
                    parent=parents.get(snapshot['previous_snapshot_id'])
                    need(snapshot['dataset_version']==dataset+'-rollback' and snapshot['observed_by']==ACTOR and
                         snapshot['payload_json']==payload['payload_json'] and snapshot['payload_hash']==payload['payload_hash'] and
                         parent is not None and parent['dataset_version']==dataset and parent['observed_by']==ACTOR and
                         parent['payload_hash']==record[2] and parent['previous_snapshot_id']==record[1],
                         'CATALOG_RECOVERY_FULL_CHAIN')
            count+=len(rows);need(count<=source.meta['source_rows'],'CATALOG_RECOVERY_VERIFY_BOUND')
            after=rows[-1]['product_id']
        conn.rollback()
        progress('RECOVERY_VERIFY',count,source.meta['source_rows'])
    need(count==source.meta['source_rows'],'CATALOG_RECOVERY_VERIFY_COUNT')
    return {'products':count,'original_values_restored':True}
