import copy
import hashlib
import json
import unittest
from unittest.mock import Mock, patch

from product_image_patch import apply, validate
import product_image_hold


def fixture(n=1):
    return [dict(product_id=i+1, barcode=str(i+1), product_name='상품', manufacturer='제조사',
                 old_image_url='http://old.example/a.jpg', image_url='https://new.example/'+str(i)+'.jpg')
            for i in range(n)]


class Database:
    def __init__(self, items):
        self.rows = {i['barcode']: dict({k:v for k,v in i.items() if k not in ('old_image_url','image_url')},
            image_url=i['old_image_url'], attribute_snapshot_id=None, product_group_key='0'*64,
            image_role=None, image_display_notice=None, image_asset_sha256=None, image_assignment_run=None,
            allergy_evidence_level='UNKNOWN', energy_kcal=123.5) for i in items}
        self.events=[]; self.snapshots={}; self.commits=0; self.failure=None
    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def begin(self): self.original=copy.deepcopy((self.rows,self.snapshots)); self.events.append('begin')
    def commit(self):
        self.events.append('commit'); self.commits+=1
        if self.failure=='commit': raise OSError('unknown commit result')
        self.original=copy.deepcopy((self.rows,self.snapshots))
    def rollback(self): self.rows,self.snapshots=copy.deepcopy(self.original); self.events.append('rollback')
    def execute(self, sql, params=()):
        self.events.append(sql)
        if sql.startswith('SET SESSION'): return
        if sql.startswith('SELECT * FROM products WHERE barcode='):
            self.result=[copy.deepcopy(self.rows[params[0]])] if params[0] in self.rows else []
        elif sql.startswith('INSERT INTO product_attribute_snapshots '):
            self.lastrowid=100+len(self.snapshots); self.snapshots[self.lastrowid]=params
        elif sql.startswith('UPDATE products SET image_url='):
            if self.failure=='update': raise OSError('write failure')
            url,key,snapshot,barcode,pid,old=params; row=self.rows[barcode]
            self.rowcount=int(row['product_id']==pid and row['image_url']==old)
            if self.rowcount: row.update(image_url=url, product_group_key=key, attribute_snapshot_id=snapshot)
        else: raise AssertionError('Unexpected query: '+sql)
    def fetchall(self): return self.result
    def fetchone(self): return self.result[0] if self.result else None


def codec(values):
    result=[]
    for v in values:
        payload=json.dumps(v['row'],sort_keys=True)
        result.append(dict(payload_json=payload, payload_hash=hashlib.sha256(payload.encode()).hexdigest(),
                           changed_fields='image_url',group_key='a'*64))
    return result


class ImagePatchTests(unittest.TestCase):
    def run_patch(self, db, items):
        return apply(db,items,codec,lambda v:db.events.append('backup'),lambda v:db.events.append('intent'),'image-patch-test')

    def test_only_selected_one_or_twenty_products_change(self):
        for count in (1,20):
            items=fixture(count+1); db=Database(items); before=copy.deepcopy(db.rows)
            result=self.run_patch(db,items[:-1])
            self.assertEqual(result,{'products_updated':count,'snapshots_added':count})
            self.assertEqual(db.rows[items[-1]['barcode']],before[items[-1]['barcode']])
            for item in items[:-1]:
                old,new=before[item['barcode']],db.rows[item['barcode']]
                self.assertEqual({k for k in old if old[k]!=new[k]}, {'image_url','product_group_key','attribute_snapshot_id'})
            self.assertLess(db.events.index('backup'),next(i for i,s in enumerate(db.events) if s.startswith('INSERT')))
            self.assertLess(db.events.index('intent'),db.events.index('commit'))
            self.assertEqual(db.commits,1)

    def test_wrong_identity_or_previous_url_or_metadata_stops_before_writes(self):
        for key,value in [('product_id',999),('image_url','https://changed.example/a'),('image_role','CATEGORY_REFERENCE')]:
            items=fixture();db=Database(items);db.rows['1'][key]=value
            with self.assertRaises(ValueError): self.run_patch(db,items)
            self.assertEqual(db.snapshots,{});self.assertEqual(db.commits,0)

    def test_write_failure_rolls_back_observation_and_product(self):
        items=fixture();db=Database(items);before=copy.deepcopy(db.rows);db.failure='update'
        with self.assertRaises(OSError):self.run_patch(db,items)
        self.assertEqual(db.rows,before);self.assertEqual(db.snapshots,{})

    def test_uncertain_commit_never_retries(self):
        items=fixture();db=Database(items);db.failure='commit'
        with self.assertRaises(OSError):self.run_patch(db,items)
        self.assertEqual(db.commits,1);self.assertEqual(db.events.count('intent'),1)

    def test_invalid_lists_rejected(self):
        for items in ([],fixture(201),fixture()*2,[dict(fixture()[0],image_url='http://unsafe.example/a')]):
            with self.assertRaises(ValueError):validate(items)

    def test_existing_nullable_catalog_text_and_missing_old_photo_are_preserved(self):
        items=[dict(fixture()[0],product_name=None,manufacturer=None,old_image_url=None)]
        db=Database(items)
        self.assertEqual(self.run_patch(db,items)['products_updated'],1)
        self.assertIsNone(db.rows['1']['product_name']);self.assertIsNone(db.rows['1']['manufacturer'])

    def test_hold_identity_and_failure_never_resume_cd(self):
        ctx={'request_id':product_image_hold.REQUEST}
        gate={'state':'WORKING','request_id':ctx['request_id'],'run_id':'43041472793'}
        plan={'component':'db','operation':'deploy','approval_id':'USER_SINGLE_PRODUCT_IMAGE_20261112'}
        api={'s3':Mock()}
        with patch.object(product_image_hold,'Gate') as factory, patch.object(product_image_hold,'load_plan',return_value=(plan,product_image_hold.HOSTS['backend'])), patch.object(product_image_hold,'execute',return_value={'success':True}) as execute:
            factory.return_value.read.return_value=(gate,'etag')
            self.assertTrue(product_image_hold.perform(api,ctx,'path','hash')['success'])
            factory.return_value.start.assert_not_called();factory.return_value.finish.assert_not_called()
            execute.reset_mock();gate['state']='OPEN'
            with self.assertRaises(ValueError):product_image_hold.perform(api,ctx,'path','hash')
            execute.assert_not_called()


if __name__=='__main__':unittest.main()
