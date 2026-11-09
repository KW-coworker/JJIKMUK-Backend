from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from database_probe import properties
from deploy import request_from_environment
from host import atomic_json
from release import check_snapshot, guard


class GuardTests(unittest.TestCase):
    def test_ssm_rejects_missing_injected_and_null_values(self):
        good = {'SSM_ReleaseCommit': 'a'*40, 'SSM_RunId': '1', 'SSM_RunAttempt': '1',
                'SSM_JarSha256': 'b'*64, 'SSM_JarVersion': 'v/1+ok', 'SSM_ManifestVersion': 'v2'}
        self.assertEqual('1-1', request_from_environment(good)['run_key'])
        for key in good:
            for bad in ['', ';touch /tmp/x', 'null', '\nhello']:
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                    request_from_environment(dict(good, **{key:bad}))

    def test_backup_requires_same_account_database_encryption_freshness(self):
        now = datetime(2026,11,8,tzinfo=timezone.utc)
        good = {'Status':'available', 'Encrypted':True, 'DBInstanceIdentifier':'test-db',
                'DBSnapshotArn':'arn:aws:rds:ap-northeast-2:111111111111:snapshot:test',
                'SnapshotCreateTime':now.isoformat()}
        check_snapshot(good, '111111111111', 'test-db', now)
        for key,value in [('Status','creating'),('Encrypted',False),('DBInstanceIdentifier','other'),
                          ('DBSnapshotArn','wrong'),('SnapshotCreateTime',(now-timedelta(days=2)).isoformat())]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_snapshot(dict(good,**{key:value}),'111111111111','test-db',now)

    def test_atomic_json_preserves_old_value_if_abandoned_temp_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json'
            atomic_json(path, {'version':1})
            path.with_suffix('.tmp').write_text('incomplete',encoding='utf-8')
            with self.assertRaises(FileExistsError): atomic_json(path,{'version':2})
            self.assertEqual({'version':1},json.loads(path.read_text()))

    def test_ambiguous_credentials_are_rejected_not_reinterpreted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'local.properties'
            for text in ['spring.datasource.password=${SECRET}', 'spring.datasource.password=a\\b',
                         'spring.datasource.username=a\nspring.datasource.username=b']:
                path.write_text(text,encoding='utf-8')
                with self.assertRaises(ValueError): properties(path)

    def test_alternate_datasource_and_schema_controls_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'local.properties'
            for key in ['spring.datasource.hikari.jdbc-url','spring.datasource.jndi-name',
                        'spring.jpa.properties.hibernate.hbm2ddl.auto',
                        'spring.jpa.properties.jakarta.persistence.schema-generation.database.action',
                        'spring.sql.init.mode','spring.liquibase.enabled']:
                path.write_text(key+'=unsafe',encoding='utf-8')
                with self.subTest(key=key), self.assertRaises(ValueError): properties(path)


if __name__ == '__main__': unittest.main()
