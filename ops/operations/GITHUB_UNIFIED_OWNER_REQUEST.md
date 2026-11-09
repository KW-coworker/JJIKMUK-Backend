# 저장소 담당자 설정 요청 — 자동 배포 + 승인된 수동 관리

AWS/서버 설정은 아직 적용하지 않습니다. Backend PR17과 AI PR14·15는 병합 완료했습니다. 완료 보고와 초기 적용 승인 전 자동 배포 변수를 켜지 마세요. PR11은 계속 닫힌 상태로 둡니다.

2026-11-10: 백엔드 PR18 병합·필수 검사 추가와 챗봇 저장소의 아래 설정은 완료했습니다. 챗봇 저장소는 `KW-coworker/PRE_REPO`로 이전됐습니다. 같은 설정을 다시 만들지 않고, 이전 대응 코드와 고정 workflow 참조의 정식 반영 후 실제 OIDC 사전검사를 진행합니다. 자세한 순서는 [저장소 이전 반영](REPOSITORY_MOVE.md)을 참고하세요.

## KW-coworker/JJIKMUK-Backend

1. Settings → Environments → `backend-production`: 배포 branch **main만**, required reviewers 없음, 대기 시간 없음. 이 환경은 일반 자동 CD용입니다.
2. `production`: 배포 branch **main만**, required reviewer **fisfin**, Prevent self-review **해제**, 관리자 우회 **차단**. 사용자가 채팅으로 승인한 수동 작업을 Codex가 같은 GitHub 계정으로 승인 제출하기 위한 환경입니다. 팀원 리뷰를 매 배포마다 요구하는 설정이 아닙니다.
3. Settings → Secrets and variables → Actions → Variables: `BACKEND_CD_ENABLED=false` 유지. 준비/최초 적용 검증 후 별도 승인으로 켭니다.
4. main 보호: PR 리뷰 인원 0명 유지, `build`와 새 `operations-validation` 검사는 필수로 지정. **`Server Operations Checks`의 `pull_request.paths` 필터 제거 수정이 main에 병합된 뒤** 새 검사를 필수화합니다. 파일 경로 때문에 실행되지 않는 검사를 필수로 지정하면 일반 PR이 Pending에서 멈출 수 있습니다. 실제 PR에 표시된 검사 이름을 선택합니다. 직접 push/강제 push/브랜치 삭제로 검사를 우회하지 않게 합니다.

기존 두 Environment 설정은 최근 조회에서 확인됐습니다. 다시 만드는 요청이 아니라 위 조건 유지 및 새 필수 검사 추가 요청입니다.

## KW-coworker/PRE_REPO

1. 최신 Python 원본은 **chatbot 브랜치**입니다. 옛 main의 앱 코드를 chatbot에 합치거나 기본 브랜치를 바꾸지 않습니다.
2. PR14는 chatbot에 CI/CD 호출 파일을, PR15는 기본 main에 실패 알림 관찰자와 수동 OIDC 사전검사 파일을 추가했으며 모두 병합됐습니다. GitHub의 `workflow_run`은 기본 브랜치에 관찰자 파일이 있어야 합니다.
3. Settings → Environments → New environment → **chatbot-production**: required reviewers 없음, wait timer 없음. Deployment branches and tags → Selected branches and tags → Branch **chatbot만** 추가.
4. Settings → Secrets and variables → Actions → Variables → **CHATBOT_CD_ENABLED=false** 추가. 아직 true로 바꾸지 않습니다.
5. Settings → Branches 또는 Rules → Rulesets에서 chatbot 보호: 리뷰 인원 0명, 실제 PR의 **cd / build** 검사 필수, 최신 브랜치 반영 요구, 강제 push/삭제 금지. 검사 이름은 CI가 만든 정확한 이름을 사용합니다.
6. Settings → Actions → General: 고정 SHA로 참조하는 KW-coworker/JJIKMUK-Backend의 재사용 workflow와 공식 actions 허용. GITHUB_TOKEN의 `issues:write` 사용을 조직 정책으로 막고 있다면 이 저장소의 실패 알림 workflow에 허용합니다. 코드를 병합하거나 PR을 자동 승인하는 권한은 요구하지 않습니다.
7. 백엔드는 기존 기본 subject 형식을 유지합니다. 이전된 챗봇은 **use_immutable_subject=true**를 유지하며 소유자 ID와 저장소 ID가 포함되는 형식을 사용합니다. 설정을 예전 형식으로 돌리지 않고, CloudShell 전에 실제 토큰 사전검사로 정확한 신원을 확인합니다.

## 알림 받기

GitHub Settings → Notifications에서 참여/멘션 알림의 On GitHub 및 필요하면 Email을 켭니다. CD가 거절되면 관련 PR의 작성자·병합자와 fisfin에게 멘션합니다. GitHub가 이미 병합을 취소하는 것은 아니며, 수정 PR 또는 수동 DB 준비가 필요하다는 안내입니다.

## 설정 이후

담당자는 설정 완료만 알려주면 됩니다. Codex가 PR/검사/실제 OIDC 사전검사를 확인한 후, 사용자에게 최종 AWS 연결 변경 승인을 요청합니다. 그때 기관 관리자 CloudShell 한 번을 진행합니다. 지금 임시 인증 JSON을 만들거나 다운로드할 필요가 없습니다.
