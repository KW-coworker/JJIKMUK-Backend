"""Disposable Linux CI failure injection: detached descendants must be killed."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

assert os.geteuid() == 0
with tempfile.TemporaryDirectory(prefix='jjikmuk-initial-timeout-') as td:
    marker = str(Path(td) / 'orphan-wrote')
    started = str(Path(td) / 'child-started')
    child = "import signal,time,pathlib;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path(" + repr(started) + ").write_text('started');time.sleep(5);pathlib.Path(" + repr(marker) + ").write_text('failed')"
    parent = "import subprocess,sys,time;assert sys.stdin.buffer.read()==b'pipe-proof';print('PIPE_OK',flush=True);subprocess.Popen([sys.executable,'-c'," + repr(child) + "],start_new_session=True);time.sleep(20)"
    result = subprocess.run(['/usr/bin/systemd-run', '--quiet', '--wait', '--pipe', '--collect',
        '--service-type=exec', '--unit=jjikmuk-ci-timeout-' + uuid.uuid4().hex,
        '--property=RuntimeMaxSec=1', '--property=TimeoutStartSec=30',
        '--property=TimeoutStopSec=1', '--property=KillMode=control-group',
        '--property=Restart=no', sys.executable, '-c', parent], input=b'pipe-proof', capture_output=True, timeout=15)
    assert b'PIPE_OK' in result.stdout and Path(started).read_text() == 'started', 'transient service did not actually run'
    assert result.returncode != 0
    time.sleep(5.2)
    assert not Path(marker).exists(), 'detached child survived cgroup timeout'
print('SYSTEMD_TIMEOUT_KILLS_DETACHED_DESCENDANTS_PASSED')

# A completely stopped JVM-style process can retain a systemd failed state.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from initial_service_state import stopped
def command(*args):
    r=subprocess.run(['systemctl',*args],capture_output=True,text=True,timeout=15)
    assert r.returncode==0
    return r.stdout.strip()
with tempfile.TemporaryDirectory(prefix='jjikmuk-stop-exit-') as td:
    ready=Path(td)/'ready';unit='jjikmuk-ci-stop-'+uuid.uuid4().hex+'.service'
    code="import signal,sys,time,pathlib;signal.signal(signal.SIGTERM,lambda a,b:sys.exit(143));pathlib.Path("+repr(str(ready))+").touch();time.sleep(60)"
    try:
        subprocess.run(['systemd-run','--quiet','--unit='+unit,'--service-type=exec',
            '--property=Restart=always','--property=RestartSec=1','--property=TimeoutStopSec=5',
            sys.executable,'-c',code],check=True,capture_output=True,timeout=15)
        deadline=time.monotonic()+5
        while not ready.exists() and time.monotonic()<deadline:time.sleep(.05)
        assert ready.exists()
        command('stop',unit)
        assert command('show',unit,'--property=ExecMainStatus','--value')=='143'
        state=stopped((unit,),command)[unit]
        assert state['ActiveState']=='failed' and state['SubState']=='failed'
        time.sleep(2)
        assert stopped((unit,),command)[unit]==state
    finally:
        subprocess.run(['systemctl','stop',unit],capture_output=True,timeout=15)
        # Only this disposable CI unit is reset; no production unit is changed.
        subprocess.run(['systemctl','reset-failed',unit],capture_output=True,timeout=15)
print('SYSTEMD_FAILED_EXIT143_WITH_EMPTY_PROCESSES_ACCEPTED_NO_AUTORESTART_PASSED')
