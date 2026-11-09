"""Explicit second step of approved disabled installation, before commissioning.

Never imported/executed by ordinary deployment. Existing state is never reset.
All previously installed per-component journals must already be resolved.
"""
import json
from pathlib import Path
import sys
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from coordination import initialize,need,secure,ROOT


def install(root=ROOT,journal_roots=None):
    roots=journal_roots if journal_roots is not None else [Path('/opt/jjikmuk-cd/runs'),Path('/opt/jjikmuk-chatbot/runs')]
    for folder in roots:
        if not folder.exists():continue
        secure(folder)
        rows=list(folder.glob('*.json'));need(len(rows)<=10000,'COMPONENT_JOURNAL_LIMIT')
        for path in rows:
            secure(path);need(path.stat().st_size<=128*1024**2,'COMPONENT_JOURNAL_BYTES')
            need(json.loads(path.read_bytes()).get('status') in {'SUCCEEDED','ROLLED_BACK'},'UNRESOLVED_COMPONENT_JOURNAL')
    initialize(root)
    return {'status':'INSTALLED_DISABLED','checks':{'coordinator_initialized':True,'prior_journals_resolved':True}}


if __name__=='__main__':
    try:print(json.dumps(install()))
    except Exception:
        print('{"status":"STOPPED","codes":["COORDINATOR_INSTALL_REQUIRES_REVIEW"]}');raise SystemExit(1)
