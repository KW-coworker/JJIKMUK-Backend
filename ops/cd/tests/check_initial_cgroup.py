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
        '--property=RuntimeMaxSec=1', '--property=JobTimeoutSec=30',
        '--property=TimeoutStopSec=1', '--property=KillMode=control-group',
        '--property=Restart=no', sys.executable, '-c', parent], input=b'pipe-proof', capture_output=True, timeout=15)
    assert b'PIPE_OK' in result.stdout and Path(started).read_text() == 'started', 'transient service did not actually run'
    assert result.returncode != 0
    time.sleep(5.2)
    assert not Path(marker).exists(), 'detached child survived cgroup timeout'
print('SYSTEMD_TIMEOUT_KILLS_DETACHED_DESCENDANTS_PASSED')
