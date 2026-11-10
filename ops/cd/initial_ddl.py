"""One guarded, journaled DDL statement on an owned connection. Never retries SQL."""
import threading
import time
from manifest import require


def settle_owned(open_control, connection_id, sql, record, *, cancel, timeout=600):
    """Confirm the exact owned query ended, including after a client failure."""
    deadline = time.monotonic() + timeout
    cancellation_attempted = False
    while time.monotonic() < deadline:
        try:
            with open_control() as control, control.cursor() as cur:
                cur.execute('SELECT ID,DB,INFO,USER=SUBSTRING_INDEX(CURRENT_USER(),%s,1),COMMAND FROM information_schema.PROCESSLIST WHERE ID=%s', ('@', connection_id))
                rows = cur.fetchall()
                if not rows:
                    record({'status':'OWNED_SESSION_ENDED','connection_id':connection_id})
                    return
                require(len(rows) == 1 and rows[0][0] == connection_id
                        and rows[0][1] == 'jjikmuk' and rows[0][3] == 1,
                        'DDL_SESSION_UNCERTAIN_KEEP_SERVICES_STOPPED')
                if rows[0][2] is None and rows[0][4] == 'Sleep':
                    record({'status':'OWNED_QUERY_ENDED','connection_id':connection_id})
                    return
                require(rows[0][2] == sql and rows[0][4] == 'Query',
                        'DDL_SESSION_UNCERTAIN_KEEP_SERVICES_STOPPED')
                if cancel and not cancellation_attempted:
                    record({'status':'DDL_CANCEL_INTENT','connection_id':connection_id,'sql':sql})
                    cancellation_attempted = True
                    cur.execute('KILL QUERY ' + str(connection_id))
        except ValueError:
            raise
        except Exception:
            # Retry only the state observation. A lost cancellation response is never resent.
            pass
        time.sleep(2)
    raise ValueError('DDL_CANCEL_OUTCOME_UNCERTAIN_KEEP_SERVICES_STOPPED')


def guarded_sql(connection, open_control, sql, guard, record, *, timeout=900):
    allowed = {
        'ALTER TABLE products DROP INDEX ft_products_search_keywords, ALGORITHM=INPLACE',
        'OPTIMIZE TABLE products',
        'ALTER TABLE products ADD FULLTEXT KEY ft_products_search_keywords (search_keywords) WITH PARSER ngram',
    }
    require(sql in allowed, 'MAINTENANCE_DDL_NOT_REVIEWED')
    guard()
    connection_id = connection.thread_id()
    require(type(connection_id) is int and 0 < connection_id < 2**63, 'MAINTENANCE_CONNECTION_ID')
    record({'status': 'DDL_INTENT', 'connection_id': connection_id, 'sql': sql})
    result, failure = [], []

    def worker():
        try:
            with connection.cursor() as cur:
                cur.execute(sql)
                result.append(cur.fetchall())
        except BaseException as error:
            # Never retain or log MySQL exception strings, which may contain input data.
            failure.append(type(error).__name__)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    stopped = False
    while thread.is_alive():
        thread.join(timeout=1)
        try:
            require(time.monotonic() < deadline, 'MAINTENANCE_DDL_TIMEOUT')
            guard()
        except BaseException:
            stopped = True
            settle_owned(open_control, connection_id, sql, record, cancel=True)
            thread.join(timeout=30)
            require(not thread.is_alive(), 'DDL_CANCEL_OUTCOME_UNCERTAIN_KEEP_SERVICES_STOPPED')
            break
    if failure:
        settle_owned(open_control, connection_id, sql, record, cancel=True)
    elif not stopped:
        settle_owned(open_control, connection_id, sql, record, cancel=False)
    record({'status': 'DDL_RETURNED', 'connection_id': connection_id, 'sql': sql,
            'stopped': stopped, 'failed': bool(failure)})
    require(not stopped and not failure, 'DDL_STOPPED_VERIFY_STATE_NO_RETRY')
    if sql == 'OPTIMIZE TABLE products':
        rows = result[0]
        require(any(r[2:] == ('status', 'OK') for r in rows)
                and not any(r[2] == 'error' for r in rows), 'PRODUCTS_REBUILD_NOT_CONFIRMED')
    guard()
