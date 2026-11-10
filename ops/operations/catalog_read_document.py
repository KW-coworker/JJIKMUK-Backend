"""Fixed read-only comparison document. Generation alone never calls AWS."""
import json
import re
from pathlib import Path


def document(binding):
    if (set(binding) != {'key','version','bytes','sha256','source_sha256'} or
        not re.fullmatch(r'operations/private/[a-f0-9]{32}/[a-f0-9]{64}\.zip',binding['key']) or
        not re.fullmatch(r'[A-Za-z0-9._~+/-]{1,1024}',binding['version']) or binding['version']=='null' or
        not all(re.fullmatch('[a-f0-9]{64}',binding[k]) for k in ('sha256','source_sha256')) or
        binding['key'].split('/')[-1] != binding['sha256']+'.zip' or
        type(binding['bytes']) is not int or not 0<binding['bytes']<=1024**3):
        raise ValueError('INVALID_COMPARISON_OBJECT')
    script = 'BINDING = '+repr(binding)+'\n'+LAUNCHER
    command = "/usr/bin/python3 -I -S -B <<'JJIKMUK_READONLY_COMPARE'\n"+script+"\nJJIKMUK_READONLY_COMPARE"
    result = {'schemaVersion':'2.2','description':'Compare product handoff in one read-only snapshot; no deploy or DB mutation',
        'parameters':{},'mainSteps':[{'action':'aws:runShellScript','name':'report',
        'inputs':{'timeoutSeconds':'1200','runCommand':[command]}}]}
    if len(json.dumps(result).encode())>60000:
        raise ValueError('DOCUMENT_TOO_LARGE')
    return result


