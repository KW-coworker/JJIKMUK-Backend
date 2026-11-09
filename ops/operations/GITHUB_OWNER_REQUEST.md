# 서버 연결을 한 번에 끝내기 위한 GitHub 준비 요청

사용자가 CloudShell에서 임시 인증 파일을 계속 발급·다운로드하지 않도록, GitHub Actions가 AWS 임시 인증을 자동 발급받는 연결을 준비했습니다. 이 PR은 연결 도구와 workflow이며 애플리케이션 배포를 실행하지 않습니다. 실제 AWS 설정·설치·배포는 별도 사용자 승인 후 진행합니다.

저장소 관리자에게 아래 준비를 요청합니다. Codex의 현재 연결 계정 fisfin은 push 권한만 있고 admin 권한은 없어 환경 보호 설정을 직접 적용할 수 없습니다.

1. 이 Draft PR의 권한·실행기를 검토합니다. 검토와 사용자 확인 전에는 병합하지 않습니다. main 반영이 끝나야 수동 workflow를 실행할 수 있습니다.
2. Settings → Environments에서 `production`을 생성하고 required reviewer에 `fisfin`을 지정합니다. 관리자 보호 규칙 우회를 끕니다.
3. Deployment branches and tags는 Selected branches and tags로 설정하고 **Branch main 하나만** 허용합니다. 태그와 와일드카드는 추가하지 않습니다.
4. 현재 사용자와 Codex가 같은 GitHub 신원을 사용하므로 `Prevent self-review`는 끕니다. 사용자가 채팅에서 승인하면 Codex가 같은 신원으로 GitHub 승인 API를 제출하는 설계입니다. 별도 두 사람의 독립 검토가 아닙니다. 이 방식에 동의하지 않으면 설정을 바꾸기 전에 별도 실행자/승인자 설계를 협의해야 합니다.
5. 위 준비가 끝나면 Codex가 AWS 접속 없는 `precheck`를 실행해 dispatch·승인 API·실제 OIDC 신원까지 확인합니다. 성공 전에는 사용자에게 마지막 CloudShell 명령을 실행시키지 않습니다.

기존 main CI의 `build` 필수 검사와 실패 병합 차단은 계속 유지·확인합니다. `Server Operations Checks`는 경로 필터가 있으므로 그대로 모든 PR의 필수 검사로 추가하지 않습니다. PR10은 개발자 AI 허용을 유지하기 위한 별도 검토 대상이고, 닫힌 PR11은 다시 열지 않습니다.

AWS 변경 역할은 지정된 백엔드/챗봇·OCR 서버 2대에서 SSM root 프로그램을 실행할 수 있습니다. 계정 전체 관리자 권한은 없지만 서버 내부 권한은 강하므로 main 코드 검토, exact SHA, 사용자 승인과 production 보호를 함께 사용합니다. 계정이나 서버를 새로 만들거나 IAM 권한을 임의 확대하는 기능은 없습니다.

이 요청서에 따라 설정할 내용을 검토해 주세요. 이번 PR이 병합되더라도 서버 설치·서비스 재시작·앱 배포는 자동으로 발생하지 않습니다.
