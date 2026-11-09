# 백엔드 main 자동 배포를 위한 GitHub 설정 요청

일반 백엔드 배포는 main 병합 후 자동으로 검사·배포하고, 최초 설치와 별도 DB/챗봇/OCR 작업만 사용자 승인으로 진행하도록 구분했습니다. **PR 리뷰 0명 + 기존 CI build 필수 유지가 가능합니다.**

저장소 관리자에게 아래 설정을 요청합니다. Codex 연결 계정 fisfin은 push 권한만 있고 admin 권한이 없어 환경 설정은 직접 적용할 수 없습니다.

| 항목 | 요청 설정 |
|---|---|
| main 규칙 | PR 경유 + build 필수 유지. 실패 검사 무시/우회 없이 병합 |
| backend-production 환경 | Selected branches and tags → **Branch main 하나만**. Required reviewers 없음, Wait timer 0, 추가 수동/custom 승인 규칙 없음 |
| production 환경 | 별도 서버 관리용. Branch main만, reviewer fisfin, 관리자 우회 끄기, Prevent self-review 끄기 |
| 저장소 변수 BACKEND_CD_ENABLED | 최초 설치 완료 전에는 **false** |

backend-production은 평소 백엔드 자동 배포 경로이므로 사용자나 Codex의 승인 제출을 기다리지 않습니다. production은 초기 설치·수동 DB/챗봇/OCR 작업을 위한 별도 경로입니다. 여기서는 사용자가 채팅에서 승인하면 같은 GitHub 계정의 Codex가 승인 API를 제출합니다. 별도 팀원 리뷰를 매번 요구하는 것이 아니며 독립된 두 사람 승인도 아닙니다.

PR10(개발자 AI 허용), PR13(지속 연결), 새 Backend Auto CD PR을 검토·정식 main 반영하는 순서가 필요합니다. 닫힌 PR11은 다시 열지 않습니다. 이 코드들이 병합되어도 활성화 변수가 false이면 서버를 배포하지 않습니다.

환경 설정과 main 반영 뒤 Codex가 실제 GitHub OIDC 사전검사를 실행합니다. 두 환경의 신원이 확인된 뒤에만 사용자에게 마지막 기관 관리자 CloudShell 1회를 요청합니다. 임시 인증 다운로드나 operator 전환은 없습니다. 실제 AWS 연결·서버 설치·첫 전환/자동 배포 활성화는 구체적인 적용안의 사용자 승인 후 진행합니다.

자동 역할은 백엔드 한 대의 고정 배포 문서만 실행합니다. 더 넓은 두 서버 관리 역할을 자동 CD에 사용하지 않습니다. Server Operations Checks는 경로 필터가 있어 모든 PR의 필수 체크로 추가하지 않습니다. CD 실행기 검사는 새 PR에서 기존 필수 build 안에 포함합니다.

이 요청서는 전달용 문서이며 Codex가 팀원에게 직접 메시지를 보내지는 않았습니다.
