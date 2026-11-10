"""Guard original Flyway execution and settle only its registered DB sessions."""
import base64
import json
import os
import re
import signal
import subprocess
import threading
import time
from manifest import require


def owned_ids(path, uid):
    st=path.lstat()
    require(not path.is_symlink() and st.st_uid==uid and st.st_mode & 0o777==0o600
            and st.st_size <= 4096, 'FLYWAY_CONNECTION_JOURNAL_CHANGED')
    raw=path.read_text(encoding='ascii')
    require(not raw or re.fullmatch(r'(?:[1-9][0-9]{0,18}\n){1,32}',raw), 'FLYWAY_CONNECTION_JOURNAL_INVALID')
    values=[int(x) for x in raw.splitlines()]
    require(len(values)==len(set(values)),'FLYWAY_CONNECTION_ID_REUSED')
    return values


def settle(open_control, ids, record, *, cancel, timeout=600):
    deadline=time.monotonic()+timeout
    attempted=set()
    pending=set(ids)
    while pending and time.monotonic()<deadline:
        try:
            with open_control() as conn, conn.cursor() as cur:
                for identity in sorted(pending):
                    cur.execute('SELECT ID,DB,USER=SUBSTRING_INDEX(CURRENT_USER(),%s,1) FROM information_schema.PROCESSLIST WHERE ID=%s',('@',identity))
                    rows=cur.fetchall()
                    if not rows:
                        pending.remove(identity)
                        continue
                    require(rows==((identity,'jjikmuk',1),) or rows==[(identity,'jjikmuk',1)],
                            'FLYWAY_SESSION_OWNERSHIP_UNCERTAIN')
                    if cancel and identity not in attempted:
                        record({'status':'FLYWAY_CANCEL_INTENT','connection_id':identity})
                        attempted.add(identity)
                        cur.execute('KILL CONNECTION '+str(identity))
        except ValueError:
            raise
        except Exception:
            # Retry observation only, never resend a cancellation with unknown outcome.
            pass
        if pending:time.sleep(2)
    require(not pending,'FLYWAY_SESSIONS_UNSETTLED_KEEP_SERVICES_STOPPED')
    record({'status':'FLYWAY_SESSIONS_ENDED','connection_ids':ids})


def stop_child(child):
    for sig, seconds in ((signal.SIGTERM,2),(signal.SIGKILL,5)):
        try:os.killpg(child.pid,sig)
        except ProcessLookupError:pass
        try:
            child.wait(timeout=seconds)
        except subprocess.TimeoutExpired:pass
    require(child.poll() is not None,'FLYWAY_PROCESS_NOT_STOPPED')


def apply(stage,props,guard,open_control,record):
    import pwd
    guard()
    user=pwd.getpwnam('ubuntu')
    folder=stage/'flyway-owned'
    folder.mkdir(mode=0o700)
    os.chown(folder,user.pw_uid,user.pw_gid)
    registry=folder/'connections'
    with registry.open('xb'):pass
    os.chmod(registry,0o600);os.chown(registry,user.pw_uid,user.pw_gid)
    data=b'\n'.join(base64.b64encode(props[k].encode()) for k in
        ('spring.datasource.url','spring.datasource.username','spring.datasource.password'))+b'\n'
    args=['/usr/sbin/runuser','-u','ubuntu','--','/usr/bin/java','-Xms32m','-Xmx192m',
          '-cp',str(stage/'lib/*')+':'+str(stage/'bin/java'),'InitialSchema',str(stage)]
    record({'status':'ORIGINAL_FLYWAY_INTENT'})
    output=[]
    failed=[]
    with subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            start_new_session=True,cwd='/',env={'PATH':'/usr/bin:/bin','LANG':'C'}) as child:
        def communicate():
            try:output.append(child.communicate(data))
            except BaseException:failed.append(True)
        worker=threading.Thread(target=communicate,daemon=True);worker.start()
        deadline=time.monotonic()+180
        stopped=False
        process_failure=None
        try:
            while worker.is_alive():
                worker.join(timeout=1)
                guard()
                require(time.monotonic()<deadline,'FLYWAY_EXECUTION_TIMEOUT')
        except BaseException:
            stopped=True
            try:stop_child(child)
            except BaseException as error:process_failure=type(error).__name__
            worker.join(timeout=5)
        finally:
            ids=owned_ids(registry,user.pw_uid)
            settle(open_control,ids,record,cancel=stopped or child.returncode!=0 or bool(failed))
        require(not worker.is_alive() and process_failure is None,'FLYWAY_PROCESS_UNSETTLED')
        require(not stopped and not failed and child.returncode==0,'ORIGINAL_FLYWAY_STOPPED_KEEP_RECORDS')
    require(len(output)==1 and len(output[0][0])<4096 and len(output[0][1])<4096,'FLYWAY_OUTPUT_LIMIT')
    require(json.loads(output[0][0])=={'status':'SCHEMA_PREPARED','migrations':4},'FLYWAY_RESULT_UNEXPECTED')
    guard()
