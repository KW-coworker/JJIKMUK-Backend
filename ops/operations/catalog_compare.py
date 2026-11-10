"""Product-only fingerprints and comparison. Never executes a supplied SQL dump.

The SQLite sidecar contains public keys and hashes, not image download URLs,
member rows, credentials, nutrition text, or application write statements.
"""
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

FORMAT = 1
SQL_SHA = 'e61c4d5ff7e6d7fd2828f85dff75e6b006481f25bfb99e8ebc1e459f982a2e23'
SOURCE_ROWS = 1348425
VALUE = re.compile(rb"\s*((?:_binary\s*)?'(?:[^'\\]|\\.)*'|NULL|0x[0-9a-fA-F]+|[-+0-9.eE]+)\s*([,)])")
ESCAPES = {b'0': b'\0', b'b': b'\b', b'n': b'\n', b'r': b'\r', b't': b'\t', b'Z': b'\x1a'}
IMAGE_META = ('image_role', 'image_display_notice', 'image_asset_sha256', 'image_assignment_run')
NON_IDENTITY = set(IMAGE_META) | {'barcode', 'product_id', 'attribute_snapshot_id',
                                'product_group_key', 'image_url', 'nutrition_basis_raw'}
ROLES = {'PRODUCT_REPRESENTATIVE', 'CATEGORY_REFERENCE'}


def need(ok, code):
    if not ok:
        raise ValueError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def hashed(value):
    return hashlib.sha256(canonical(value)).digest()


def normalized(value, sql_type):
    if value is None:
        return None
    if sql_type.startswith('bit('):
        return int.from_bytes(value, 'big') if isinstance(value, bytes) else int(value)
    if sql_type in ('double', 'float'):
        result = float(value)
        need(math.isfinite(result), 'NONFINITE_NUMBER')
        return 0.0 if result == 0 else result
    if sql_type.startswith(('bigint', 'int', 'tinyint', 'smallint')):
        return int(value)
    need(sql_type.startswith(('varchar(', 'char(', 'text', 'longtext', 'mediumtext')),
         'UNSUPPORTED_COLUMN_TYPE')
    return value.decode('utf-8') if isinstance(value, bytes) else str(value)


def decode(value, sql_type):
    if value == b'NULL':
        return None
    if value.startswith(b'_binary'):
        value = value[len(b'_binary'):].lstrip()
    if value.startswith(b"'"):
        value = re.sub(rb'\\(.)', lambda m: ESCAPES.get(m[1], m[1]), value[1:-1])
    elif value.lower().startswith(b'0x'):
        value = bytes.fromhex(value[2:].decode('ascii'))
    else:
        value = int(value) if sql_type.startswith('bit(') else value.decode('ascii')
    return normalized(value, sql_type)


def parse_rows(line, columns):
    prefix = b'INSERT INTO `products` VALUES '
    need(line.startswith(prefix), 'PRODUCT_STATEMENT_REQUIRED')
    pos, end = len(prefix), len(line.rstrip())
    while pos < end:
        need(line[pos:pos+1] == b'(', 'ROW_OPEN')
        pos += 1
        row = {}
        for index, (name, sql_type) in enumerate(columns):
            match = VALUE.match(line, pos)
            need(match is not None and match[2] == (b')' if index == len(columns)-1 else b','),
                 'ROW_LITERAL_OR_WIDTH')
            row[name] = decode(match[1], sql_type)
            pos = match.end()
        yield row
        if line[pos:pos+1] == b';' and pos+1 == end:
            return
        need(line[pos:pos+1] == b',', 'ROW_SUFFIX')
        pos += 1
    raise ValueError('UNTERMINATED_STATEMENT')


def present(value):
    return value is not None and bool(str(value).strip())


