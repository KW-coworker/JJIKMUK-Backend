import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unittest
import os
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

import initial_schema as schema
from initial_schema_contract import COLUMNS, INDEXES, FOREIGN_KEYS
import initial_db_runner as runner
from manifest import checksum

ROOT = Path(__file__).resolve().parents[3]


def manifest():
    return {'migrations': [{'version': p.name.split('__')[0][1:], 'script': p.name,
                            'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'checksum': checksum(p.read_bytes())}
                           for p in sorted((ROOT / 'src/main/resources/db/migration').glob('*.sql'))]}


def metadata(prepared=False):
    m = manifest()
    columns = [[table, 'id', 1, 'bigint', 'NO', None, None, '']
               for table in ('products', 'products_rollback', 'users', 'family_profiles')]
    if prepared:
        columns += [[t, c, 2, kind, nullable, 255 if kind.startswith('varchar') else None, '0' if t == 'users' else None, '']
            for t, c, kind, nullable in [('products', 'nutrition_basis_raw', 'varchar(255)', 'YES'),
                ('products_rollback', 'nutrition_basis_raw', 'varchar(255)', 'YES'),
                ('users', 'profile_version', 'bigint', 'NO')]]
        columns += [[t, name, i, kind, nullable, None, default, extra]
                    for t, rows in COLUMNS.items() for i, (name, kind, nullable, default, extra) in enumerate(rows, 1)]
    history = [dict(version='0', script='baseline', checksum=None, type='BASELINE', success=True)]
    history += [dict(version=r['version'], script=r['script'], checksum=r['checksum'], type='SQL', success=True)
                for r in m['migrations'] if prepared or int(r['version']) <= 16]
    indexes = [[t, 'PRIMARY', 0, 1, 'id', None, 'BTREE'] for t in ('products', 'users', 'family_profiles')]
    fks = []
    if prepared:
        indexes += [[table, name, non_unique, i, col, None, 'BTREE'] for table, rows in INDEXES.items()
                    for name, non_unique, cols in rows for i, col in enumerate(cols, 1)]
        fks = [[t, n, 1, c, 'jjikmuk', rt, rc, 'RESTRICT', 'CASCADE'] for t, n, c, rt, rc in FOREIGN_KEYS]
    return {'columns': columns, 'indexes': indexes, 'history': history, 'foreign_keys': fks,
            'tables': [[t, 'InnoDB', 'Dynamic'] for t in sorted({r[0] for r in columns})]}


class InitialSchemaTests(unittest.TestCase):
    def test_exact_before_after_and_preservation(self):
        m, before, after = manifest(), metadata(), metadata(True)
        schema.verify_schema(m, before, False)
        schema.verify_schema(m, after, True)
        schema.verify_preservation(before, after)

    def test_changed_sql_or_new_version_is_rejected(self):
        for change in ('hash', 'extra'):
            m = manifest()
            if change == 'hash': next(r for r in m['migrations'] if r['version'] == '19')['sha256'] = '0' * 64
            else: m['migrations'].append(dict(m['migrations'][0], version='21'))
            with self.assertRaises(ValueError): schema.validate_source(m)

    def test_fulltext_and_incompatible_fk_parent_stop_before_any_ddl(self):
        for kind in ('fulltext', 'type', 'key', 'engine'):
            value = metadata()
            if kind == 'fulltext': value['indexes'].append(['products', 'ft', 1, 1, 'search_keywords', None, 'FULLTEXT'])
            if kind == 'type': next(r for r in value['columns'] if r[0] == 'users')[3] = 'bigint unsigned'
            if kind == 'key': value['indexes'] = [r for r in value['indexes'] if r[0] != 'users']
            if kind == 'engine': next(r for r in value['tables'] if r[0] == 'family_profiles')[1] = 'MyISAM'
            with self.subTest(kind=kind), self.assertRaises(ValueError): schema.verify_schema(manifest(), value, False)

    def test_maintenance_opt_in_allows_only_exact_existing_product_index(self):
        value=metadata()
        index=['products','ft_products_search_keywords',1,1,'search_keywords',None,'FULLTEXT']
        value['indexes'].append(index)
        with self.assertRaises(ValueError):schema.verify_schema(manifest(),value,False)
        schema.verify_schema(manifest(),value,False,fulltext_maintenance=True)
        for position,replacement in ((0,'products_rollback'),(1,'different_index'),(4,'nutrition_basis_raw')):
            bad=copy.deepcopy(value);bad['indexes'][-1][position]=replacement
            with self.assertRaises(ValueError):schema.verify_schema(manifest(),bad,False,fulltext_maintenance=True)

    def test_missing_old_history_failed_checksum_or_partial_ddl_is_rejected(self):
        for kind in ('missing', 'checksum', 'failure', 'partial', 'baseline'):
            value = metadata()
            if kind == 'missing': value['history'].pop()
            if kind == 'checksum': value['history'][1]['checksum'] += 1
            if kind == 'failure': value['history'][1]['success'] = False
            if kind == 'partial': value['columns'].append(['users', 'profile_version', 2, 'bigint', 'NO', None])
            if kind == 'baseline': value['history'].append(value['history'][0])
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                schema.verify_schema(manifest(), value, False)

    def test_existing_columns_and_indexes_must_survive(self):
        for field in ('columns', 'indexes'):
            after = metadata(True)
            after[field].pop(0)
            with self.subTest(field=field), self.assertRaises(ValueError):
                schema.verify_preservation(metadata(), after)

    def test_missing_new_fields_indexes_fk_or_wrong_default_is_rejected(self):
        for kind in ('column', 'index', 'foreign_key', 'default', 'cascade'):
            value = metadata(True)
            if kind == 'column': value['columns'] = [r for r in value['columns'] if r[1] != 'include_self']
            if kind == 'index': value['indexes'].pop()
            if kind == 'foreign_key': value['foreign_keys'].pop()
            if kind == 'default': next(r for r in value['columns'] if r[1] == 'profile_version')[6] = None
            if kind == 'cascade': value['foreign_keys'][0][-1] = 'RESTRICT'
            with self.subTest(kind=kind), self.assertRaises(ValueError): schema.verify_schema(manifest(), value, True)

    @unittest.skipUnless(os.name == 'posix', 'Linux process-group behavior')
    def test_timeout_kills_grandchild_before_it_can_write(self):
        with tempfile.TemporaryDirectory() as td:
            marker = str(Path(td) / 'must-not-exist')
            child = "import time,pathlib;time.sleep(4);pathlib.Path(" + repr(marker) + ").write_text('orphan')"
            parent = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c'," + repr(child) + "]);time.sleep(10)"
            with self.assertRaisesRegex(ValueError, 'PROCESS_TIMEOUT'):
                schema.bounded_process([sys.executable, '-c', parent], b'', 0.5)
            time.sleep(4.2)
            self.assertFalse(Path(marker).exists())

    def test_snapshot_intent_precedes_creation_and_never_retries_create(self):
        rds, api = MagicMock(), {'s3': MagicMock()}
        rds.create_db_snapshot.side_effect = RuntimeError('lost response')
        with patch.object(runner, 'put_once') as intent, self.assertRaises(RuntimeError):
            runner.snapshot(rds, api, {'run_id': '123', 'commit': 'a' * 40, 'request_id': 'b' * 32},frozen_epoch=1)
        intent.assert_called_once()
        rds.create_db_snapshot.assert_called_once()
        rds.describe_db_snapshots.assert_not_called()

    def test_database_backups_required_before_snapshot_or_host_work(self):
        rds = MagicMock()
        row = {'DBInstanceIdentifier': runner.DB,
               'DBInstanceArn': 'arn:aws:rds:ap-northeast-2:076767081522:db:' + runner.DB,
               'Engine': 'mysql', 'EngineVersion': '8.0.43', 'DBInstanceStatus': 'available',
               'StorageEncrypted': True, 'BackupRetentionPeriod': 1,
               'LatestRestorableTime': datetime.now(timezone.utc), 'PreferredBackupWindow': '00:00-00:30'}
        row['Endpoint'] = {'Address': runner.DB_HOST, 'Port': 3306}
        rds.describe_db_instances.return_value = {'DBInstances': [row]}
        self.assertTrue(runner.check_database(rds)['checks']['automated_backups_enabled'])
        row['BackupRetentionPeriod'] = 0
        with self.assertRaisesRegex(ValueError, 'AUTOMATED_BACKUP_REQUIRED'): runner.check_database(rds)

    def test_document_is_fixed_and_no_secret_values(self):
        h = 'a' * 64
        doc = runner.document('operations/bootstrap/' + h + '/payload.zip', h,
                              {'files': {}, 'commit': 'b' * 40}, {'commit': 'b' * 40})
        self.assertEqual({}, doc['parameters'])
        self.assertEqual('report', doc['mainSteps'][-1]['name'])
        self.assertLess(len(json.dumps(doc)), 60000)
        self.assertNotIn('spring.datasource.password', json.dumps(doc))
        for value in ('RuntimeMaxSec=1200', 'TimeoutStartSec=30', 'TimeoutStopSec=5', 'KillMode=control-group', 'Restart=no'):
            self.assertIn(value, json.dumps(doc))


if __name__ == '__main__': unittest.main()
