"""Small, explicit image replacements. No catalog scans, schema changes or retries."""
import hashlib
import json
from urllib.parse import urlsplit


def require(ok, code):
    if not ok:
        raise ValueError(code)


def validate(items):
    require(type(items) is list and 1 <= len(items) <= 200, 'IMAGE_PATCH_COUNT')
    keys = {'product_id', 'barcode', 'product_name', 'manufacturer', 'old_image_url', 'image_url'}
    for item in items:
        require(type(item) is dict and set(item) == keys, 'IMAGE_PATCH_FIELDS')
        require(type(item['product_id']) is int and item['product_id'] > 0, 'IMAGE_PATCH_ID')
        for name in keys - {'product_id'}:
            value = item[name]
            nullable = name in ('product_name', 'manufacturer', 'old_image_url')
            require(value is None and nullable or
                    type(value) is str and (nullable or len(value) > 0) and len(value) <= (2000 if 'url' in name else 1000)
                    and not any(ord(c) < 32 for c in value), 'IMAGE_PATCH_TEXT')
        require(len(item['barcode']) <= 255 and item['image_url'] != item['old_image_url'], 'IMAGE_PATCH_UNCHANGED')
        url = urlsplit(item['image_url'])
        require(url.scheme == 'https' and url.hostname and not url.username and not url.password
                and not url.fragment and url.port in (None, 443), 'IMAGE_PATCH_URL')
    require(len({x['product_id'] for x in items}) == len(items)
            and len({x['barcode'] for x in items}) == len(items), 'IMAGE_PATCH_DUPLICATE')
    return sorted(items, key=lambda x: x['barcode'])


def plain(row):
    return {k: int.from_bytes(v, 'big') if isinstance(v, bytes) else v for k, v in row.items()}


def apply(connection, items, codec, save_before, save_intent, dataset):
    items = validate(items)
    require(dataset.startswith('image-patch-') and len(dataset) <= 100, 'IMAGE_PATCH_DATASET')
    rows, previous = [], []
    committed = False
    try:
        with connection.cursor() as cur:
            cur.execute('SET SESSION innodb_lock_wait_timeout=5,lock_wait_timeout=5,MAX_EXECUTION_TIME=10000')
        connection.begin()
        with connection.cursor() as cur:
            for item in items:
                cur.execute('SELECT * FROM products WHERE barcode=%s FOR UPDATE', (item['barcode'],))
                found = cur.fetchall()
                require(len(found) == 1, 'IMAGE_PATCH_PRODUCT_MISSING')
                row = plain(found[0])
                require(all(row[k] == item[k] for k in ('product_id', 'barcode', 'product_name', 'manufacturer')),
                        'IMAGE_PATCH_IDENTITY')
                require(row['image_url'] == item['old_image_url'], 'IMAGE_PATCH_OLD_URL_CHANGED')
                # Do not leave metadata describing a previous picture or invent a role.
                require(all(row[k] is None for k in ('image_role', 'image_display_notice',
                        'image_asset_sha256', 'image_assignment_run')), 'IMAGE_PATCH_EXISTING_METADATA')
                prior = None
                if row['attribute_snapshot_id'] is not None:
                    cur.execute('SELECT product_id,payload_hash,payload_json FROM product_attribute_snapshots WHERE id=%s',
                                (row['attribute_snapshot_id'],))
                    prior = cur.fetchone()
                    require(prior is not None and prior['product_id'] == row['product_id'] and
                            hashlib.sha256(prior['payload_json'].encode()).hexdigest() == prior['payload_hash'],
                            'IMAGE_PATCH_PRIOR_SNAPSHOT')
                rows.append(row)
                previous.append(prior)
            encoded = codec([{'row': dict(row, image_url=item['image_url']),
                              'previous': prior['payload_json'] if prior else None}
                             for row, item, prior in zip(rows, items, previous)])
            require(len(encoded) == len(rows), 'IMAGE_PATCH_CODEC_COUNT')
            for value in encoded:
                require(set(value) == {'payload_json', 'payload_hash', 'changed_fields', 'group_key'} and
                        hashlib.sha256(value['payload_json'].encode()).hexdigest() == value['payload_hash'] and
                        len(value['group_key']) == 64, 'IMAGE_PATCH_CODEC_RESULT')
            save_before({'items': items, 'rows': rows, 'dataset': dataset})
            expected = []
            for row, item, value in zip(rows, items, encoded):
                cur.execute('INSERT INTO product_attribute_snapshots '
                    '(product_id,previous_snapshot_id,dataset_version,observed_at,observed_by,rule_version,'
                    'change_reason,changed_fields,payload_hash,payload_json) '
                    'VALUES (%s,%s,%s,NOW(6),%s,%s,%s,%s,%s,%s)',
                    (row['product_id'], row['attribute_snapshot_id'], dataset, 'USER_IMAGE_PATCH',
                     'catalog-observation-v1', 'User requested product image URL replacement',
                     value['changed_fields'], value['payload_hash'], value['payload_json']))
                snapshot_id = cur.lastrowid
                require(type(snapshot_id) is int and snapshot_id > 0, 'IMAGE_PATCH_SNAPSHOT_ID')
                cur.execute('UPDATE products SET image_url=%s,product_group_key=%s,attribute_snapshot_id=%s '
                            'WHERE barcode=%s AND product_id=%s AND BINARY image_url <=> BINARY %s',
                            (item['image_url'], value['group_key'], snapshot_id, row['barcode'],
                             row['product_id'], row['image_url']))
                require(cur.rowcount == 1, 'IMAGE_PATCH_UPDATE_COUNT')
                wanted = dict(row, image_url=item['image_url'], product_group_key=value['group_key'],
                              attribute_snapshot_id=snapshot_id)
                cur.execute('SELECT * FROM products WHERE barcode=%s', (row['barcode'],))
                require(plain(cur.fetchone()) == wanted, 'IMAGE_PATCH_READBACK')
                expected.append(wanted)
            save_intent({'rows': expected, 'dataset': dataset})
            connection.commit()
            committed = True
        # Independent transaction after commit. Never replay an uncertain commit.
        with connection.cursor() as cur:
            for row in expected:
                cur.execute('SELECT * FROM products WHERE barcode=%s', (row['barcode'],))
                require(plain(cur.fetchone()) == row, 'IMAGE_PATCH_COMMITTED_READBACK')
        connection.rollback()
        return {'products_updated': len(rows), 'snapshots_added': len(rows)}
    except BaseException:
        if not committed:
            try:
                connection.rollback()
            except Exception:
                pass
        raise
