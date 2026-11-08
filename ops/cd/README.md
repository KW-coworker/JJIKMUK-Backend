# 승인 후 사용하는 백엔드 CD

GitHub에서 검토된 main의 JAR 하나를 기존 Ubuntu/systemd 백엔드에 반영한다. 개발자 시험용 AI 일괄 허용을 유지하며, OCR 서버·챗봇 Python 코드·DB 구조·운영 설정은 이 배포기의 변경 대상이 아니다.

**이 PR은 실행기를 구현한다. AWS/서버/GitHub 운영 설정을 설치하거나 배포하지 않는다.** `BACKEND_CD_ENABLED`가 없으면 workflow는 실행 작업을 건너뛴다. `config.example.json`도 기본 `enabled:false`다. 예제의 `REPLACE_…` 값은 실제 설정이 아니다. main 병합, 운영 설정, 최초 배포는 각각 담당자 검토와 사용자 승인이 필요하다.

## 사용 흐름

```text
담당자 PR 검토 → main 병합
  → 사용자가 정확한 main SHA와 백업을 지정해 수동 실행
  → 전체 테스트 + 원본 JAR 빌드
  → GitHub production 환경 승인
  → main SHA 재확인 / 백업 상태 확인
  → 임시 AWS 권한으로 S3에 버전 고정 업로드
  → 고정 SSM 문서가 미리 설치된 배포기 실행
  → 현재 상태·DB 이력·파일 해시 확인
  → JAR 연결 변경 + 백엔드 재시작
  → 새 프로세스·API·OCR·챗봇 확인
  → 성공 기록 또는 이전 JAR 복구
```

단일 인스턴스를 재시작하므로 잠깐의 서비스 중단이 발생한다. 무중단 배포를 제공하지 않는다. 운영 중 사용자 데이터 쓰기를 되돌리는 기능도 아니다.

## 구현 파일

| 파일 | 역할 |
|---|---|
| `.github/workflows/backend-cd.yml` | main에서만 수동 배포, 승인·동시 실행 제어·OIDC |
| `.github/workflows/backend-cd-checks.yml` | PR의 Python 회귀 검사와 백엔드 test/bootJar |
| `release.py` | JAR 포장, 동일 파일 대조, 백업 검사, S3 업로드, SSM 1회 요청·결과 조회 |
| `manifest.py` | SHA256·JAR 내부 설정·Flyway SQL/체크섬 비교 |
| `engine.py`, `host.py` | 의도 기록, 원자적 연결 변경, 검증, 제한된 복구 |
| `database_probe.py` | 백엔드 실행 계정으로 Flyway 이력 SELECT만 수행 |
| `deploy.py`, `deploy.ssm.json` | 정해진 인자만 받는 서버 진입점·SSM 문서 |
| `commission.py` | 별도 승인으로 설치·검증된 첫 정상 버전 등록 |
| `config.example.json`, `iam.example.json` | 검토·값 확정이 필요한 비활성 설정·권한 예제 |

Python 실행기는 표준 라이브러리만 사용한다. DB probe는 서버의 별도 승인된 기존 PyMySQL 환경을 사용한다. 백엔드 의존성을 변경하지 않는다. GitHub Actions는 검증한 커밋 SHA로 고정한다.

Gradle wrapper 다운로드 제한은 60초다. 첫 Linux CI에서 기본 10초 다운로드 제한으로 빌드 시작 전에 중단된 것을 반영했다. Gradle 버전·애플리케이션 의존성·검사 기준은 동일하다.

## 변경 전에 멈추는 조건

- 요청 SHA와 실행 SHA가 다르거나, 승인 대기 중 main이 바뀐 경우.
- 같은 계정/서울/DB의 암호화된 available 스냅샷이 없거나 생성된 지 24시간이 지난 경우. 이 검사는 복원 시험이나 RPO 보장을 대신하지 않는다. 스냅샷 생성 권한은 CD에 없다.
- S3 versioning이 꺼져 있거나, 파일 버전·크기·해시·커밋이 일치하지 않는 경우. JAR는 256MiB 이하이고 다운로드 전 2GiB 여유 공간을 요구한다.
- 실행 중 JAR·명령행·작업 폴더·환경·보호 파일이 등록된 기준과 다른 경우. 변경하려면 별도 설정 검토가 필요하다.
- SQL 파일 목록/내용 또는 JAR 내부 properties/yaml이 달라진 경우. 초기 도입 시 OFF 기본값의 개발자 AI 환경변수 별칭 한 줄만 비교에서 정규화한다.
- 실제 Flyway 이력에 실패/누락/추가/체크섬 차이가 있는 경우. DB 구조가 달라지는 릴리스는 별도 계획으로 처리하며 JAR만 되돌려 해결하지 않는다.
- 데이터 import/backfill이 켜져 있거나 DDL 모드가 validate가 아닌 경우, 지원하지 않는 datasource/JPA/Flyway/config override가 있는 경우.
- 미완료 전환 기록이나 같은 실행의 불확실한 임시 파일이 남은 경우. 삭제하고 재실행하지 않는다.

