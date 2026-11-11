"""A bounded pipe to the exact candidate JAR's pure Kotlin observation helpers."""
import json
import subprocess
import threading
import time
from catalog_delta import canonical, need


class Codec:
    def __init__(self, args, *, guard=lambda:None):
        self.guard=guard
        self.child=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                    cwd='/',env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})

    def __call__(self, values):
        raw=canonical(values)+b'\n'
        need(0<len(values)<=500 and len(raw)<=16*1024**2,'CATALOG_CODEC_INPUT')
        received=[];failed=[]
        def exchange():
            try:
                self.child.stdin.write(raw);self.child.stdin.flush()
                received.append(self.child.stdout.readline(16*1024**2+1))
            except BaseException:failed.append(True)
        thread=threading.Thread(target=exchange,daemon=True);thread.start()
        deadline=time.monotonic()+30
        try:
            while thread.is_alive():
                thread.join(0.5);self.guard()
                need(time.monotonic()<deadline,'CATALOG_CODEC_TIMEOUT')
            need(not failed and len(received)==1 and len(received[0])<=16*1024**2 and received[0].endswith(b'\n'), 'CATALOG_CODEC_OUTPUT')
            result=json.loads(received[0])
            need(type(result) is list and len(result)==len(values), 'CATALOG_CODEC_COUNT')
            for item in result:
                need(type(item) is dict and set(item)=={'payload_json','payload_hash','changed_fields','group_key'},'CATALOG_CODEC_FIELDS')
            return result
        except BaseException:
            self.close();raise

    def close(self):
        if self.child.poll() is None:
            self.child.terminate()
            try:self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=5)
