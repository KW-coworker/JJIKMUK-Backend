"""Return only tokens from the fixed public index definition, never application data."""
import re
from readiness_probe import DB_HOST, CA, digest, need


def summarize(ddl):
    need(isinstance(ddl, str) and len(ddl) < 65536, 'INDEX_DDL_LIMIT')
    lines = [x.strip().rstrip(',').strip() for x in ddl.splitlines() if 'FULLTEXT KEY' in x]
    need(len(lines) == 1 and len(lines[0]) <= 512, 'INDEX_DEFINITION_COUNT')
    line = lines[0]
    need(line.startswith('FULLTEXT KEY `ft_products_search_keywords` (`search_keywords`)'), 'INDEX_SCOPE_CHANGED')
    # Tokens expose only the already-scoped index clause. No other DDL or values leave the host.
    tokens = re.findall(r'[A-Za-z_][A-Za-z_0-9]*|[0-9]+', line)
    need(len(tokens) <= 30 and all(len(x) <= 60 for x in tokens), 'INDEX_TOKEN_LIMIT')
    normalized = re.sub(r'\s+', ' ', line).strip()
    expected = 'FULLTEXT KEY `ft_products_search_keywords` (`search_keywords`) /*!50100 WITH PARSER `ngram` */'
    return {'status': 'OK', 'checks': {'normalized_exact_ngram_definition': normalized == expected},
            'counts': {'index_line_length': len(line)},
            'hashes': {'index_line': digest(line.encode())},
            'codes': ['INDEX_TOKEN_' + x.upper() for x in tokens]}


def query(connect, props):
    with connect(host=DB_HOST, port=3306, database='jjikmuk', user=props['spring.datasource.username'],
        password=props['spring.datasource.password'], ssl_ca=CA, ssl_verify_cert=True, ssl_verify_identity=True,
        connect_timeout=5, read_timeout=10, write_timeout=5, autocommit=True, local_infile=False) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute('START TRANSACTION READ ONLY')
                cur.execute('SHOW CREATE TABLE `jjikmuk`.`products`')
                return summarize(cur.fetchone()[1])
        finally:
            conn.rollback()
