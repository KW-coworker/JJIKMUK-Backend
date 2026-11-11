import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from catalog_checks import schema,manifests
from catalog_delta import IMAGE_META
from catalog_document import document
from catalog_package import source_plan,SOURCE_SHA,SOURCE_BYTES,ARCHIVE_SHA,ARCHIVE_BYTES,PREVIOUS
from catalog_runner import time_budget
from catalog_writer import Journal,MUTABLE
from connection import canonical,sha


class ContractTests(unittest.TestCase):
    def metadata(self):
        old={'columns':[['products','barcode',1,'varchar(255)','NO',255,None,'']],
             'indexes':[['products','fulltext','FULLTEXT']], 'foreign_keys':[],
             'tables':[['products','InnoDB','Dynamic']]}
        new=copy.deepcopy(old)
        for i,(name,kind,n) in enumerate(zip(IMAGE_META,
                ['varchar(32)','varchar(255)','char(64)','varchar(64)'],[32,255,64,64]),2):
            new['columns'].append(['products',name,i,kind,'YES',n,None,''])
        attrs=[['image_asset_sha256','ascii','ascii_general_ci'],['image_assignment_run','ascii','ascii_general_ci'],
               ['image_display_notice','utf8mb4','utf8mb4_unicode_ci'],['image_role','utf8mb4','utf8mb4_unicode_ci']]
        return old,new,attrs

    def test_exact_source_image_definition_and_original_columns(self):
        old,new,attrs=self.metadata();schema(old,new,attrs)
        for mutate in (
                lambda n,a:n['columns'][0].__setitem__(3,'text'),
                lambda n,a:n['indexes'].clear(),
                lambda n,a:a[1].__setitem__(1,'utf8mb4'),
                lambda n,a:n['columns'][-1].__setitem__(4,'NO')):
            changed,collation=copy.deepcopy(new),copy.deepcopy(attrs);mutate(changed,collation)
            with self.assertRaises(ValueError):schema(old,changed,collation)

    def test_migration_only_adds_v21_and_preserves_original_configuration(self):
        old={'migrations':[{'version':str(i),'sha256':sha(str(i).encode())} for i in range(1,21)],'configuration':{'auto_ddl':False}}
        new=copy.deepcopy(old);new['migrations'].append({'version':'21','sha256':'a'*64})
        manifests(old,new,'a'*64)
        new['migrations'][16]['sha256']='b'*64
        with self.assertRaises(ValueError):manifests(old,new,'a'*64)
        new=copy.deepcopy(old);new['migrations'].append({'version':'21','sha256':'a'*64});new['configuration']['auto_ddl']=True
        with self.assertRaises(ValueError):manifests(old,new,'a'*64)

    def test_baseline_detects_each_mutable_field_pointer_and_identity_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=Journal(Path(tmp)/'private.sqlite',{'request':'fixture'})
            row={'product_id':1,'barcode':'fixture','attribute_snapshot_id':2,**{n:None for n in MUTABLE}}
            try:
                j.baseline([row]);j.require_baseline(row)
                for key in ('barcode','attribute_snapshot_id',*MUTABLE):
                    with self.assertRaisesRegex(ValueError,'BEFORE_VALUES_CHANGED'):
                        j.require_baseline(dict(row,**{key:'changed'}))
                with self.assertRaisesRegex(ValueError,'BEFORE_VALUES_CHANGED'):
                    j.require_baseline(dict(row,product_id=9))
            finally:j.close()
            with self.assertRaises(FileExistsError):Journal(Path(tmp)/'private.sqlite',{'request':'fixture'})

    def test_source_plan_requires_exact_payload_and_version(self):
        value={'approved':True,'approval_id':'USER_SOURCE_COMPATIBILITY_AND_DB_APPLY_20261111',
               'source_key':'operations/private/'+'1'*32+'/'+ARCHIVE_SHA+'.zip','source_version':'fixture-version',
               'source_archive_sha256':ARCHIVE_SHA,'source_archive_bytes':ARCHIVE_BYTES,
               'source_sqlite_sha256':SOURCE_SHA,'source_sqlite_bytes':SOURCE_BYTES,'previous_commit':PREVIOUS,'required_bytes':5*1024**3}
        raw=canonical(value)
        with patch.object(Path,'read_bytes',return_value=raw):
            self.assertEqual(source_plan('ops/operations/plans/catalog-fixture.json',sha(raw)),value)
            with self.assertRaises(ValueError):source_plan('ops/operations/plans/catalog-fixture.json','f'*64)
        for key,val in [('source_version','null'),('approved',False),('source_archive_sha256','0'*64),
                        ('source_sqlite_bytes',SOURCE_BYTES+1),('previous_commit','b'*40),('required_bytes',1)]:
            bad=canonical(dict(value,**{key:val}))
            with patch.object(Path,'read_bytes',return_value=bad),self.assertRaises(ValueError):
                source_plan('ops/operations/plans/catalog-fixture.json',sha(bad))

    def test_generated_commands_compile_without_running_and_bind_phase(self):
        binding={'archive_sha256':'a'*64,'request_id':'b'*32}
        for phase in ('freeze','apply','recover'):
            result=document(binding,{'files':{}},phase)
            self.assertEqual(result['parameters'],{})
            script=result['mainSteps'][0]['inputs']['runCommand'][0].split('\n',1)[1].rsplit('\nJJIKMUK_CATALOG_FIXED',1)[0]
            compile(script,'fixed-'+phase,'exec')
            self.assertIn('RuntimeMaxSec=',script)
            self.assertIn('"phase":"'+phase+'"',script)
        with self.assertRaises(ValueError):document(binding,{},'replay')

    def test_expiring_role_cannot_start_apply(self):
        with patch.dict(os.environ,{'CATALOG_ROLE_REQUEST_EPOCH':'1900000000'}),patch('catalog_runner.time.time',return_value=1900000100):
            time_budget('apply')
        with patch.dict(os.environ,{'CATALOG_ROLE_REQUEST_EPOCH':'1900000000'}),patch('catalog_runner.time.time',return_value=1900001300):
            with self.assertRaisesRegex(ValueError,'TIME_INSUFFICIENT'):time_budget('apply')
        with patch.dict(os.environ,{'CATALOG_ROLE_REQUEST_EPOCH':''}):
            with self.assertRaisesRegex(ValueError,'TIME_REQUIRED'):time_budget('freeze')


if __name__=='__main__':unittest.main()
