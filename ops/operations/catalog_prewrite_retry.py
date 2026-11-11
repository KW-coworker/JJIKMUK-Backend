"""Admission after a recovered freeze failure, separate from the last data rollback."""
import hashlib
import json
from pathlib import Path

REQUEST='a5291163ee0a456b85366e6075d8fce6'
RUN='43030219397'
COMMIT='ecb1baec6f840e0b4e048899aeabf5064940463a'
ARCHIVE='000eff0df449c6b18cbabd79d90e5c4aaa302e37665370efbf4013a6fc6ed489'
BINDING='59b8da55607c9a68ccde3228432be93e4ad87ca6e7bfde81835fb6089ccf2d00'
RECOVERY_OPERATION='a748da85fc03bc4830c3bd0f605b8d8360207a4efed5ebe05436818169edd891'
RECOVERY_RESULT='f51733edeba99ef400ff4c55ad072abeea339637b7e5643a228d39a59542f73c'


def stage():return Path('/opt/jjikmuk-catalog-'+ARCHIVE[:16])


def coordinator():
    def phase(name):return hashlib.sha256((REQUEST+':'+RUN+':'+name).encode()).hexdigest()
    frozen={'status':'MUTATION_INTENT','component':'db','operation_id':phase('freeze')}
    return {'status':'ROLLED_BACK','component':'db','operation_id':phase('recover'),
            'recovery_of':hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest()}


def validate_state(state,baseline):
    from manifest import require
    require(hashlib.sha256(json.dumps(state['binding'],sort_keys=True,separators=(',',':')).encode()).hexdigest()==BINDING,
            'REAPPLY_PREWRITE_BINDING_CHANGED')
    require(state['status']=='RECOVERED' and state['previous']==baseline,
            'REAPPLY_PREWRITE_STATE_CHANGED')
    require(not any(key in state for key in ('preservation','candidate_release','counts','recovery_counts',
            'value_verification','recovery_verification')),'REAPPLY_PREWRITE_DATA_WORK_PRESENT')


def verify(work):
    import subprocess
    from host import secure,read_host_state
    from manifest import require,digest
    from coordination import ROOT
    folder=stage();secure(folder)
    path=folder/'state.json';secure(path);before=digest(path)
    state=read_host_state(path);validate_state(state,work.host.baseline)
    require(not (folder/'before-values.sqlite').exists(),'REAPPLY_PREWRITE_JOURNAL_EXISTS')
    for phase in ('freeze','apply','recover'):
        row=subprocess.run(['/usr/bin/systemctl','is-active','jjikmuk-catalog-'+phase+'-'+ARCHIVE[:16]],
                           capture_output=True,timeout=5)
        require(row.stdout.strip() in (b'inactive',b'failed',b'unknown'),'REAPPLY_PREWRITE_UNIT_ACTIVE')
    record=ROOT/'history'/coordinator()['operation_id']/'02.json'
    for item in (ROOT,ROOT/'history',record.parent,record):secure(item)
    require(record.stat().st_size<4096 and json.loads(record.read_bytes())==coordinator(),
            'REAPPLY_PREWRITE_RECOVERY_RECORD_CHANGED')
    require(digest(path)==before,'REAPPLY_PREWRITE_STATE_CHANGED_DURING_READ')
