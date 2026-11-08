import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from manifest import make_manifest, validate_manifest, require_same_schema, require_database


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.jar = Path(self.tmp.name) / 'backend.jar'
        with zipfile.ZipFile(self.jar, 'w') as z:
            z.writestr('META-INF/MANIFEST.MF', 'Main-Class: org.springframework.boot.loader.launch.JarLauncher\n')
            z.writestr('BOOT-INF/classes/org/jjikmuk/backend/domain/chat/AiChatClient.class', b'chatbot.developer-test-auto-consent')
            z.writestr('BOOT-INF/classes/application.properties', 'spring.flyway.enabled=true\n')
            z.writestr('BOOT-INF/classes/db/migration/V1__test.sql', b'create table test (id int);\r\n')
        self.m = make_manifest(self.jar, 'a' * 40, '123', '1')

    def test_hash_covers_actual_jar(self):
        self.assertEqual(hashlib.sha256(self.jar.read_bytes()).hexdigest(), self.m['jar_sha256'])
        validate_manifest(self.m)

    def test_changed_migration_is_refused(self):
        changed = json.loads(json.dumps(self.m))
        changed['migrations'][0]['sha256'] = '0' * 64
        with self.assertRaises(ValueError): require_same_schema(self.m, changed)

    def test_changed_startup_configuration_is_refused(self):
        changed = json.loads(json.dumps(self.m))
        changed['configuration']['BOOT-INF/classes/application.properties'] = '0'*64
        with self.assertRaises(ValueError): require_same_schema(self.m, changed)

    def test_compressed_oversized_configuration_is_refused(self):
        with zipfile.ZipFile(self.jar, 'a', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('BOOT-INF/classes/extra.properties', b'x'*(1024*1024+1))
        with self.assertRaises(ValueError): make_manifest(self.jar, 'a'*40, '123', '1')

    def test_failed_missing_or_different_database_history_is_refused(self):
        row = dict(self.m['migrations'][0], success=True, type='SQL')
        require_database(self.m, [row])
        for rows in [[], [dict(row, success=False)], [dict(row, checksum=0)], [row, row]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError): require_database(self.m, rows)

    def test_wrong_repo_or_injected_identifier_is_refused(self):
        for key, value in [('repository', 'someone/else'), ('commit', '../evil'), ('run_id', '1; echo bad')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_manifest(dict(self.m, **{key: value}))

    def test_duplicate_zip_entry_is_refused(self):
        with zipfile.ZipFile(self.jar, 'a') as z:
            z.writestr('BOOT-INF/classes/db/migration/V1__other.sql', 'select 1;')
        with self.assertRaises(ValueError): make_manifest(self.jar, 'a' * 40, '123', '1')


if __name__ == '__main__': unittest.main()
