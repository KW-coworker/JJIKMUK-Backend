"""Non-root, read-only candidate startup checks; never execute FastAPI lifespan."""
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys


def main():
    raw = sys.stdin.buffer.read(131073)
    assert len(raw) <= 131072 and os.geteuid() == 999 and sys.version_info[:3] == (3, 13, 16)
    request = json.loads(raw)
    source = Path(request['source'])
    assert str(source) == '/opt/jjikmuk-chatbot/releases/3d0be58e601281d22aef8e08a20e6d9642a48f36-43058384792-1/AI'
    assert set(request) == {'source', 'environment', 'database_addresses'}
    os.environ.clear(); os.environ.update(request['environment'])
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source))
    allowed = set(request['database_addresses'])
    assert allowed and all(re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,3}){3}', address) for address in allowed)

    def audit(event, args):
        if event == 'socket.connect':
            address = args[1]
            if not (isinstance(address, tuple) and address[0] in allowed and address[1] == 3306):
                raise PermissionError('CANDIDATE_EXTERNAL_NETWORK_BLOCKED')
        if event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'):
            raise PermissionError('CANDIDATE_CHILD_PROCESS_BLOCKED')
    sys.addaudithook(audit)
    from packaging.requirements import Requirement
    missing, wrong = [], []
    for line in (source / 'requirements.txt').read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            version = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(requirement.name); continue
        if version not in requirement.specifier:
            wrong.append(requirement.name)
    report = {'status': 'OK', 'checks': {'dependencies_match': not (missing or wrong)},
              'counts': {'dependency_missing': len(missing), 'dependency_version_mismatch': len(wrong)}, 'codes': []}
    if missing or wrong:
        report['codes'] = ['DEPENDENCY_' + re.sub('[^A-Z0-9]', '_', name.upper()) for name in (missing + wrong)[:30]]
        return report
    # Enforce read-only SQL for every physical connection before the original
    # repository code can issue a query. These temporary session settings do not
    # modify DB data or the running service's sessions.
    import pymysql
    original = pymysql.connect
    connections = []

    def readonly_connect(*args, **kwargs):
        assert not args and kwargs['host'] == 'jjikmuk-dev-db.cp22o82i4ex5.ap-northeast-2.rds.amazonaws.com'
        assert kwargs['database'] == 'jjikmuk' and kwargs.get('port', 3306) == 3306
        conn = original(**kwargs)
        try:
            with conn.cursor() as cursor:
                cursor.execute('SET SESSION TRANSACTION READ ONLY')
                cursor.execute('SET SESSION MAX_EXECUTION_TIME=10000')
            connections.append(conn)
            return conn
        except BaseException:
            conn.close(); raise
    pymysql.connect = readonly_connect
    try:
        from app.infrastructure.rag import get_rag_status
        rag = get_rag_status(verify_retriever=False)
        report['checks']['existing_rag_current'] = bool(rag.get('retriever_ready') and not rag.get('index_stale'))
        report['counts']['rag_document_count'] = int(rag.get('document_count') or 0)
        # No lifespan, ChatRequest, vectorstore open, rebuild, embedding or generation.
        from app.api.main import configure_repositories, readiness
        configure_repositories()
        response = readiness(); value = json.loads(response.body)
        report['checks']['candidate_ready'] = response.status_code == 200 and value.get('ready') is True
        for key in ('deployment_boundary_valid', 'product_repository_available',
                    'activity_repository_available', 'conversation_repository_available'):
            report['checks'][key] = value.get(key) is True
        report['codes'] = [code.upper() for code in value.get('deployment_boundary_error_codes', [])
                           if re.fullmatch('[a-z][a-z0-9_]{0,79}', code)][:30]
        return report
    finally:
        support = sys.modules.get('app.infrastructure.mysql_support')
        if support is not None:
            support.dispose_mysql_connection_pools()
        for conn in connections:
            if getattr(conn, 'open', False):
                conn.close()


if __name__ == '__main__':
    # Keep imported library output out of the machine-readable, sanitized result.
    result_fd = os.dup(1)
    os.dup2(2, 1)
    exit_code = 0
    try:
        result = main()
    except Exception as error:
        result = {'status': 'PREFLIGHT_FAILED', 'codes': ['CANDIDATE_PROBE_' + type(error).__name__.upper()]}
        exit_code = 1
    with os.fdopen(result_fd, 'w') as stream:
        print(json.dumps(result), file=stream)
    raise SystemExit(exit_code)
