"""Fixed host metadata only. No environment, credentials, file contents or HTTP/SQL."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

SERVICES = ('jjikmuk-backend.service', 'food-chatbot.service', 'jjikmuk-ocr.service', 'nginx.service')
STATES = {'active', 'inactive', 'failed', 'activating', 'deactivating', 'reloading', 'maintenance', 'not-found'}


def inspect():
    services = {}
    for service in SERVICES:
        result = subprocess.run(['/usr/bin/systemctl', 'show', service, '--property=ActiveState', '--value'],
                                capture_output=True, timeout=4, env={'PATH': '/usr/bin:/bin', 'LANG': 'C'})
        state = result.stdout.decode().strip()
        services[service] = state if state in STATES else 'unknown'
    paths = {}
    for name in ('/opt/jjikmuk-cd', '/etc/jjikmuk-cd/config.json', '/opt/food-chatbot', '/opt/ocr-service'):
        p = Path(name)
        if p.is_symlink():
            paths[name] = {'symlink': True}
        elif p.exists():
            s = p.lstat(); paths[name] = {'uid': s.st_uid, 'gid': s.st_gid, 'mode': s.st_mode & 0o777}
        else:
            paths[name] = {'exists': False}
    return {'status': 'OBSERVED', 'services': services, 'paths': paths,
            'free_bytes': shutil.disk_usage('/').free, 'python': list(sys.version_info[:3]),
            'database_queries': 0, 'service_restarts': 0, 'app_writes': 0}


if __name__ == '__main__':
    try:
        print(json.dumps(inspect()))
    except Exception:
        print('{"status":"INSPECTION_FAILED"}')
        raise SystemExit(1)
