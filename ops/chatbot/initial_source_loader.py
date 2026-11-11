"""Fixed SSM loader for one reviewed code-only chatbot transition package."""
import json
import os
from pathlib import Path
import subprocess
import sys


def execute(envelope):
    sys.dont_write_bytecode = True
    root = Path('/opt/jjikmuk-cd/bin')
    # Validate installed trusted modules before importing them as root.
    for path in [root, *root.parents]:
        st = path.lstat()
        assert not path.is_symlink() and st.st_uid == 0 and not st.st_mode & 0o022
    sys.path.insert(0, str(root))
    from private_plan import validate
    from private_runner import unpack, digest
    from coordination import ROOT, locked, secure
    from connection import canonical, sha, BUCKET, ACCOUNT
    from bootstrap import need
    from run import safe_report
    validate(envelope)
    need(envelope['component'] == 'chatbot' and envelope['operation'] == 'deploy'
         and envelope['approval_id'] == 'USER_RESUME_BACKEND_AND_CHATBOT_20261112'
         and envelope['recovery_sha256'] is None, 'CHATBOT_SOURCE_SCOPE')
    operation = sha(canonical(envelope))
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
