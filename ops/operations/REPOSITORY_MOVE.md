# 챗봇 저장소 이전 반영

챗봇은 `Alphrit/jjikmuk-CO-WORKER-`에서 `KW-coworker/PRE_REPO`로 이전됐습니다. 저장소 ID `1206944262`, 배포 브랜치 `chatbot`, 기본 브랜치 `main`은 같습니다. 소유자는 KW-coworker(ID `304766488`)입니다.

이전 과정에서 GitHub의 기본 OIDC subject는 ID가 포함되는 형식으로 바뀌었습니다. 현재 설정인 `use_default=true`, `use_immutable_subject=true`를 유지하며, 챗봇 역할은 아래 값만 허용합니다. 이름 변경·이전의 동작은 [GitHub 공식 OIDC 설명](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims)을 참고하세요.

```text
repo:KW-coworker@304766488/PRE_REPO@1206944262:environment:chatbot-production
```

연결 도구와 인증 사전검사는 저장소 이름·저장소 ID·소유자 ID·subject·브랜치·커밋·실행 ID를 대조합니다. 이전 이름이나 ID가 다른 토큰은 허용하지 않습니다. 백엔드의 기존 인증 형식과 세 역할의 신뢰 조건, 모든 역할의 작업 권한·경계는 그대로입니다.

챗봇 패키지 명세·배포 출처 검사·실패 알림의 대상 저장소도 새 이름을 사용합니다. Python 챗봇 기능 코드나 DB migration을 바꾸는 작업은 아닙니다.

## 반영 순서

1. 백엔드의 이전 대응 변경을 검토·병합합니다.
2. PRE_REPO의 chatbot 브랜치 `chatbot-cd.yml`, `chatbot-precheck.yml`과 기본 main의 `chatbot-cd-notify.yml`, `chatbot-precheck.yml`이 검증된 새 백엔드 제어 코드 커밋을 고정 참조하도록 각각 PR을 검토·병합합니다. 옛 제어 코드 커밋을 유지하면 새 저장소를 거절합니다.
3. 두 배포 변수는 계속 false로 둡니다. 최신 backend main과 chatbot 커밋으로 실제 OIDC 사전검사를 진행합니다. 이전 저장소에서 성공한 검사나 로컬 모의 토큰 검사는 이 단계를 대신하지 않습니다.
4. 갱신한 단일 helper와 AWS 템플릿의 해시·정확한 연결 변경 목록을 제시하고 사용자 승인을 받습니다. 기존 helper/템플릿 해시로 CloudShell을 실행하지 않습니다.
5. 승인된 연결 뒤 서버를 확인하고 초기 설치·배포·활성화는 별도 승인을 받습니다.

2026-11-10 확인된 backend main에는 새 V18~V20 migration도 있습니다. 서버 DB 적용 여부는 확인하지 않았습니다. 최초 배포 계획에서 별도로 대조하며, 저장소 이전 대응을 이유로 DB를 자동 변경하지 않습니다.

이 변경은 준비 코드입니다. AWS 설정·서버 설치·배포를 실행한 것이 아닙니다. 실제 연결 전에 고정 참조와 인증 검사 결과가 일치하는지 확인해야 합니다.
