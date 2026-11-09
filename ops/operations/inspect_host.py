"""Fixed service/source metadata. No environment files, credentials, SQL or HTTP."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVICES = {'backend': ('jjikmuk-backend.service', 'food-chatbot-team.service', 'nginx.service'),
            'ocr': ('docker.service',)}


def unit(name, prop):
    result = subprocess.run(['/usr/bin/systemctl', 'show', name, '--property='+prop, '--value'],
                            capture_output=True, timeout=4, env={'PATH':'/usr/bin:/bin','LANG':'C'})
    if result.returncode: raise ValueError('SERVICE_QUERY_FAILED')
    return result.stdout.decode().strip()


def source_digest(root):
    root = root.resolve(strict=True)
    allowed = ('/opt/jjikmuk-github/releases/', '/opt/food-chatbot/releases/', '/opt/jjikmuk-chatbot/releases/')
    if not any(str(root).startswith(p) for p in allowed): raise ValueError('SOURCE_PATH_UNREVIEWED')
    files = sorted((root/'app').rglob('*.py'))
    if not 0 < len(files) <= 2000: raise ValueError('SOURCE_FILE_LIMIT')
    rows=[]; total=0
    for path in files:
        if path.is_symlink() or not path.is_file(): raise ValueError('SOURCE_FILE_TYPE')
        size=path.stat().st_size; total+=size
        if size > 2*1024**2 or total > 64*1024**2: raise ValueError('SOURCE_BYTES_LIMIT')
        rows.append([path.relative_to(root).as_posix(),hashlib.sha256(path.read_bytes()).hexdigest()])
    return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest(),len(rows)


def inspect(kind):
    if kind not in SERVICES: raise ValueError('HOST_KIND_REQUIRED')
    checks={name:unit(name,'ActiveState')=='active' for name in SERVICES[kind]}
    hashes={};counts={}
    if kind=='backend' and checks['food-chatbot-team.service']:
        root=Path(unit('food-chatbot-team.service','WorkingDirectory'))
        try:
            hashes['chatbot_python_sources'],counts['chatbot_python_files']=source_digest(root)
            checks['chatbot_source_observed']=True
        except (ValueError,OSError): checks['chatbot_source_observed']=False
    return {'status':'OBSERVED','checks':checks,'hashes':hashes,'counts':counts,
            'free_bytes':shutil.disk_usage('/').free,'python':list(sys.version_info[:3]),
            'database_queries':0,'service_restarts':0,'app_writes':0}


if __name__ == '__main__':
    try:
        print(json.dumps(inspect(os.environ.get('SSM_HostKind',''))))
    except Exception:
        print('{"status":"INSPECTION_FAILED"}')
        raise SystemExit(1)
