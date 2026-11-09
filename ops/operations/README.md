# 한 번 연결한 뒤 사용하는 서버 작업 통로

이 변경은 매번 CloudShell에서 STS 파일을 발급·다운로드·전달하던 절차를 GitHub OIDC로 교체한다. 연결 성공 후 Codex는 기존 GitHub 로그인으로 조회·설치·배포·검증·복구를 실행하고 결과를 회수한다. AWS 임시 인증은 각 GitHub 작업에서 자동 발급되며 사용자 PC나 채팅으로 전달하지 않는다.

**현재는 준비 코드다. 이 PR만으로 AWS 역할이나 서버 파일을 만들지 않는다.** 정식 main 반영·GitHub 보호 설정·정확한 AWS 연결안 승인 후 사람이 기관 관리자 CloudShell 한 곳에서 `connect_once.py`를 한 번 실행하는 순서다. operator 로그인, 세션파일 export, 사용자 결과 다운로드가 없다. 설정 성공은 GitHub의 실제 OIDC 조회 실행까지 확인한 뒤 판정한다.

## 대상과 권한

기관 `076767081522`, 서울, 백엔드·챗봇 `i-06350403fe0400e1b`, OCR `i-0feac4ca32779b098`를 대상으로 한다. 기존 EC2 instance profile/role `JjikmukMigrationHost`는 유지하고 새 전용 S3의 읽기 inline policy만 추가한다. 공유 대상이 다른 인스턴스까지 늘었거나 boundary가 있으면 사전검사에서 멈춘다.

| 주체 | 자동으로 받는 권한 |
|---|---|
| `JjikmukOperationsRead` | 계정/서울의 인프라 메타데이터, 두 서버의 고정 비밀 제외 상태 점검, 기존 실행 결과·연결 보고서 조회 |
| `JjikmukOperationsExecute` | production 승인 후 두 서버에서 검토한 작업 문서 실행, 전용 S3 파일 업로드/조회, 지정 DB의 새 snapshot 생성·조회 |
| 서버의 기존 역할 | 새 S3의 operations/artifacts prefix 읽기. 기존 정책·다른 bucket 권한 유지 |

두 GitHub 역할은 같은 제한 managed policy를 권한과 permissions boundary에 함께 사용한다. IAM 수정·계정 로그인 관리·네트워크/인스턴스 생성·삭제·DB 복원·Secret Manager 조회 권한은 주지 않는다. 접속 가능한 서버는 두 개지만 EC2/RDS의 Describe 메타데이터 권한은 API 제약상 계정/리전 단위다.

**변경 역할은 두 서버에서 SSM을 통한 root 프로그램 실행이 가능한 강한 권한이다.** IAM만으로 프로그램의 모든 동작을 “JAR 교체만”으로 강제하지 않는다. 실제 범위는 main에 검토된 작업 문서·해시·사용자 승인·GitHub 보호 설정으로 제한한다. 애플리케이션이 가진 DB 접근도 고려해야 하므로 DB 데이터 수정은 별도 승인 없이 수행하지 않는다. 아직 OCR·챗봇 배포 구현과 운영 검증이 끝난 것은 아니며, 이후 각 작업을 준비·승인하되 새 AWS 인증 교환은 필요 없게 만드는 통로다.

## 한 번의 연결에서 만드는 것

CloudFormation stack `Jjikmuk-ServerOperations`에 GitHub OIDC provider(없을 때만1개), 조회·변경 역할과 각 policy, private/versioned/AES256 S3 bucket과 TLS 정책, 고정 조회·백엔드 CD SSM 문서2개, 기존 host role의 새 S3 읽기 policy를 만든다. 기존 OIDC provider는 audience/URL이 맞으면 재사용하고 수정하지 않는다. 최대10개 stack resource, provider 재사용 시9개다. 대상 bucket은 `jjikmuk-operations-076767081522-apne2`다.

앱 설정·서비스·DB 데이터는 이 연결 과정에서 변경하지 않는다. CloudFormation `DisableRollback=True`로 부분 실패의 기록·리소스를 보존하고 setup을 반복해 덮어쓰지 않는다. 정상 완료 시 비밀 없는 결과를 S3 `connection/setup.json`에 남기므로 Codex가 직접 확인할 수 있다. IAM 전체관리자 역할을 Codex에게 넘기거나 장기 access key를 만들지 않는다.

## CloudShell 실행 전에 끝나야 할 GitHub 준비