LAUNCHER = r'''
import fcntl, hashlib, json, os, re, resource, shutil, signal, stat, subprocess, sys, zipfile
from pathlib import Path

def need(ok,code):
    if not ok: raise ValueError(code)

def secure(path):
    p=Path(path)
    for part in [p,*p.parents]:
        s=part.lstat()
        need(not part.is_symlink() and s.st_uid==0 and not s.st_mode&0o022,'UNTRUSTED_PATH')
    return p

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
    return h.hexdigest()

def safe_report(raw):
    value=json.loads(raw)
    need(set(value)<={'status','checks','hashes','counts','codes'},'REPORT_FIELDS')
    for group in ('checks','hashes','counts'):
        items=value.get(group,{})
        need(type(items) is dict and len(items)<=100,'REPORT_MAP')
        for key,item in items.items():
            need(re.fullmatch('[a-zA-Z][a-zA-Z0-9_.-]{0,79}',key),'REPORT_KEY')
            need(type(item) is bool if group=='checks' else
                 type(item) is int and 0<=item<2**63 if group=='counts' else
                 type(item) is str and re.fullmatch('[a-f0-9]{64}',item),'REPORT_VALUE')
    return value

def restricted():
    resource.setrlimit(resource.RLIMIT_AS,(512*1024**2,512*1024**2))
    resource.setrlimit(resource.RLIMIT_CPU,(450,460))
    os.nice(10)

def run():
    need(os.geteuid()==0,'ROOT_LAUNCHER_REQUIRED')
    root=secure('/opt/jjikmuk-cd')
    stage=Path('/opt')/('jjikmuk-db-compare-'+BINDING['sha256'][:20])
    need(not stage.exists() and not stage.is_symlink(),'COMPARISON_ALREADY_STAGED_NO_REPLAY')
    need(shutil.disk_usage('/opt').free>=BINDING['bytes']*3+1024**3,'DISK_RESERVE')
    stage.mkdir(mode=0o755)
    os.chmod(stage,0o755)
    archive=stage/'input.zip'
    aws=secure(root/'tools/aws-cli/aws')
    fetched=subprocess.run([str(aws),'s3api','get-object','--region','ap-northeast-2',
        '--bucket','jjikmuk-operations-076767081522-apne2','--key',BINDING['key'],
        '--version-id',BINDING['version'],'--expected-bucket-owner','076767081522',str(archive)],
        capture_output=True,timeout=300,env={'PATH':'/usr/bin:/bin','HOME':'/root','AWS_MAX_ATTEMPTS':'1','AWS_PAGER':''})
    need(fetched.returncode==0 and archive.stat().st_size==BINDING['bytes'] and
         digest(archive)==BINDING['sha256'],'COMPARISON_DOWNLOAD_HASH')
    os.chmod(archive,0o600)
    files={'catalog_compare.py','catalog_read_probe.py','source-fingerprints.sqlite'}
    with zipfile.ZipFile(archive) as z:
        need(len(z.namelist())==4 and set(z.namelist())==files|{'bundle.json'} and
             z.getinfo('bundle.json').file_size<4096,'BUNDLE_MEMBERS')
        manifest=json.loads(z.read('bundle.json'))
        need(set(manifest)==files,'BUNDLE_MANIFEST')
        for name in sorted(files):
            info=z.getinfo(name);wanted=manifest[name]
            need(stat.S_IFMT(info.external_attr>>16) in (0,stat.S_IFREG) and
                 set(wanted)=={'bytes','sha256'} and info.file_size==wanted['bytes'] and
                 0<info.file_size<1024**3,'BUNDLE_FILE_LIMIT')
            path=stage/name
            with z.open(name) as src,path.open('xb') as dest:
                shutil.copyfileobj(src,dest,1024**2)
            os.chmod(path,0o444)
            need(digest(path)==wanted['sha256'],'BUNDLE_FILE_HASH')
    need(digest(stage/'source-fingerprints.sqlite')==BINDING['source_sha256'],'SOURCE_HASH')
    sys.path[:0]=[str(secure(root/'bin'))]
    from host import Host
    from coordination import TERMINAL
    coordinator=secure('/var/lib/jjikmuk-operations')
    with secure(coordinator/'host.lock').open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=json.loads(secure(coordinator/'state.json').read_bytes())
        need(state.get('status') in TERMINAL,'UNRESOLVED_HOST_OPERATION')
        config=json.loads(secure('/etc/jjikmuk-cd/config.json').read_bytes())
        host=Host(config);host.runtime(host.baseline)
        before=host.identity()
        mem=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
        need(int(mem['MemAvailable'].split()[0])*1024>=512*1024**2,'MEMORY_RESERVE')
        request={'source_sha256':BINDING['source_sha256'],'database':config['database'],
                 'migrations':host.baseline['manifest']['migrations']}
        child=subprocess.Popen(['/usr/sbin/runuser','-u','ubuntu','--','/usr/bin/python3.12','-I','-S','-B',
            str(stage/'catalog_read_probe.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            start_new_session=True,preexec_fn=restricted,env={'PATH':'/usr/bin:/bin','HOME':'/home/ubuntu'})
        try:
            stdout,stderr=child.communicate(json.dumps(request).encode(),timeout=540)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL)
            child.communicate(timeout=10)
            raise ValueError('PROBE_DEADLINE')
        need(not stderr and len(stdout)<=16384,'PROBE_OUTPUT_LIMIT')
        report=safe_report(stdout.decode())
        need(child.returncode==0 and report['status']=='VERIFIED','PROBE_NOT_VERIFIED')
        host.runtime(host.baseline)
        need(host.identity()==before,'BACKEND_PROCESS_CHANGED')
        report['checks']['same_backend_process']=True
        report['checks']['protected_files_unchanged']=True
        with (stage/'result.json').open('x') as f:
            os.chmod(stage/'result.json',0o600);json.dump(report,f)
        return report

try: print(json.dumps(run()))
except BaseException as error:
    print(json.dumps({'status':'STOPPED','codes':['READONLY_COMPARISON_STOPPED_KEEP_STAGE']}))
    raise SystemExit(1)
'''
