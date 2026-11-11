"""Read fixed paid-call ledgers; never import apps, call providers or change limits."""
import json
from contextlib import closing
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time

CHAT_LEDGER = Path('/var/lib/food-chatbot/integration-20261015/external-ai.sqlite3')
OCR_ROOT = Path('/home/ubuntu/ocr-json-secrets/paid-budget')


def need(condition, code):
    if not condition:
        raise ValueError(code)


def counters(cap, used):
    need(type(cap) is int and type(used) is int and 0 <= used <= cap <= 1000,
         'INVALID_PAID_COUNTERS')
    return {'limit': cap, 'used': used, 'remaining': cap-used}


def chatbot_counts(path):
    need(path.is_file() and not path.is_symlink() and path.resolve() == path,
         'CHATBOT_LEDGER_PATH')
    need(path.stat().st_size <= 64*1024**2, 'CHATBOT_LEDGER_SIZE')
    # mode=ro refuses missing files; one SELECT gives a consistent SQLite snapshot.
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=3)) as db:
        db.execute('PRAGMA query_only=ON')
        rows = db.execute('SELECT cap,prior,(SELECT COUNT(*) FROM calls) FROM budget WHERE id=1').fetchall()
    need(len(rows) == 1, 'CHATBOT_LEDGER_ROW')
    cap, prior, count = rows[0]
    need(type(prior) is int and type(count) is int and prior >= 0, 'CHATBOT_LEDGER_PRIOR')
    return counters(cap, prior+count)


def ocr_counts(marker, cap):
    need(marker.parent.resolve() == marker.parent and marker.parent.is_dir(), 'OCR_LEDGER_PATH')
    indices = set()
    with os.scandir(marker.parent) as entries:
        for entry in entries:
            if entry.name != marker.name and not entry.name.startswith(marker.name+'.'):
                continue
            need(not entry.is_symlink() and entry.is_file(follow_symlinks=False), 'OCR_MARKER_TYPE')
            if entry.name == marker.name:
                index = 1
            else:
                suffix = entry.name[len(marker.name)+1:]
                need(re.fullmatch(r'[0-9]{6}', suffix) is not None, 'OCR_MARKER_NAME')
                index = int(suffix)
                need(2 <= index <= cap, 'OCR_MARKER_RANGE')
            indices.add(index)
            need(len(indices) <= 1000, 'OCR_MARKER_LIMIT')
    need(indices == set(range(1, len(indices)+1)), 'OCR_MARKER_GAP')
    return counters(cap, len(indices))


def command(args):
    result = subprocess.run(args, capture_output=True, timeout=10, check=True,
                            env={'PATH':'/usr/bin:/bin', 'LANG':'C'})
    need(len(result.stdout) <= 1024**2, 'LOCAL_QUERY_SIZE')
    return result.stdout


def service_identity():
    pid = command(['/usr/bin/systemctl','show','food-chatbot-team.service','--property=MainPID','--value']).strip()
    invocation = command(['/usr/bin/systemctl','show','food-chatbot-team.service','--property=InvocationID','--value']).strip()
    need(re.fullmatch(rb'[1-9][0-9]{0,9}', pid) is not None and re.fullmatch(rb'[0-9a-f]{32}', invocation) is not None,
         'CHATBOT_SERVICE_NOT_RUNNING')
    return pid.decode(), invocation


def chatbot():
    before = service_identity()
    with Path('/proc', before[0], 'environ').open('rb') as source:
        raw = source.read(1024**2+1)
    need(len(raw) <= 1024**2, 'PROCESS_ENV_SIZE')
    key = b'FOOD_CHATBOT_EXTERNAL_AI_STATE_DB='
    paths = [item[len(key):].decode() for item in raw.split(b'\0') if item.startswith(key)]
    del raw  # No environment or credentials are returned or saved.
    need(paths == [str(CHAT_LEDGER)], 'ACTIVE_CHATBOT_LEDGER_MISMATCH')
    result = chatbot_counts(CHAT_LEDGER)
    need(service_identity() == before, 'CHATBOT_PROCESS_CHANGED')
    return result


def ocr():
    raw = command(['/usr/bin/docker','inspect','ocr-json-institution'])
    instances = json.loads(raw)
    del raw
    need(len(instances) == 1, 'OCR_CONTAINER_COUNT')
    live = instances[0]
    need(live['State']['Running'] is True, 'OCR_CONTAINER_NOT_RUNNING')
    selected = {}
    for key in ('OCR_PAID_ATTEMPT_MARKER', 'OCR_PAID_ATTEMPT_LIMIT'):
        matches = [item[len(key)+1:] for item in live['Config']['Env'] if item.startswith(key+'=')]
        need(len(matches) == 1, 'OCR_BUDGET_SETTING_COUNT')
        selected[key] = matches[0]
    cap_text = selected['OCR_PAID_ATTEMPT_LIMIT']
    need(re.fullmatch(r'[1-9][0-9]{0,3}', cap_text) is not None, 'OCR_CAP_FORMAT')
    cap = int(cap_text)
    counters(cap, 0)
    marker = Path(selected['OCR_PAID_ATTEMPT_MARKER'])
    need(marker.is_absolute() and '..' not in marker.parts, 'OCR_MARKER_PATH')
    mounts = [m for m in live['Mounts'] if marker.is_relative_to(m['Destination'])]
    need(len(mounts) == 1 and mounts[0]['Type'] == 'bind', 'OCR_LEDGER_MOUNT')
    mount = mounts[0]
    source = Path(mount['Source']) / marker.relative_to(mount['Destination'])
    need(source.parent == OCR_ROOT and source.name == 'paid-attempt.claimed', 'ACTIVE_OCR_LEDGER_MISMATCH')
    result = ocr_counts(source, cap)
    after = json.loads(command(['/usr/bin/docker','inspect','--format','{{json .State}}','ocr-json-institution']))
    need(after['Running'] is True and after['Pid'] == live['State']['Pid']
         and after['StartedAt'] == live['State']['StartedAt'], 'OCR_PROCESS_CHANGED')
    return result


def report(kind):
    need(kind in ('chatbot','ocr'), 'FIXED_COMPONENT_REQUIRED')
    result = chatbot() if kind == 'chatbot' else ocr()
    return {'status':'VERIFIED', 'checks':{'readonly_ledger':True, 'active_runtime_verified':True},
            'counts':{**result, 'observed_epoch_seconds':int(time.time()), 'paid_ai_calls':0,
                      'service_restarts':0, 'application_writes':0}}


def main(kind):
    try:
        print(json.dumps(report(kind)))
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', str(error)) else 'PAID_USAGE_READ_FAILED'
        print(json.dumps({'status':'STOPPED', 'codes':[code]}))
        raise SystemExit(1)
