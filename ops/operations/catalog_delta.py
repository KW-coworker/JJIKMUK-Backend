"""Supplied product values only. No connection, SQL execution or member data.

An immutable 42-field identity is checked before changing the two supplied
allergy quality fields, filling nutrition basis or filling an empty image.
"""
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from catalog_compare import (SQL_SHA, SOURCE_ROWS, NON_IDENTITY, IMAGE_META,
                             ROLES, canonical, normalized, parse_rows, present, need)

QUALITY = ('allergy_evidence_level', 'allergy_data_confidence')
VALUES = (*QUALITY, 'nutrition_basis_raw', 'image_url', *IMAGE_META)
LEVELS = {'VERIFIED_SOURCE', 'DECLARED_LABEL', 'INGREDIENT_DERIVED', 'INFERRED', 'UNKNOWN', 'SOURCE_INGREDIENTS'}
FORMAT = 1


def identity(row, columns):
    return hashlib.sha256(canonical([[name, normalized(row[name], kind)]
        for name, kind in columns if name not in NON_IDENTITY and name not in QUALITY])).digest()


def source_values(row):
    need(type(row['product_id']) is int and row['product_id'] > 0 and
         type(row['barcode']) is str and 0 < len(row['barcode']) <= 255, 'PRODUCT_KEY')
    values = {name: row[name] for name in VALUES}
    need(values[QUALITY[0]] in LEVELS, 'SOURCE_ALLERGY_LEVEL')
    confidence = values[QUALITY[1]]
    need(confidence is None or type(confidence) in (int, float) and 0 <= confidence <= 1,
         'SOURCE_ALLERGY_CONFIDENCE')
    limits = {'nutrition_basis_raw': 255, 'image_url': 2048, 'image_role': 32,
              'image_display_notice': 255, 'image_asset_sha256': 64, 'image_assignment_run': 64}
    for name, limit in limits.items():
        value = values[name]
        need(value is None or type(value) is str and len(value) <= limit and '\0' not in value,
             'SOURCE_TEXT_LIMIT')
    # Historical URLs are retained, never newly assigned without source role
    # metadata. Apply the HTTPS requirement to the newly supplied assignments.
    if values['image_role'] in ROLES:
        parsed = urlsplit(values['image_url'])
        need(parsed.scheme == 'https' and parsed.hostname and not parsed.username and
             not parsed.password and not parsed.fragment, 'SOURCE_IMAGE_URL')
        need(present(values['image_url']) and present(values['image_display_notice']) and
             re.fullmatch('[a-f0-9]{64}', values['image_asset_sha256'] or '') and
             present(values['image_assignment_run']), 'SOURCE_IMAGE_METADATA')
    canonical(values)  # Reject NaN and unsupported literal types.
    return values


def changes(current, source, columns):
    need(current['barcode'] == source['barcode'] and current['product_id'] == source['product_id'],
         'PRODUCT_IDENTITY_CHANGED')
    need(identity(current, columns) == source['identity_hash'], 'IMMUTABLE_PRODUCT_FIELDS_CHANGED')
    wanted = source['values']
    result = {name: wanted[name] for name in QUALITY if current[name] != wanted[name]}
    if present(wanted['nutrition_basis_raw']):
        need(not present(current['nutrition_basis_raw']) or
             current['nutrition_basis_raw'] == wanted['nutrition_basis_raw'], 'EXISTING_NUTRITION_BASIS_CONFLICT')
        if not present(current['nutrition_basis_raw']):
            result['nutrition_basis_raw'] = wanted['nutrition_basis_raw']
    if not present(current['image_url']) and present(wanted['image_url']):
        need(wanted['image_role'] in ROLES, 'EMPTY_IMAGE_HAS_NO_SOURCE_ROLE')
        result.update({name: wanted[name] for name in ('image_url', *IMAGE_META)})
    # Existing nonempty URLs and their metadata are retained even if source differs.
    return result


def build(source, state, output):
    output = Path(output)
    need(not output.exists() and not output.is_symlink(), 'DELTA_OUTPUT_EXISTS')
    columns = [(r['column'], r['type']) for r in state['columns'] if r['table'] == 'products']
    need(len(columns) == 54 and len({n for n, _ in columns}) == 54, 'SOURCE_COLUMN_COUNT')
    con = sqlite3.connect(output)
    digest = hashlib.sha256()
    count = basis = images = 0
    try:
        con.execute('PRAGMA cache_size=-32768')
        con.execute('CREATE TABLE products(barcode TEXT PRIMARY KEY COLLATE BINARY, '
                    'product_id INTEGER NOT NULL UNIQUE, identity_hash BLOB NOT NULL, values_json TEXT NOT NULL)')
        con.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        with gzip.open(source, 'rb') as stream:
            while line := stream.readline(16 * 1024**2 + 1):
                need(len(line) <= 16 * 1024**2, 'SOURCE_LINE_LIMIT')
                digest.update(line)
                if not line.startswith(b'INSERT INTO `products` VALUES '):
                    continue
                for row in parse_rows(line, columns):
                    values = source_values(row)
                    con.execute('INSERT INTO products VALUES (?,?,?,?)',
                        (row['barcode'], row['product_id'], identity(row, columns), canonical(values).decode()))
                    count += 1
                    basis += present(values['nutrition_basis_raw'])
                    images += present(values['image_url'])
                    need(count <= SOURCE_ROWS, 'SOURCE_ROW_LIMIT')
        need(digest.hexdigest() == SQL_SHA and count == SOURCE_ROWS, 'SOURCE_HASH_OR_COUNT')
        need(basis == 289044 and images == 1098863, 'SOURCE_TARGET_COUNTS')
        metadata = {'format': FORMAT, 'sql_sha256': SQL_SHA, 'columns': columns,
                    'source_rows': count, 'source_basis_filled': basis, 'source_image_filled': images}
        con.executemany('INSERT INTO metadata VALUES (?,?)', [(k, json.dumps(v)) for k, v in metadata.items()])
        con.commit()
        need(con.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'DELTA_DATABASE_INTEGRITY')
        return metadata
    finally:
        con.close()


class Source:
    def __init__(self, path):
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
        self.db.execute('PRAGMA query_only=ON')
        self.db.execute('PRAGMA cache_size=-65536')
        self.meta = {k: json.loads(v) for k, v in self.db.execute('SELECT key,value FROM metadata')}
        need(self.meta['format'] == FORMAT and self.meta['sql_sha256'] == SQL_SHA and
             self.meta['source_rows'] == SOURCE_ROWS, 'DELTA_BINDING')
        self.columns = self.meta['columns']

    def get(self, barcode):
        row = self.db.execute('SELECT * FROM products WHERE barcode=? COLLATE BINARY', (barcode,)).fetchone()
        need(row is not None, 'OPERATING_PRODUCT_NOT_IN_SOURCE')
        return dict(zip(('barcode', 'product_id', 'identity_hash', 'values'), (*row[:3], json.loads(row[3]))))

    def close(self):
        self.db.close()