이 검사들은 검토된 코드의 배포를 보조한다. 애플리케이션의 임의 SQL/새 startup 코드까지 정적으로 증명하거나 격리하지 않는다. migration 파일이 같아도 새 코드의 데이터 쓰기는 리뷰해야 한다.

## 별도 승인 후 확정할 운영 설정

1. 현재 서버/프로세스/설정/DB 이력을 새로 조회하고, 예제와 맞는지 확인한다. 현재 인증정보를 GitHub나 작업 로그에 복사하지 않는다. 다른 Spring 설정 방식이 쓰이면 실행기를 우회하지 말고 지원 범위를 PR로 보완한다.
2. repository `production` 환경에 **승인자, 자기 승인 금지, main 배포 제한**을 설정한다. 실제 요금제에서 사용 가능한 보호 기능인지 확인한다. main 규칙에는 `Backend CI / build`와 실제 생성되는 CD 검사 이름을 필수 상태 검사로 연결한다. 이 코드만으로 환경 보호가 생기지 않는다.
3. OIDC 전용 역할을 만든다. 실제 발급되는 repository/production subject와 audience를 확인하여 `iam.example.json`의 정확한 값으로 제한한다. 관리자/이전 작업 역할을 재사용하지 않는다. subject가 environment 기반이면 main 제한은 production 환경 정책으로도 강제한다.
4. 전용 비공개 S3 저장 위치를 준비한다. Public Access Block·versioning·암호화·TLS 정책을 적용하고, 예제 prefix와 역할 권한을 일치시킨다. 예제는 SSE-S3를 전제한다. SSE-KMS를 쓰려면 해당 키의 권한을 별도 검토한다. 과거 릴리스/백업 삭제·자동 수명 정책은 별도 승인 대상이다.
5. 기존 SSM 관리 경로와 EC2 역할에 지정 prefix의 `GetObjectVersion`만 추가한다. 최신 호환 SSM agent가 ENV_VAR 전달을 지원하는지 확인한다. SSH 포트나 일반 원격 셸 권한은 새로 열지 않는다.
6. 고정 SSM 문서를 설치하고 문서 **숫자 버전**을 고정한다. GitHub 역할에 문서 생성·수정·임의 문서 실행 권한을 주지 않는다. `SendCommand`는 문서와 백엔드 인스턴스 모두로 제한한다.
7. `/opt/jjikmuk-cd/bin`에 검토된 Python 파일만 root 소유로 설치한다. 부모/실행기/릴리스는 group/world 쓰기를 금지한다. bin은 앱 계정의 probe 실행을 위해 읽기/진입 가능하게 한다(디렉터리 755, Python 644). `/etc/jjikmuk-cd/config.json`, 상태 파일은 root 전용으로 관리한다. releases/runs 디렉터리도 미리 만들고 불확실한 파일을 지우지 않는다.
8. `config.example.json`에 실제 argv, 작업 폴더, JDBC 대상, DB probe 계정/인터프리터, CA, 검증된 health URL을 채운다. `protected_paths`에는 모든 systemd unit/drop-in/EnvironmentFile, 설정·CA·실행기 파일을 포함한다. 일반 설정 파일은 변경 검출용 해시만 상태에 저장하고 값을 출력하지 않는다.
9. 첫 기준 버전은 **병합된 GitHub main의 원본**으로 별도 승인된 최초 배포를 한다. 검토한 commit/JAR SHA256을 고정하고 `/opt/jjikmuk-cd/releases/<commit>-1-1/backend.jar`에 설치한다. 기존 운영 JAR·unit/drop-in을 보존한 뒤 정확한 `ExecStart`와 `current` 연결을 설정한다. `-Dchatbot.developer-test-auto-consent=true`를 유지한다. 새 설정·재시작은 이번 PR 작업에 포함되지 않는다.
10. 최초 배포가 정상임을 확인한 뒤 명시적 `commission.py --commit <40자리SHA> --expected-jar-sha256 <64자리SHA> --approve-baseline-enrollment`로 기준을 등록한다. 이 도구는 파일 복사·unit 수정·재시작을 하지 않고 상태 검사 후 기준만 기록한다. 기존 baseline이 있으면 덮어쓰지 않는다. 중간 실패 시 남은 manifest/임시 파일을 자동 삭제하지 말고 원인을 검토한다.
11. 아래 변수와 환경 보호를 대조하고 실제 SSM/실패 복구 시험을 승인된 시간에 수행한 뒤 `BACKEND_CD_ENABLED=true`로 활성화한다. 설정만 했다고 실서버 검증 완료로 보지 않는다.

