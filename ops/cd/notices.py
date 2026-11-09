"""Public CD notices contain only verified GitHub identities and allowlisted outcomes."""
import io
import json
import re
import zipfile

TARGETS = {'KW-coworker/JJIKMUK-Backend': ('main','Backend CD','backend'),
           'Alphrit/jjikmuk-CO-WORKER-': ('chatbot','Chatbot CD','chatbot')}
REASONS = {
    'SCHEMA_CHANGE_REQUIRES_SEPARATE_RELEASE': 'DB 변경이 포함돼 있습니다. 서버 담당자가 승인된 DB 작업과 기준 등록을 먼저 진행해야 합니다.',
    'DATABASE_HISTORY_MISMATCH': '서버 DB 이력이 코드 요구사항과 다릅니다. DB 상태를 확인하고 필요한 수동 작업을 요청하세요.',
    'CHATBOT_SCHEMA_MISMATCH': '챗봇이 요구하는 DB 구조가 준비되지 않았습니다. 자동 SQL 실행 없이 배포를 보류했습니다.',
    'CONFIGURATION_CHANGE_REQUIRES_REVIEW': '실행 설정 변경이 포함돼 있습니다. 서버 담당자의 설정 호환성 확인이 필요합니다.',
    'RUNTIME_CHANGE_REQUIRES_REVIEW': 'Python 또는 라이브러리 구성이 달라졌습니다. 검증된 실행 환경을 먼저 준비해야 합니다.',
    'RAG_CHANGE_REQUIRES_REVIEW': '검색 자료 또는 인덱스 호환성 확인이 필요합니다. 자동 재구축은 하지 않습니다.',
    'HOST_OPERATION_BUSY': '같은 서버에서 다른 작업이 진행 중입니다. 작업 종료와 기존 실행 결과를 확인한 뒤 재시도하세요.',
    'UNRESOLVED_HOST_OPERATION': '이전 서버 작업의 결과가 미확정입니다. 서버 담당자의 상태 확인이 먼저 필요합니다.',
    'PROTECTED_CONFIG_CHANGED': '승인된 서버 설정과 현재 설정이 다릅니다. 원인을 확인한 뒤 기준을 다시 검증해야 합니다.',
    'HEALTH_DEADLINE': '새 버전의 정상 실행을 제한 시간 안에 확인하지 못했습니다. 변경 코드와 호환성을 확인하세요.',
    'BUILD_FAILED': '검사 또는 빌드가 실패했습니다. 해당 실행의 실패한 검사를 수정한 PR을 올려주세요.',
    'SUPERSEDED': '더 최신 커밋이 있어 이 버전의 배포를 중단했습니다. 최신 실행 결과를 확인하세요.',
}
STATES = {
    'SUCCEEDED': '배포 성공 기록이 있습니다. 자동화의 다른 단계 실패 여부를 확인하세요.',
    'ROLLED_BACK': '배포는 실패했고 이전 실행 버전으로 복귀한 기록이 있습니다.',
    'MANUAL_RECOVERY_REQUIRED': '자동 복귀를 완료하지 못했습니다. 서버 담당자의 복구 확인이 필요합니다.',
    'REJECTED': '서버 실행 버전 전환 전에 자동 배포가 거절됐습니다.',
    'STOP_REVIEW_REQUIRED': '안전 조건을 확인하지 못했습니다. 서버 실행 상태는 별도 확인이 필요합니다.',
    'UNKNOWN': '서버 반영 여부가 확인되지 않았습니다. 같은 배포를 다시 보내지 말고 기존 실행을 조회하세요.',
    'NOT_DISPATCHED': '이 실행에서는 서버 배포 작업을 시작하지 않았습니다.',
}


def need(ok,code):
    if not ok: raise ValueError(code)


def parse_result(data, run):
    need(len(data)<=1024*1024,'NOTICE_ARCHIVE_LIMIT')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        files=z.infolist()
        need(len(files)==1 and files[0].filename=='result.json' and files[0].file_size<=32768,'NOTICE_ARCHIVE_MEMBERS')
        result=json.loads(z.read(files[0]))
    need(type(result) is dict,'NOTICE_RESULT_TYPE')
    # Never render unrecognized remote fields, exception messages or response bodies.
    for key,expected in [('commit',run['head_sha']),('run_id',str(run['id'])),('attempt',str(run['run_attempt']))]:
        need(str(result.get(key,''))==expected,'NOTICE_RESULT_IDENTITY')
    status=result.get('status','UNKNOWN')
    code=result.get('reason',status)
    return {'status':status if status in STATES else 'STOP_REVIEW_REQUIRED',
            'reason':code if code in REASONS else 'REVIEW_REQUIRED'}


def classify(run,jobs,result=None):
    build=[j for j in jobs if j['name'].split(' / ')[-1]=='build']
    deploy=[j for j in jobs if j['name'].split(' / ')[-1]=='deploy']
    if build and any(j['conclusion'] in {'failure','timed_out','cancelled'} for j in build) and not any(
            j['conclusion'] not in {'skipped',None} for j in deploy):
        return {'status':'NOT_DISPATCHED','reason':'BUILD_FAILED'}
    if result:return result
    return {'status':'UNKNOWN','reason':'REVIEW_REQUIRED'}


def login(value):
    return value if isinstance(value,str) and re.fullmatch('[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})',value) else None


def message(repo,run,outcome,people):
    need(repo in TARGETS and re.fullmatch('[a-f0-9]{40}',run['head_sha']),'NOTICE_TARGET')
    need(type(run['id']) is int and run['id']>0 and type(run['run_attempt']) is int,'NOTICE_RUN')
    marker=f'<!-- jjikmuk-cd:{run["id"]}:{run["run_attempt"]} -->'
    recipients=sorted({v for x in ['fisfin',*people] if (v:=login(x))})
    component=TARGETS[repo][2]
    reason=outcome.get('reason','REVIEW_REQUIRED')
    text=REASONS.get(reason,'실행 링크에서 실패 단계를 확인하세요. 서버 담당자가 원인을 분류한 뒤 코드 수정 또는 수동 작업을 진행해야 합니다.')
    state=STATES.get(outcome.get('status'),STATES['UNKNOWN'])
    body=(marker+'\n'+ ' '.join('@'+v for v in recipients)+f'\n\n**{component} 자동 배포 확인 필요**\n\n'
          +f'- 대상 코드: `{run["head_sha"]}`\n- 결과: {state}\n- 다음 작업: {text}\n'
          +f'- [실행 결과 확인](https://github.com/{repo}/actions/runs/{run["id"]}/attempts/{run["run_attempt"]})\n\n'
          +'main/배포 브랜치의 병합이 취소된 것은 아닙니다. 코드 문제면 수정 PR을 병합하고, DB·설정 문제면 승인된 수동 작업을 먼저 요청하세요.\n'
          +'알림 전송 실패나 상태 불명은 배포 재실행 사유가 아닙니다.')
    return marker,body
