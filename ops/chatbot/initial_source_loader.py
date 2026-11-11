"""Fixed SSM loader for one reviewed code-only chatbot transition package."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def safe_report(raw):
    """Validate this fixed package's public result without runner-only modules."""
    if len(raw.encode()) > 16384:
        raise ValueError('CHATBOT_SOURCE_REPORT_LIMIT')
    value = json.loads(raw)
    if type(value) is not dict or not set(value) <= {'status', 'checks', 'hashes', 'counts', 'codes'}:
        raise ValueError('CHATBOT_SOURCE_REPORT_FIELDS')
    if value.get('status') not in {'SUCCEEDED', 'ROLLED_BACK', 'PREFLIGHT_FAILED', 'MANUAL_RECOVERY_REQUIRED'}:
        raise ValueError('CHATBOT_SOURCE_REPORT_STATUS')
    for field, entries in value.items():
        if field == 'status':
            continue
        if field == 'codes':
            if type(entries) is not list or len(entries) > 50 or not all(
                    type(code) is str and re.fullmatch('[A-Z][A-Z0-9_]{0,79}', code) for code in entries):
                raise ValueError('CHATBOT_SOURCE_REPORT_CODES')
            continue
        if type(entries) is not dict or len(entries) > 100:
            raise ValueError('CHATBOT_SOURCE_REPORT_MAP')
        for key, item in entries.items():
            if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_.-]{0,79}', key):
                raise ValueError('CHATBOT_SOURCE_REPORT_KEY')
            valid = (type(item) is bool if field == 'checks' else
                     type(item) is int and 0 <= item < 2**63 if field == 'counts' else
                     type(item) is str and re.fullmatch('[a-f0-9]{64}', item))
            if not valid:
                raise ValueError('CHATBOT_SOURCE_REPORT_VALUE')
    return value


def installed_modules():
    # Only these modules are included by ops/cd/package_install.py. In particular,
    # ops/operations/run.py exists on the GitHub runner, not on the EC2 host.
    from private_plan import validate
    from private_runner import unpack, digest
    from coordination import ROOT, locked, secure
    from connection import canonical, sha, BUCKET, ACCOUNT
    from bootstrap import need
    return validate, unpack, digest, ROOT, locked, secure, canonical, sha, BUCKET, ACCOUNT, need


def execute(envelope):
    sys.dont_write_bytecode = True
    root = Path('/opt/jjikmuk-cd/bin')
    # Validate installed trusted modules before importing them as root.
    for path in [root, *root.parents]:
        st = path.lstat()
        assert not path.is_symlink() and st.st_uid == 0 and not st.st_mode & 0o022
    sys.path.insert(0, str(root))
    validate, unpack, digest, ROOT, locked, secure, canonical, sha, BUCKET, ACCOUNT, need = installed_modules()
    validate(envelope)
    need(envelope['component'] == 'chatbot' and envelope['operation'] == 'deploy'
         and envelope['approval_id'] == 'USER_RESUME_BACKEND_AND_CHATBOT_20261112'
         and envelope['recovery_sha256'] is None, 'CHATBOT_SOURCE_SCOPE')
    operation = sha(canonical(envelope))
    # The previous loader failed before importing its report helper. Continue only
    # when no host attempt or staging directory was created; never replay a child.
    need(not (ROOT / 'history' / operation).exists()
         and not (ROOT / ('chatbot-source-' + operation)).exists(), 'CHATBOT_SOURCE_PREVIOUS_EXECUTION_EXISTS')
    with locked('chatbot', operation) as guard:
        folder = ROOT / ('chatbot-source-' + operation)
        folder.mkdir(mode=0o700)
        archive = folder / 'package.zip'
        aws = Path('/opt/jjikmuk-cd/tools/aws-cli/aws'); secure(aws)
        key = 'operations/private/' + envelope['request_id'] + '/' + envelope['sha256'] + '.zip'
        response = subprocess.run([str(aws), 's3api', 'get-object', '--region', 'ap-northeast-2',
            '--bucket', BUCKET, '--key', key, '--version-id', envelope['version'],
            '--expected-bucket-owner', ACCOUNT, str(archive)], capture_output=True, timeout=180)
        need(response.returncode == 0 and archive.stat().st_size == envelope['bytes']
             and digest(archive) == envelope['sha256'], 'CHATBOT_SOURCE_PACKAGE_HASH')
        entry = unpack(archive, folder / 'payload')
        guard.record('MUTATION_INTENT')
        with (folder / 'private.log').open('xb') as log:
            os.chmod(log.name, 0o600)
            child = subprocess.run(['/usr/bin/python3.12', '-I', '-S', '-B', str(entry)],
                cwd=entry.parent, stdout=log, stderr=log, timeout=1200,
                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root', 'JJIKMUK_OPERATION_ID': operation})
        need(child.returncode == 0, 'CHATBOT_SOURCE_CHILD_UNKNOWN_KEEP_HOLD')
        path = entry.parent / 'transition-result.json'; secure(path)
        need(path.stat().st_size <= 16384, 'CHATBOT_SOURCE_REPORT_LIMIT')
        result = safe_report(path.read_text())
        if result['status'] == 'SUCCEEDED':
            need(result.get('checks') and all(v is True for v in result['checks'].values()), 'CHATBOT_SOURCE_UNVERIFIED')
            guard.record('SUCCEEDED')
        elif result['status'] == 'ROLLED_BACK':
            need(result.get('checks') and all(v is True for v in result['checks'].values()), 'CHATBOT_ROLLBACK_UNVERIFIED')
            guard.record('ROLLED_BACK')
        elif result['status'] == 'PREFLIGHT_FAILED':
            need(not (entry.parent / 'switch-intent.json').exists(), 'CHATBOT_PREFLIGHT_AFTER_SWITCH_INTENT')
            guard.record('REJECTED')
        else:
            guard.record('MANUAL_RECOVERY_REQUIRED')
        return result
