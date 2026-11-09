"""Chatbot adapter for the common journaled code-only transition engine.

Installation/commissioning must supply a root-owned reviewed baseline. Runtime,
credentials, DB schema and RAG index remain separately approved inputs.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from host import Host,secure,command,read_host_state
from package import compatible,unpack,sha,canonical,need


class ChatHost(Host):
    def release_path(self,release):
        m=release['manifest']
        need(re.fullmatch('[a-f0-9]{40}',m['commit']) and re.fullmatch('[1-9][0-9]{0,19}',m['run_id'])
             and re.fullmatch('[1-9][0-9]{0,3}',m['attempt']),'CHATBOT_RELEASE_ID')
        return self.root/'releases'/f"{m['commit']}-{m['run_id']}-{m['attempt']}"

    def existing(self,request):
        for path in (self.root/'runs').glob('*.json'):
            need(read_host_state(path)['status'] in {'SUCCEEDED','ROLLED_BACK'},'UNRESOLVED_HOST_OPERATION')
        need(not (self.root/'runs'/(request['run_key']+'.json')).exists(),'OPERATION_ALREADY_RECORDED_NO_REPLAY')

    def prepare(self,request):
        folder=self.root/'releases'/f"{request['commit']}-{request['run_id']}-{request['attempt']}"
        folder.mkdir(mode=0o755)
        prefix=f"artifacts/chatbot/{request['commit']}/{request['run_key']}"
        for name,version in [('manifest.json',request['manifest_version']),('chatbot.zip',request['archive_version'])]:
            args=[self.config['aws'],'s3api','--region','ap-northeast-2']
            target=['--bucket',self.config['bucket'],'--key',prefix+'/'+name,'--version-id',version,'--expected-bucket-owner','076767081522']
            meta=json.loads(command(args+['head-object']+target))
            need(0<meta['ContentLength']<=(2*1024**2 if name=='manifest.json' else 128*1024**2),'CHATBOT_ARTIFACT_SIZE')
            need(shutil.disk_usage(folder).free>meta['ContentLength']+2*1024**3,'DISK_RESERVE_REQUIRED')
            command(args+['get-object']+target+[str(folder/name)],120)
        m=json.loads((folder/'manifest.json').read_bytes())
        need(all(m[k]==request[k] for k in ['commit','run_id','attempt','archive_sha256']),'CHATBOT_ARTIFACT_IDENTITY')
        compatible(self.baseline['manifest'],m)
        unpack(folder/'chatbot.zip',m,folder/'AI')
        return dict(self.baseline,manifest=m)

    def source_intact(self,release):
        folder=self.release_path(release)/'AI'
        actual={str(p.relative_to(folder)).replace('\\','/') for p in folder.rglob('*') if p.is_file()}
        need(actual==set(release['manifest']['files']),'CHATBOT_SOURCE_MEMBERS_CHANGED')
        for name,entry in release['manifest']['files'].items():
            p=folder/name;secure(p)
            need(p.stat().st_size==entry['bytes'] and sha(p.read_bytes())==entry['sha256'],'CHATBOT_SOURCE_CHANGED')

    def runtime(self,release):
        self.source_intact(release)
        need((self.root/'current').resolve(strict=True)==self.release_path(release),'CURRENT_POINTER_CHANGED')
        need(self.unit('ActiveState')=='active' and self.unit('User')==self.config['service_user']
             and self.config['service_user'] not in ('','root'),'CHATBOT_SERVICE_IDENTITY')
        pid=int(self.unit('MainPID'));need(pid>0,'SERVICE_NO_PID')
        argv=[x.decode() for x in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0') if x]
        need(argv==self.config['expected_argv'],'SERVICE_ARGUMENTS_CHANGED')
        need(Path(f'/proc/{pid}/cwd').resolve()==self.release_path(release)/'AI','CHATBOT_PROCESS_SOURCE_CHANGED')
        values=dict(x.decode().split('=',1) for x in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if b'=' in x)
        for key in ['INVOCATION_ID','JOURNAL_STREAM','SYSTEMD_EXEC_PID','NOTIFY_SOCKET','WATCHDOG_PID','WATCHDOG_USEC']:values.pop(key,None)
        need(values.get('PYTHONDONTWRITEBYTECODE')=='1','CHATBOT_BYTECODE_MUST_BE_DISABLED')
        need(sha(canonical(values))==release['environment_sha256'],'PROCESS_ENVIRONMENT_CHANGED')
        need(self.protected()==release['protected'],'PROTECTED_CONFIG_CHANGED')
        self.require_protected_references(release['protected'])

    def database(self,manifest):
        # This trusted SELECT-only probe is never imported from a new application release.
        output=command(['/usr/sbin/runuser','-u',self.config['db_user'],'--','/usr/bin/python3.12','-I','-S','-B',
            '/opt/jjikmuk-cd/bin/database_probe.py'],35,json.dumps({'database':self.config['database'],'schema_only':True}))
        need(json.loads(output)['schema_sha256']==self.baseline['database_schema_sha256'],'CHATBOT_SCHEMA_MISMATCH')

    def preflight(self,previous,candidate):
        need(int(candidate['manifest']['run_id'])>int(previous['manifest']['run_id']),'STALE_RELEASE_RUN')
        self.runtime(previous);compatible(previous['manifest'],candidate['manifest']);self.database(candidate['manifest'])
        # Immutable venv, RAG inputs, index and settings are all in protected_paths.
        # The commissioned service starts app.start without --rebuild-rag.
        need(self.config['expected_argv'][-6:]==['-m','app.start','--host','127.0.0.1','--port','8000'],
             'CHATBOT_RAG_START_GATE_REQUIRED')

    def rollback_preflight(self,previous,candidate):
        need(self.protected()==previous['protected'],'PROTECTED_CONFIG_CHANGED')
        self.source_intact(previous);self.database(previous['manifest'])
