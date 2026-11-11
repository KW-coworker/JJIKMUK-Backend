"""New execution after the inspected product rollback and service restoration."""
import hashlib
import json
import re

REQUEST='a5291163ee0a456b85366e6075d8fce6'
OLD_RUN='42942707829'
SERVICE_RUN='42953603757'
PREVIOUS='70dc1a70fff94dd0bee30f34638a15add23c0f26'
OLD_ARCHIVE='472ad52397dda23747bb08b2d8d76cb050f92f70166aad8f734be18b80c5dcd4'
OLD_STATE='fb13fa0da139bd01e3c9c41aeec64bffa89eab5698579ed4801f787f4967ce1b'
OLD_JOURNAL='10c110c3ad9feb726d7ce6269b187170137d0b6419e1896e0ca70e664d8b4314'
OLD_COORDINATOR='ef1303eb1c891501120cdb73eaf17b9ad722b8beaa93b5d8fbca775745fa1571'
SERVICE_OPERATION='2355941da8905c0d62172949290dd548fb5127de554ceddf8e528774921e0e2f'
SERVICE_RESULT='ec37984bea0e9f0f9045de5bd7fe5e28f3272945dd378c026d16d20e3f753591'
LAST_RUN='42984831949'
LAST_COMMIT='2d01af1f5f139b3c650e93f477e2f4216ccf52e2'
LAST_ARCHIVE='ce8e03247702573860180199b619404d4ff573194bdd4663dcb2b71f97fa516d'
LAST_BINDING='ecb046cd67d0a4ab1861fefe4b52159d60e9edba28fd7e883bb19d1a5b36678d'
LAST_RECOVERY_OPERATION='3cdf2917bb191b06996da5ada3bde4586a67569f887087dab99006daf759f61b'
LAST_RECOVERY_RESULT='a4ed03168140c9194391d0de69ee7668de67a7ae95efbafb32bc39f1255592ab'
SOURCE_SHA='f277f176e199336e7d4dcc8058c64a1d3b87c3b5768171691c3eb11f29ba1e4f'
SOURCE_BYTES=1052856320
SCHEMA_SHA='b768920c4335a7d19a5e5f228a8e4f11810f40aabdc184f08d71cbdde2d4c2e6'
HOST_START_BYTES=5*1024**3
RDS_RESERVE_BYTES=2*1024**3
ROLLBACK_BUDGET_BYTES=3*1024**3
APPLY_BUDGET_BYTES=3*1024**3
RDS_START_BYTES=RDS_RESERVE_BYTES+ROLLBACK_BUDGET_BYTES+APPLY_BUDGET_BYTES
RESERVE_APPROVAL='USER_RDS_RESERVE_2GIB_20261111'
PHASE_SECONDS={'freeze':1200,'apply':7200,'recover':7200}
SNAPSHOT_POLLS=180
SNAPSHOT_BUDGET=1920
RUNNER_SECONDS={'freeze':4200,'apply':8500,'recover':8700}
LEASE_BYTES={'freeze':RDS_RESERVE_BYTES+ROLLBACK_BUDGET_BYTES,
             'apply':RDS_RESERVE_BYTES+ROLLBACK_BUDGET_BYTES,'recover':RDS_RESERVE_BYTES}


def need(value,code):
    if not value:raise ValueError(code)


def dataset(request,run):
    need(request==REQUEST and re.fullmatch('[1-9][0-9]{0,19}',run) and run not in (OLD_RUN,SERVICE_RUN,LAST_RUN),
         'REAPPLY_FRESH_EXECUTION_REQUIRED')
    return 'catalog-handoff-'+hashlib.sha256((request+':'+run).encode()).hexdigest()[:32]


def previous_coordinator(value):
    operation=hashlib.sha256((REQUEST+':'+LAST_RUN+':recover').encode()).hexdigest()
    need(value=={'status':'ROLLED_BACK','component':'db','operation_id':operation,
                 'recovery_of':previous_apply_record()[1]},
         'REAPPLY_LAST_RECOVERY_COORDINATOR_CHANGED')


def previous_apply_record():
    value={'status':'MUTATION_INTENT','component':'db',
           'operation_id':hashlib.sha256((REQUEST+':'+LAST_RUN+':apply').encode()).hexdigest()}
    # Match coordination.atomic's exact bytes, including its default separators.
    raw=json.dumps(value,sort_keys=True).encode('utf-8')
    return value,hashlib.sha256(raw).hexdigest()


def validate_binding(binding):
    need(binding.get('reapply')=={'previous_run':OLD_RUN,'service_run':SERVICE_RUN,'previous_archive':OLD_ARCHIVE,
         'previous_state_sha256':OLD_STATE,'previous_journal_sha256':OLD_JOURNAL,
         'last_recovered_run':LAST_RUN,'last_recovery_sha256':LAST_RECOVERY_RESULT},'REAPPLY_BINDING')
    need(binding['previous_commit']==PREVIOUS and binding['source_sha256']==SOURCE_SHA and
         binding['source_bytes']==SOURCE_BYTES and binding['required_bytes']==RDS_RESERVE_BYTES,'REAPPLY_SOURCE_OR_PREVIOUS')
    need(binding.get('reserve_approval')==RESERVE_APPROVAL and binding.get('source_plan_required_bytes')==5*1024**3,
         'REAPPLY_USER_RESERVE_APPROVAL_REQUIRED')
    dataset(binding['request_id'],binding['run_id'])


def lease_binding(binding,phase):
    validate_binding(binding)
    need(phase in PHASE_SECONDS,'REAPPLY_PHASE')
    return dict(binding,required_bytes=LEASE_BYTES[phase])
