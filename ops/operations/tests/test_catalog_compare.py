import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from catalog_compare import build, Comparison, fingerprint, parse_rows, hashed


COLUMNS = [('barcode','varchar(255)'), ('product_id','bigint'),
    ('product_name','varchar(1000)'), ('manufacturer','varchar(1000)'),
    ('total_weight','varchar(255)'), ('raw_materials','text'), ('energy_kcal','double'),
    ('is_vegan','bit(1)'), ('attribute_snapshot_id','bigint'), ('product_group_key','char(64)'),
    ('image_url','varchar(2000)'), ('nutrition_basis_raw','varchar(255)'),
    ('image_role','varchar(32)'), ('image_display_notice','varchar(255)'),
    ('image_asset_sha256','char(64)'), ('image_assignment_run','varchar(64)')]


def row(**updates):
    result = dict(zip([n for n, _ in COLUMNS],
        ['SKU', 1, '시험 상품', '제조사', '44g', '밀,설탕', 10.0, 1, 1, 'g'*64,
         'https://example.invalid/img?token=DO_NOT_EXPORT', '100g',
         'CATEGORY_REFERENCE', '다른 상품 사진', 'a'*64, 'fixture-only']))
    return result | updates


def sql_literal(value):
    if value is None:
        return b'NULL'
    if isinstance(value, str):
        return b"'"+value.replace('\\','\\\\').replace("'","\\'").replace('\n','\\n').encode()+b"'"
    return str(value).encode()


class CatalogComparisonTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def sidecar(self, rows):
        payload = b'CREATE TABLE `products` (\n) ENGINE=InnoDB;\n'
        payload += b'INSERT INTO `products` VALUES '+b','.join(
            b'('+b','.join(sql_literal(r[n]) for n, _ in COLUMNS)+b')' for r in rows)+b';\n'
        # A non-product statement is never executed or extracted.
        payload += b"INSERT INTO `users` VALUES ('PRIVATE_MEMBER_MUST_NOT_COPY');\n"
        source = self.base/'input.sql.gz'
        source.write_bytes(gzip.compress(payload))
        target = self.base/'fingerprints.sqlite'
        state = {'columns': [{'table':'products','column':n,'type':t} for n,t in COLUMNS]}
        counts = build(source,target,state,hashlib.sha256(payload).hexdigest(),len(rows))
        return target, counts

    def compare(self, source, operating):
        path, _ = self.sidecar(source)
        c = Comparison(path)
        try:
            for r in operating:
                c.consume(r)
            return c.finish()['counts']
        finally:
            c.close()

    def test_only_public_keys_and_hashes_are_stored(self):
        path, counts = self.sidecar([row()])
        raw = path.read_bytes()
        self.assertNotIn(b'DO_NOT_EXPORT',raw)
        self.assertNotIn(b'PRIVATE_MEMBER_MUST_NOT_COPY',raw)
        self.assertNotIn('시험 상품'.encode(),raw)
        self.assertEqual(counts['source_category_reference'],1)

    def test_blank_image_and_basis_are_candidates(self):
        c = self.compare([row()],[row(image_url=' ',nutrition_basis_raw=None)])
        self.assertEqual(c['image_fill_category_candidate'],1)
        self.assertEqual(c['basis_fill_candidate'],1)

    def test_existing_image_is_preserved_and_basis_conflict_held(self):
        c = self.compare([row()],[row(image_url='old',nutrition_basis_raw='44g')])
        self.assertEqual(c['image_existing_preserved'],1)
        self.assertEqual(c['image_fill_category_candidate'],0)
        self.assertEqual(c['basis_conflict_held'],1)

    def test_same_barcode_other_id_is_never_merged(self):
        c = self.compare([row()],[row(product_id=2,image_url=None)])
        self.assertEqual(c['id_conflict'],1)
        self.assertEqual(c['exact_identity'],0)

    def test_same_keys_changed_product_is_never_merged(self):
        c = self.compare([row()],[row(raw_materials='다른 배합',image_url=None)])
        self.assertEqual(c['identity_conflict'],1)
        self.assertEqual(c['image_fill_category_candidate'],0)

    def test_old_and_new_only_are_separate_not_inserted(self):
        c = self.compare([row()],[row(barcode='OTHER',product_id=2)])
        self.assertEqual((c['source_only'],c['operating_only']),(1,1))

    def test_missing_image_metadata_is_held(self):
        c = self.compare([row(image_asset_sha256=None)],[row(image_url=None)])
        self.assertEqual(c['image_fill_bad_metadata_held'],1)

    def test_snapshot_and_group_difference_are_visible(self):
        c = self.compare([row()],[row(attribute_snapshot_id=2,product_group_key='h'*64)])
        self.assertEqual((c['snapshot_difference'],c['group_difference']),(1,1))

    def test_dump_and_database_types_hash_identically(self):
        source = fingerprint(row(energy_kcal=10,is_vegan=1),COLUMNS)
        operating = fingerprint(row(energy_kcal=10.0,is_vegan=b'\x01'),COLUMNS)
        self.assertEqual(source,operating)

    def test_escaped_literals_and_binary_bits(self):
        data = b"INSERT INTO `products` VALUES ('a\\'b\\n',_binary '\\0');\n"
        rows = list(parse_rows(data,[('text','text'),('flag','bit(1)')]))
        self.assertEqual(rows,[{'text':"a'b\n",'flag':0}])

    def test_malformed_dump_is_rejected(self):
        with self.assertRaises(ValueError):
            list(parse_rows(b"INSERT INTO `products` VALUES ('x'); DELETE FROM products;",[('text','text')]))

    def test_missing_fields_are_not_silently_null(self):
        value = row(); del value['manufacturer']
        with self.assertRaisesRegex(ValueError,'MISSING_PRODUCT_FIELDS'):
            fingerprint(value,COLUMNS)

    def test_duplicate_operating_keys_are_rejected(self):
        path, _ = self.sidecar([row()]); c = Comparison(path)
        try:
            c.consume(row())
            with self.assertRaises(ValueError):
                c.consume(row(product_id=2))
        finally:
            c.close()

    def test_source_is_readonly_during_comparison(self):
        path, _ = self.sidecar([row()]); before = hashlib.sha256(path.read_bytes()).hexdigest()
        c = Comparison(path)
        try:
            c.consume(row()); c.finish()
            with self.assertRaises(sqlite3.OperationalError):
                c.con.execute('DELETE FROM products')
        finally:
            c.close()
        self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
