"""Host helpers shared by freeze, apply and recovery; no standalone entry point."""
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import threading
import time
import zipfile
from manifest import require,digest
from host import secure,command,atomic_json
from initial_flyway import owned_ids,settle,stop_child

UNITS=('jjikmuk-backend.service','food-chatbot-team.service')


def systemctl(*args):return command(['/usr/bin/systemctl',*args],90)


def chatbot_state():
    unit=UNITS[1]
    pid=systemctl('show',unit,'--property=MainPID','--value')
    require(pid.isdigit() and int(pid)>0,'CATALOG_CHATBOT_PROCESS')
    folder=Path('/proc')/pid
    env=dict(part.split(b'=',1) for part in (folder/'environ').read_bytes().split(b'\0') if b'=' in part)
    for key in (b'INVOCATION_ID',b'JOURNAL_STREAM',b'SYSTEMD_EXEC_PID',b'NOTIFY_SOCKET',b'WATCHDOG_PID',b'WATCHDOG_USEC'):env.pop(key,None)
    h=hashlib.sha256((folder/'cmdline').read_bytes())
    for key,value in sorted(env.items()):h.update(b'\0'+key+b'='+value)
    return {'runtime':h.hexdigest(),'uid':folder.stat().st_uid,'cwd':os.readlink(folder/'cwd')}


def extract_classes(jar,stage):
    root=stage/'classes';root.mkdir(mode=0o755)
    with zipfile.ZipFile(jar) as z:
        for info in z.infolist():
            prefix='BOOT-INF/classes/'
            if not info.filename.startswith(prefix) or not info.filename.endswith('.class'):continue
            name=Path(info.filename[len(prefix):])
            require(not name.is_absolute() and '..' not in name.parts and info.file_size<2*1024**2,'CATALOG_CLASS_PATH')
            path=root/name;path.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
            with path.open('xb') as f:f.write(z.read(info))
            os.chmod(path,0o644)


def migrate(stage,props,guard,open_control,record):
    guard();user=pwd.getpwnam('ubuntu')
    folder=stage/'flyway-owned';folder.mkdir(mode=0o700);os.chown(folder,user.pw_uid,user.pw_gid)
    registry=folder/'connections'
    with registry.open('xb'):pass
    os.chmod(registry,0o600);os.chown(registry,user.pw_uid,user.pw_gid)
    data=b'\n'.join(base64.b64encode(props[k].encode()) for k in
       ('spring.datasource.url','spring.datasource.username','spring.datasource.password'))+b'\n'
    args=['/usr/sbin/runuser','-u','ubuntu','--','/usr/bin/java','-Xms32m','-Xmx192m','-cp',
          str(stage/'lib/*')+':'+str(stage/'bin/java'),'CatalogSchema',str(stage)]
    output=[];failed=[]
    record('V21_FLYWAY_INTENT')
    with subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,
                          cwd='/',env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'}) as child:
        def communicate():
            try:output.append(child.communicate(data))
            except BaseException:failed.append(True)
        thread=threading.Thread(target=communicate,daemon=True);thread.start()
        deadline=time.monotonic()+900;stopped=False
        try:
            while thread.is_alive():
                thread.join(1);guard();require(time.monotonic()<deadline,'CATALOG_DDL_TIMEOUT')
        except BaseException:
            stopped=True;stop_child(child);thread.join(5)
        finally:
            ids=owned_ids(registry,user.pw_uid)
            settle(open_control,ids,lambda event:record(event),cancel=stopped or child.returncode!=0 or bool(failed))
        require(not stopped and not failed and not thread.is_alive() and child.returncode==0,'CATALOG_DDL_UNCERTAIN_NO_RETRY')
    require(len(output)==1 and len(output[0][0])<4096 and not output[0][1] and
            json.loads(output[0][0])=={'status':'SCHEMA_PREPARED','migrations':1},'CATALOG_DDL_RESULT')


def prepare_release(host,stage,candidate):
    release={'manifest':candidate,'protected':host.baseline['protected'],'environment_sha256':host.baseline['environment_sha256']}
    folder=host.release_path(release);folder.mkdir(mode=0o755)
    with (stage/'backend.jar').open('rb') as source,(folder/'backend.jar').open('xb') as output:
        shutil.copyfileobj(source,output);output.flush();os.fsync(output.fileno())
    os.chmod(folder/'backend.jar',0o644);atomic_json(folder/'manifest.json',candidate)
    require(digest(folder/'backend.jar')==candidate['jar_sha256'],'CATALOG_RELEASE_HASH')
    return release


def start_and_enroll(host,release,old_identity,chatbot,record):
    require(host.protected()==release['protected'],'CATALOG_PROTECTED_FILES_CHANGED')
    host.database(release['manifest'])
    record('APP_SWITCH_INTENT');host.activate(release)
    systemctl('start',UNITS[1]);host.restart()
    require(chatbot_state()==chatbot,'CATALOG_CHATBOT_RUNTIME_CHANGED')
    chatbot_identity=systemctl('show',UNITS[1],'--property=InvocationID','--value')
    require(bool(chatbot_identity),'CATALOG_CHATBOT_INVOCATION_REQUIRED')
    host.verify(release,old_identity)
    require(systemctl('show',UNITS[1],'--property=ActiveState','--value')=='active' and
            systemctl('show',UNITS[1],'--property=InvocationID','--value')==chatbot_identity and
            chatbot_state()==chatbot,'CATALOG_CHATBOT_NOT_STABLE')
    host.commit(release);record('APP_VERIFIED_AND_ENROLLED')
