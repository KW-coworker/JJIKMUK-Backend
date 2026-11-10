"""Local disposable CI MySQL rehearsal using the exact application's libraries."""
from pathlib import Path
import subprocess
import sys
import zipfile

repo = Path(__file__).resolve().parents[3]
jars = [p for p in (repo / 'build/libs').glob('*.jar') if not p.name.endswith('-plain.jar')]
assert len(jars) == 1
stage = repo / 'build/schema-rehearsal'
stage.mkdir()
for name in ('lib', 'sql', 'classes'):
    (stage / name).mkdir()
with zipfile.ZipFile(jars[0]) as z:
    for item in z.infolist():
        if item.filename.startswith('BOOT-INF/lib/') and item.filename.endswith('.jar'):
            (stage / 'lib' / Path(item.filename).name).write_bytes(z.read(item))
        if item.filename.startswith('BOOT-INF/classes/db/migration/') and item.filename.endswith('.sql'):
            (stage / 'sql' / Path(item.filename).name).write_bytes(z.read(item))
subprocess.run(['javac', '-cp', str(stage / 'lib/*'), '-d', str(stage / 'classes'),
                str(repo / 'ops/cd/java/InitialSchema.java'),
                str(repo / 'ops/cd/tests/java/InitialSchemaRehearsal.java'),
                str(repo / 'ops/cd/tests/java/V17FulltextRehearsal.java')], check=True, timeout=60)
subprocess.run(['java', '-cp', str(stage / 'lib/*') + ':' + str(stage / 'classes'),
                'V17FulltextRehearsal', str(stage / 'sql/V17__preserve_product_nutrition_basis.sql')], check=True, timeout=60)
subprocess.run(['java', '-cp', str(stage / 'lib/*') + ':' + str(stage / 'classes'),
                'InitialSchemaRehearsal', str(stage)], check=True, timeout=120)
sys.path.insert(0, str(repo / 'ops/cd'))
import pymysql
from initial_schema import read_from_connection
from initial_schema_contract import verify_new_tables
with pymysql.connect(host='127.0.0.1', port=3306, database='jjikmuk', user='root',
                      password='rehearsal_only', autocommit=True) as conn:
    verify_new_tables(read_from_connection(conn))
print('MYSQL_REAL_COLUMNS_DEFAULTS_INDEXES_AND_FOREIGN_KEYS_PASSED')

# Exercise preservation against real MySQL conversions, including NULL and binary.
from initial_preservation import capture, verify
with pymysql.connect(host='127.0.0.1', port=3306, database='jjikmuk', user='root',
                      password='rehearsal_only', autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute('CREATE TABLE preservation_fixture (id BIGINT PRIMARY KEY, text_value VARCHAR(30), binary_value BLOB)')
        cur.execute("INSERT INTO preservation_fixture VALUES (1,'A',X'00'),(2,NULL,NULL),(3,'한글',X'0001')")
    shape = {'preservation_fixture': {'columns': ['id', 'text_value', 'binary_value'], 'primary_key': ['id']}}
    def sample():
        return capture(conn, shape, 17, lambda: None, cursor_class=pymysql.cursors.SSCursor)
    before = sample()
    for mutation, undo in [
            ("UPDATE preservation_fixture SET text_value='a' WHERE id=1", "UPDATE preservation_fixture SET text_value='A' WHERE id=1"),
            ("UPDATE preservation_fixture SET text_value='' WHERE id=2", "UPDATE preservation_fixture SET text_value=NULL WHERE id=2"),
            ("UPDATE preservation_fixture SET binary_value=X'01' WHERE id=1", "UPDATE preservation_fixture SET binary_value=X'00' WHERE id=1")]:
        with conn.cursor() as cur: cur.execute(mutation)
        try:
            verify(before, sample())
        except ValueError:
            pass
        else:
            raise AssertionError('changed original value escaped preservation proof')
        with conn.cursor() as cur: cur.execute(undo)
        verify(before, sample())
    with conn.cursor() as cur:
        cur.execute('ALTER TABLE preservation_fixture ADD COLUMN new_column BIGINT NOT NULL DEFAULT 0, ALGORITHM=INSTANT')
    verify(before, sample())
print('MYSQL_ORIGINAL_PROJECTION_CASE_NULL_BINARY_AND_ADDITIVE_COLUMN_PROOF_PASSED')

guard_conn = pymysql.connect(host='127.0.0.1', port=3306, database='jjikmuk', user='root',
                            password='rehearsal_only', autocommit=True)
try:
    with guard_conn.cursor() as cur:
        cur.execute("INSERT INTO preservation_fixture(id,text_value) WITH d AS (SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) SELECT 10+a.n+10*b.n+100*c.n+1000*d.n,'cancel-fixture' FROM d a CROSS JOIN d b CROSS JOIN d c CROSS JOIN d")
    checks = [0]
    def fail_after_first_stream_batch():
        checks[0] += 1
        if checks[0] == 2:
            raise ValueError('SYNTHETIC_STALE_GUARD')
    try:
        capture(guard_conn, shape, 17, fail_after_first_stream_batch, cursor_class=pymysql.cursors.SSCursor)
    except ValueError as error:
        assert str(error) == 'SYNTHETIC_STALE_GUARD'
    else:
        raise AssertionError('live guard failure was ignored')
    assert not guard_conn.open
finally:
    if guard_conn.open:
        guard_conn.close()
print('MYSQL_STREAMING_GUARD_FAILURE_CLOSES_CONNECTION_WITHOUT_DRAIN_PASSED')

# Real server cancellation must end the registered session, not just its local thread.
import threading,time
from initial_flyway import settle
def local_connection():
    return pymysql.connect(host='127.0.0.1',port=3306,database='jjikmuk',user='root',
                           password='rehearsal_only',autocommit=True,read_timeout=5)
owned=local_connection();identity=owned.thread_id();outcome=[]
def query():
    try:
        with owned.cursor() as cur:cur.execute('SELECT SLEEP(30)')
    except pymysql.Error:outcome.append('cancelled')
worker=threading.Thread(target=query);worker.start()
time.sleep(.2)
settle(local_connection,[identity],lambda event:None,cancel=True,timeout=10)
worker.join(timeout=5)
assert not worker.is_alive() and outcome==['cancelled']
if owned.open:owned.close()
print('MYSQL_OWNED_SESSION_CANCELLATION_CONFIRMED_ON_SERVER_PASSED')
