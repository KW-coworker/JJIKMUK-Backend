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
