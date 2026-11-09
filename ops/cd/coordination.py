"""One host-wide lock and durable mutation record across both CDs and manual work."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat

ROOT = Path('/var/lib/jjikmuk-operations')
TERMINAL = {'IDLE','SUCCEEDED','ROLLED_BACK','REJECTED','VERIFIED','INSTALLED_DISABLED'}
STATES = TERMINAL | {'PREPARING','MUTATION_INTENT','SWITCH_INTENT','ROLLBACK_INTENT','MANUAL_RECOVERY_REQUIRED'}


def need(ok, code):
    if not ok: raise ValueError(code)


def secure(path, owner=0):
    s=path.lstat()
    need(not path.is_symlink() and s.st_uid==owner and not s.st_mode & 0o022,'UNTRUSTED_COORDINATOR_PATH')
    need(stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode),'COORDINATOR_FILE_TYPE')


def atomic(path, value):
    temporary=path.with_name(path.name+'.next')
    with temporary.open('x',encoding='utf-8') as f:
        os.chmod(temporary,0o600)
        json.dump(value,f,sort_keys=True);f.flush();os.fsync(f.fileno())
    os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def initialize(root=ROOT, owner=0):
    """Only the separately approved initial installer calls this, never a CD run."""
    need(not root.exists() and not root.is_symlink(),'COORDINATOR_ALREADY_EXISTS')
    for parent in [root.parent,*root.parent.parents]:secure(parent,owner)
    root.mkdir(mode=0o700)
    (root/'history').mkdir(mode=0o700)
    with (root/'host.lock').open('x') as f:
        os.chmod(root/'host.lock',0o600);f.flush();os.fsync(f.fileno())
    atomic(root/'state.json',{'status':'IDLE'})


class Guard:
    def __init__(self,root,component,operation_id):
        self.root=root;self.component=component;self.operation_id=operation_id
        self.status='PREPARING';self.record('PREPARING')

    def record(self,status):
        need(status in STATES,'COORDINATOR_STATE_REJECTED')
        value={'status':status,'component':self.component,'operation_id':self.operation_id}
        # Preserve all transition records; no journal deletion or replay.
        history=self.root/'history'/self.operation_id
        history.mkdir(mode=0o700,exist_ok=True)
        count=len(list(history.glob('*.json')))
        need(count<50,'COORDINATOR_TRANSITION_LIMIT')
        atomic(history/f'{count:02d}.json',value)
        atomic(self.root/'state.json',value)
        self.status=status


@contextmanager
def locked(component, operation_id, *, root=None, owner=0, recovery_sha256=None):
    import fcntl
    root=ROOT if root is None else Path(root)
    need(component in {'backend','chatbot','ocr','db','installation'},'COORDINATOR_COMPONENT')
    need(re.fullmatch('[0-9a-f]{64}',operation_id),'COORDINATOR_OPERATION_ID')
    for path in [root,root/'host.lock',root/'state.json',root/'history']:secure(path,owner)
    with (root/'host.lock').open('r+') as f:
        try: fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('HOST_OPERATION_BUSY') from None
        raw=(root/'state.json').read_bytes();need(len(raw)<4096,'COORDINATOR_STATE_LIMIT')
        state=json.loads(raw);need(state.get('status') in STATES,'COORDINATOR_STATE_INVALID')
        if state['status'] not in TERMINAL:
            need(recovery_sha256 is not None and hashlib.sha256(raw).hexdigest()==recovery_sha256,
                 'UNRESOLVED_HOST_OPERATION')
        else: need(recovery_sha256 is None,'RECOVERY_STATE_CHANGED')
        need(not (root/'history'/operation_id).exists(),'OPERATION_ALREADY_RECORDED_NO_REPLAY')
        guard=Guard(root,component,operation_id)
        try:
            yield guard
        except BaseException:
            if guard.status=='PREPARING':guard.record('REJECTED')
            raise
        else:
            # An omitted completion is not a successful operation.
            need(guard.status in TERMINAL,'OPERATION_COMPLETION_NOT_RECORDED')