1. 이 workflow/도구를 검토해 main에 반영한다. 사용자 정책대로 앱 배포도 GitHub main 원본만 사용한다. 개발자 AI 허용 기능은 별도 PR10 검토가 필요하며 PR11은 닫힌 채 유지한다.
2. 저장소 관리자가 `production` 환경을 만들고 custom branch policy를 **branch `main` 하나**로 제한하고 관리자 우회를 끈다.
3. 현재 Codex와 사용자의 GitHub 연결 신원은 `fisfin`(ID166599710) 하나다. 채팅의 명시 승인을 Codex가 같은 신원으로 GitHub에 제출하려면 required reviewer에 fisfin을 넣고 `prevent_self_review=false`로 설정해야 한다. 이는 두 사람의 독립 승인 방식이 아니다. 같은 계정에서 자기승인금지를 켜면 승인 단계가 막히므로 이 설정을 숨기거나 동작한다고 가정하지 않는다. 독립 검토를 원한다면 별도 실행자/승인자 연결 설계를 확정해야 하며 사용자의 AWS 계정 왕복으로 해결하지 않는다.
4. `control.py check`에서 기존 GitHub 로그인·push 권한·환경을 확인한다. 현재 연결 계정은 repo admin이 아니어서 위 설정을 직접 적용할 수 없다.
5. Codex가 `precheck` workflow를 실행하고 사용자의 승인에 따라 production 승인 API를 제출한다. 이 작업은 AWS에 접속하지 않고 실제 GitHub OIDC 토큰의 저장소·main·production·run 신원을 검사한다. 토큰 자체는 기록하지 않는다. 이 정확한 main에서 성공한 이력이 있어야 CloudShell 도구가 진행된다. 이 단계가 성공하기 전에 사용자에게 CloudShell 작업을 요청하지 않는다.

CloudShell 도구는 main SHA·repository ID·OIDC subject 설정·production reviewer/main 제한/관리자 우회를 먼저 대조한다. GitHub 준비가 안 된 상태에서 사용자에게 명령을 먼저 실행시키지 않는다. 아직 배포되지 않은 준비 파일을 곧바로 실행할 명령은 제공하지 않는다. 최종 고정 main URL·helper SHA·template SHA가 포함된 단일 명령은 선행조건 완료 후 확정한다.

## 실행과 승인

- `precheck`: AWS 연결 전 GitHub 실행·승인·실제 OIDC 신원 경로 검증. AWS API·서버 명령은 없다.
- `inspect`: main의 고정 읽기 job, 읽기 역할. 서비스 상태/디스크 등 비밀 없는 요약만 artifact에 기록한다. 상세 원문은 public GitHub 로그로 출력하지 않는다.
- `execute`: main에 있는 승인된 `ops/operations/plans/*.json`의 정확한 SHA를 입력한다. production 승인·명시 confirm·최신 main·첫 run attempt가 필수다. 문서 이름과 실행 의도를 S3에 먼저 기록하고 조건부 쓰기로 같은 계획의 재전송을 막는다.
- `collect`: 읽기 역할로 기존 operation ID의 결과만 조회한다. SendCommand 응답이 끊겼다면 comment와 문서/대상을 대조해 기존 명령을 찾고, 불확실하면 재전송하지 않는다. 이 조회에는 새 AWS 인증파일이나 추가 CloudShell 작업이 없다.

`control.py`는 기존 Git credential helper를 메모리에서만 사용한다. 채팅 승인에 바인딩된 입력 SHA와 고유 request ID가 있어야 dispatch/production 승인 API를 호출한다. 연결 설정 이후에는 사용자 명시 승인 범위 안에서 Codex가 이 API를 실행한다. 승인 기록은 작업 통제이며 IAM이 채팅 메시지를 읽어 강제하는 기능은 아니다.

배포별 계획은 변경과 필요한 복구를 하나의 승인 범위로 묶는다. 기존 backend CD의 JAR 복귀를 재사용하되 최초 설치/전환·OCR·챗봇의 실제 작업과 복구 프로그램은 각각 검증한 뒤 추가한다. access setup 성공이 모든 배포의 성공이나 모든 데이터의 복원 가능성을 의미하지 않는다.

## 기존 백엔드 CD와 연결할 값

`BACKEND_CD_ROLE_ARN=arn:aws:iam::076767081522:role/JjikmukOperationsExecute`, bucket=`jjikmuk-operations-076767081522-apne2`, prefix=`artifacts/backend`, document=`Jjikmuk-BackendDeploy-v1`, version=`1`을 사용한다. 백엔드 config의 S3 값도 반드시 같아야 한다. `BACKEND_CD_ENABLED=false`를 유지하고 설치·초기 전환은 별도 승인한다. 기존 CD schema/config/backup 보호를 완화하지 않는다.

## 검증 및 한계

로컬 unit 검사는 권한 범위, main/승인/해시 거부, 부분 setup 보존, 유실 응답 중복 전송 차단, 수집 전용 경로, 비밀 원문 출력 거부를 확인한다. AWS 템플릿은 cfn-lint로, workflow는 actionlint로 검증한다. 고정 SDK lock은 별도 audit한다. 실제 AWS 연결/OIDC·두 서버 상태·GitHub 승인 실행은 아직 미검증이다.

현재 두 서버·계정·권한 범위를 유지하는 작업은 자동 인증으로 수행한다. 연결을 삭제하거나 계정/서버·권한 범위를 바꾸면 재설계가 필요할 수 있다. 기존 임시 세션을 만료 후 재발급받는 절차는 이 연결의 정상 운영 경로가 아니다.

공식 근거: [GitHub의 AWS OIDC 연결](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws), [환경 승인과 자기승인 설정](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments), [AWS OIDC Provider 리소스](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-iam-oidcprovider.html).