def fingerprint(row, columns):
    need({name for name, _ in columns if name not in IMAGE_META} <= set(row), 'MISSING_PRODUCT_FIELDS')
    need(type(row['product_id']) is int and row['product_id'] > 0 and
         isinstance(row['barcode'], str) and row['barcode'], 'PRODUCT_KEY')
    identity = [[name, normalized(row.get(name), kind)] for name, kind in columns
                if name not in NON_IDENTITY]
    role = row.get('image_role')
    valid_meta = (role in ROLES and present(row.get('image_display_notice')) and
                  isinstance(row.get('image_asset_sha256'), str) and
                  re.fullmatch('[0-9a-f]{64}', row['image_asset_sha256']) is not None and
                  present(row.get('image_assignment_run')))
    return (row['barcode'], row['product_id'], hashed(identity),
            int(present(row.get('image_url'))), hashed(row.get('image_url')),
            role if role in ROLES else None, int(valid_meta),
            int(present(row.get('nutrition_basis_raw'))), hashed(row.get('nutrition_basis_raw')),
            hashed(row.get('product_group_key')), hashed(row.get('attribute_snapshot_id')),
            hashed([row.get(name) for name in IMAGE_META]))


def build(source, destination, state, expected_sql_sha=SQL_SHA, expected_rows=SOURCE_ROWS):
    destination = Path(destination)
    need(not destination.exists() and not destination.is_symlink(), 'OUTPUT_ALREADY_EXISTS')
    columns = [(r['column'], r['type']) for r in state['columns'] if r['table'] == 'products']
    need(len(columns) == len(set(n for n, _ in columns)) and
         NON_IDENTITY <= {n for n, _ in columns}, 'SOURCE_COLUMNS')
    con = sqlite3.connect(destination)
    con.execute('PRAGMA cache_size=-32768')
    con.execute('PRAGMA temp_store=FILE')
    con.execute('''CREATE TABLE products(barcode TEXT PRIMARY KEY COLLATE BINARY,
        product_id INTEGER NOT NULL UNIQUE, identity_hash BLOB NOT NULL,
        image_present INTEGER NOT NULL, image_hash BLOB NOT NULL, image_role TEXT,
        image_meta_valid INTEGER NOT NULL, basis_present INTEGER NOT NULL, basis_hash BLOB NOT NULL,
        group_hash BLOB NOT NULL, snapshot_hash BLOB NOT NULL, image_meta_hash BLOB NOT NULL)''')
    con.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    digest = hashlib.sha256()
    counts = dict(source_rows=0, source_image_filled=0, source_basis_filled=0,
                  source_representative=0, source_category_reference=0, source_bad_assigned_metadata=0)
    product_ddl = []
    in_ddl = False
    try:
        with gzip.open(source, 'rb') as stream:
            while True:
                line = stream.readline(16*1024*1024+1)
                if not line:
                    break
                need(len(line) <= 16*1024*1024, 'SQL_LINE_LIMIT')
                digest.update(line)
                if line.startswith(b'CREATE TABLE `products` ('):
                    need(not product_ddl, 'DUPLICATE_PRODUCTS_DDL')
                    in_ddl = True
                if in_ddl:
                    product_ddl.append(line)
                    if line.startswith(b') ENGINE='):
                        in_ddl = False
                if line.startswith(b'INSERT INTO `products` VALUES '):
                    for row in parse_rows(line, columns):
                        value = fingerprint(row, columns)
                        con.execute('INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', value)
                        counts['source_rows'] += 1
                        need(counts['source_rows'] <= expected_rows, 'SOURCE_ROW_LIMIT')
                        counts['source_image_filled'] += value[3]
                        counts['source_basis_filled'] += value[7]
                        counts['source_representative'] += value[5] == 'PRODUCT_REPRESENTATIVE'
                        counts['source_category_reference'] += value[5] == 'CATEGORY_REFERENCE'
                        counts['source_bad_assigned_metadata'] += value[5] in ROLES and not value[6]
        need(digest.hexdigest() == expected_sql_sha, 'SOURCE_SQL_HASH')
        need(counts['source_rows'] == expected_rows and product_ddl and not in_ddl, 'SOURCE_INCOMPLETE')
        for name, value in [('format', FORMAT), ('sql_sha256', expected_sql_sha),
                            ('columns', columns), ('counts', counts),
                            ('product_ddl_sha256', hashlib.sha256(b''.join(product_ddl)).hexdigest())]:
            con.execute('INSERT INTO metadata VALUES (?,?)', (name, json.dumps(value, ensure_ascii=False)))
        con.commit()
        need(con.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'SIDECAR_INTEGRITY')
        return counts
    finally:
        con.close()


