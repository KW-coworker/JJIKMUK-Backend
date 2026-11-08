"""SELECT-only Flyway probe, executed by an existing approved PyMySQL environment.

The approved properties file must use simple literal key=value syntax. Ambiguous
Java escapes/placeholders are rejected rather than reinterpreting credentials.
"""
import json
from pathlib import Path
import sys
import re
from urllib.parse import urlsplit


def properties(path):
    result = {}
    for raw in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', '!')): continue
        if '=' not in line: raise ValueError('UNSUPPORTED_PROPERTIES_SYNTAX')
        key, value = line.split('=', 1)
        key = key.strip(); value = value.strip()
        compact = re.sub('[^a-z0-9]', '', key.lower())
        datasource = {'spring.datasource.url','spring.datasource.username','spring.datasource.password',
                      'spring.datasource.driver-class-name'}
        jpa = {'spring.jpa.hibernate.ddl-auto','spring.jpa.show-sql',
               'spring.jpa.properties.hibernate.format_sql','spring.jpa.properties.hibernate.jdbc.batch_size',
               'spring.jpa.properties.hibernate.order_inserts','spring.jpa.properties.hibernate.order_updates'}
        flyway = {'spring.flyway.enabled','spring.flyway.locations','spring.flyway.baseline-on-migrate','spring.flyway.baseline-version'}
        if ((compact.startswith('springdatasource') and key not in datasource) or
            (compact.startswith('springjpa') and key not in jpa) or
            (compact.startswith('springflyway') and key not in flyway) or
            compact.startswith(('springconfig','springprofiles','springsql','springliquibase','springbatch'))):
            raise ValueError('UNSUPPORTED_DATABASE_OVERRIDE')
        if key.startswith(('spring.datasource.', 'spring.flyway.', 'spring.jpa.', 'spring.config.', 'spring.profiles.')) or key.endswith('.enabled'):
            if key in result or '\\' in value or '${' in value: raise ValueError('AMBIGUOUS_DATABASE_PROPERTIES')
            result[key] = value
    return result


def probe(config):
    import pymysql
    db = config['database']
    props = properties(db['properties_file'])
    # Match the approved app DB URL; do not silently probe a different database.
    if props.get('spring.datasource.url') != db['expected_jdbc_url']: raise ValueError('DATABASE_URL_CHANGED')
    target = urlsplit(db['expected_jdbc_url'].removeprefix('jdbc:'))
    if (not db['expected_jdbc_url'].startswith('jdbc:mysql://') or target.username or target.password or
            target.hostname != db['host'] or (target.port or 3306) != 3306 or target.path != '/' + db['name']):
        raise ValueError('DATABASE_TARGET_MISMATCH')
    with pymysql.connect(host=db['host'], port=3306, database=db['name'],
                         user=props['spring.datasource.username'], password=props['spring.datasource.password'],
                         ssl_ca=db['ca_file'], ssl_verify_cert=True, ssl_verify_identity=True,
                         connect_timeout=5, read_timeout=10, write_timeout=5, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT version, script, checksum, success, type FROM flyway_schema_history ORDER BY installed_rank')
            rows = cur.fetchmany(102)
            if len(rows) > 101: raise ValueError('DATABASE_HISTORY_LIMIT')
    return [dict(version=v, script=s, checksum=c, success=bool(ok), type=t) for v, s, c, ok, t in rows]


if __name__ == '__main__':
    try:
        print(json.dumps(probe(json.load(sys.stdin))))
    except Exception:
        print('DATABASE_PROBE_FAILED', file=sys.stderr)
        raise SystemExit(1)