| GitHub 변수 | 설정 위치/내용 |
|---|---|
| `BACKEND_CD_ENABLED` | repository 변수. 초기에는 없거나 false |
| `BACKEND_AWS_ACCOUNT_ID`, `BACKEND_CD_ROLE_ARN` | production 환경. 전용 역할/대상 계정 |
| `BACKEND_CD_BUCKET`, `BACKEND_CD_PREFIX` | production 환경. S3 위치 |
| `BACKEND_INSTANCE_ID`, `BACKEND_DATABASE_ID` | production 환경. 실제 백엔드·DB |
| `BACKEND_CD_DOCUMENT`, `BACKEND_CD_DOCUMENT_VERSION` | production 환경. 고정 문서/숫자 버전 |

상태 확인 URL은 local filters, public filters, DB를 쓰는 고정 상품 조회, OCR health, chatbot readiness, 익명 인증 거부를 모두 포함한다. URL/status/응답 구조를 최초 설정 시 실제 확인한다. 이 기본 검사는 유료 AI/OCR 추론이나 사용자의 로그인·개인 데이터 요청을 실행하지 않으며, 그 기능의 종단 검증을 대체하지 않는다.

## 실패·복구 규칙

- 연결 변경 전에 실패하면 실행 중인 서비스를 바꾸지 않는다. 다운로드된 후보는 보존한다.
- 변경 의도를 디스크에 기록한 뒤 연결을 바꾸고 재시작한다. 새 systemd InvocationID를 요구하므로 기존 JVM이 살아 있다는 이유만으로 성공 판정하지 않는다.
- 재시작/검증 실패 시 보호 설정·이전 JAR·DB 이력을 다시 확인하고 이전 JAR로 한 번 복구한다. 복구 성공도 해당 배포는 실패로 보고한다.
- 전환 기록에는 이전/후보 manifest와 해시가 모두 남는다. 기준 파일을 교체한 직후 프로세스가 죽어도 이전 버전 식별자는 사라지지 않는다.
- `SWITCH_INTENT`, `ROLLBACK_INTENT`, `MANUAL_RECOVERY_REQUIRED`가 남으면 다음 배포를 차단한다. SSM 시간 초과/통신 단절도 재요청하지 않는다. command ID, run 기록, current, baseline, 실제 JVM을 함께 확인한 뒤 별도 승인으로 복구한다. journal/lock을 지워 재시도하지 않는다.
- 성공한 같은 run은 현재 실행 버전까지 같은 경우에만 재시작 없이 결과를 반환한다. 과거 run을 새 배포로 재사용하지 않는다.
- 스냅샷 DB 복원, 데이터 삭제, 인프라 생성, 자동 정리는 구현 범위에 없다. DB 복원은 별도 승인·복구 계획이 필요하다.

## 개발 검증

```bash
PYTHONPATH=ops/cd python3 -m unittest discover -s ops/cd/tests -v
./gradlew test bootJar
```

테스트는 로컬 파일/가짜 명령 경계를 사용하며 AWS 인증·운영 DB·유료 AI를 호출하지 않는다. Linux에서는 실제 자식 프로세스를 전환의 여러 단계에서 종료하여 디스크 기록과 재실행 차단을 확인한다. Windows에서는 해당 POSIX 검사만 skip한다. 실서버 SSM/IAM/서비스 검증은 별도 승인 후 남아 있다.