class Comparison:
    """Exact matching only. Proposed counts are neither an UPDATE nor approval."""
    def __init__(self, source):
        self.con = sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro', uri=True)
        self.con.execute('PRAGMA query_only=ON')
        metadata = dict(self.con.execute('SELECT key,value FROM metadata'))
        self.meta = {k: json.loads(v) for k, v in metadata.items()}
        need(self.meta['format'] == FORMAT, 'SIDECAR_FORMAT')
        self.columns = self.meta['columns']
        self.counts = dict(operating_rows=0, operating_only=0, shared_barcode=0,
            id_conflict=0, identity_conflict=0, exact_identity=0, snapshot_difference=0,
            group_difference=0, image_existing_preserved=0, image_existing_differs=0,
            image_fill_representative_candidate=0, image_fill_category_candidate=0,
            image_fill_bad_metadata_held=0, image_both_missing=0,
            basis_both_missing=0, basis_same=0, basis_fill_candidate=0,
            basis_existing_preserved=0, basis_conflict_held=0)
        self.seen = set()
        self.last_barcode = None
        self.proof = hashlib.sha256()

    def consume(self, row):
        value = fingerprint(row, self.columns)
        barcode, product_id = value[:2]
        need(barcode != self.last_barcode, 'DUPLICATE_OPERATING_BARCODE')
        self.last_barcode = barcode
        need(product_id not in self.seen, 'DUPLICATE_OPERATING_ID')
        self.seen.add(product_id)
        self.proof.update(canonical([barcode, product_id, *[x.hex() if isinstance(x, bytes) else x for x in value[2:]]]))
        c = self.counts
        c['operating_rows'] += 1
        source = self.con.execute('SELECT * FROM products WHERE barcode=? COLLATE BINARY', (barcode,)).fetchone()
        if source is None:
            c['operating_only'] += 1
            return
        c['shared_barcode'] += 1
        if source[1] != product_id:
            c['id_conflict'] += 1
            return
        if source[2] != value[2]:
            c['identity_conflict'] += 1
            return
        c['exact_identity'] += 1
        c['snapshot_difference'] += source[10] != value[10]
        c['group_difference'] += source[9] != value[9]
        if value[3]:
            c['image_existing_preserved'] += 1
            c['image_existing_differs'] += source[4] != value[4]
        elif source[3]:
            if not source[6] or source[5] not in ROLES:
                c['image_fill_bad_metadata_held'] += 1
            else:
                c['image_fill_representative_candidate' if source[5] == 'PRODUCT_REPRESENTATIVE'
                  else 'image_fill_category_candidate'] += 1
        else:
            c['image_both_missing'] += 1
        if not value[7] and not source[7]:
            c['basis_both_missing'] += 1
        elif not value[7]:
            c['basis_fill_candidate'] += 1
        elif not source[7]:
            c['basis_existing_preserved'] += 1
        elif source[8] == value[8]:
            c['basis_same'] += 1
        else:
            c['basis_conflict_held'] += 1

    def finish(self):
        c = dict(self.counts)
        c['source_only'] = self.meta['counts']['source_rows']-c['shared_barcode']
        need(c['source_only'] >= 0, 'DUPLICATE_OPERATING_BARCODE')
        return {'counts': {**self.meta['counts'], **c},
                'hashes': {'operating_projection': self.proof.hexdigest()}}

    def close(self):
        self.con.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        counts = build(args.source, args.output, json.loads(Path(args.state).read_bytes()))
        print(json.dumps({'status': 'LOCAL_FINGERPRINTS_READY', 'counts': counts}))
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch('[A-Z_]{1,70}', str(error)) else type(error).__name__
        print(json.dumps({'status': 'STOPPED_KEEP_OUTPUT', 'code': code}))
        raise SystemExit(1)
