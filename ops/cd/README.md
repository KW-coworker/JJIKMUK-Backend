# main 병합 후 백엔드 자동 배포

main에 반영된 원본 백엔드를 GitHub가 테스트·빌드하고 서버까지 자동 반영한다. 평소 배포에는 사용자/Codex 승인, 수동 SHA 입력, 백업 번호 입력이 없다. APK의 API 주소가 같고 API 계약이 호환되면 기존 APK에서 새 서버 동작을 시험할 수 있다.

**구현 준비본이며 현재 서버에는 설치·활성화하지 않았다.** 최초 AWS 연결·설치·초기 전환은 구체적인 적용안 승인 후 수행한다. `BACKEND_CD_ENABLED`가 없거나 false이면 main push도 검사·빌드만 한다.

## 일상 흐름

1. 담당자가 PR을 올리면 기존 필수 `build`에서 CD 실행기 검사와 백엔드 전체 테스트·bootJar를 실행한다. 실패하면 병합 조건을 충족하지 못한다. PR 리뷰 인원 0명 설정은 유지할 수 있다.
2. main 병합 시 `Backend CD`가 해당 커밋을 다시 테스트·빌드한다. 수동 Run workflow는 검사·빌드만 하며 배포하지 않는다.
3. 활성화된 경우 main이 여전히 해당 커밋인지 확인하고 실제 JAR SHA256·내부 설정·SQL 목록을 기록한다.
4. `backend-production` 환경에서 자동 배포 전용 OIDC 역할을 받는다. **이 환경의 승인자는 0명**, 대기 시간은 0이며 branch main만 허용한다.
5. 동일 DB의 최근 24시간 안에 생성된 available·암호화 백업을 자동 선택한다. 없으면 배포를 차단한다. 이 역할은 백업을 만들거나 DB를 복원하지 않는다.
6. 조건부 S3 실행 기록을 남기고 JAR·manifest를 버전 고정 업로드한다. 백엔드 1대에 고정 SSM 문서 1개만 실행한다.
7. 서버가 현재 JAR/설정/DB 이력/후보 파일을 대조한다. SQL 또는 properties/yaml 변경, 미완료 작업, 설정 차이가 있으면 전환 전 중단한다.
8. JAR 연결을 바꾸고 백엔드만 재시작한다. 새 프로세스·상태 API·상품 조회·OCR health·챗봇 readiness·익명 인증 거부·DB 이력을 검사한다.
9. 모든 검사가 같은 새 프로세스에서 최소 60초 연속 정상이어야 성공이다. 검증 제한은 240초다. 실패하면 조건이 맞는 경우 이전 JAR로 한 번 복귀하고 배포는 실패로 표시한다.

main 병합 이후의 실패는 **서버 반영 거부**다. main의 커밋을 자동 삭제하거나 PR 병합을 취소하지 않는다. 빠르게 여러 번 병합되면 실행 중 배포를 중간 취소하지 않고, 대기 중에는 최신 요청을 우선한다. 업로드 후 main 재확인과 서버 run 순서 검사가 오래된 요청의 덮어쓰기를 막는다.

## 범위와 자동 검증의 한계

자동 대상은 백엔드 JAR다. DB 구조/데이터 갱신, Python 챗봇, OCR 코드/모델, 운영 설정은 별도 작업이다. SQL과 설정이 바뀌는 PR은 main에 병합되어도 CD에서 차단될 수 있으므로 담당자가 변경 범위를 알려야 한다.

개발자 AI 일괄 허용은 유지한다. PR10이 정식 main에 먼저 반영되어야 해당 기능이 있는 원본 JAR를 만들 수 있다. 서버에서 임의 패치하거나 이 PR에 앱 코드를 끼워 넣지 않는다. 닫힌 PR11을 재사용하지 않는다.

자동 테스트는 모든 기능 오류를 증명해 없애는 도구가 아니다. 기존 APK와의 API 호환성·새 기능의 기대 동작은 백엔드 담당자가 테스트로 보강해야 한다. UI/응답 계약이 달라지면 새 APK가 필요할 수 있다. 기본 상태 검사는 유료 AI 호출·실제 OCR 추론·사용자 로그인/개인정보 요청을 실행하지 않는다.

단일 서버를 재시작하므로 잠깐의 중단이 있다. 애플리케이션 데이터 쓰기나 DB 변경은 JAR 복귀로 되돌리지 않는다. Flyway 이력 비교는 수동 DDL 전체 fingerprint가 아니며 앱의 임의 SQL 실행을 정적으로 차단하지 않는다.

## 권한과 최초 활성화

PR13의 한 번 연결 도구가 다음 통로를 함께 준비한다.

| 경로 | 환경/역할 | 평소 승인 |
|---|---|---|
| 백엔드 자동 CD | backend-production / JjikmukBackendAutoDeploy | 없음 |
| 상태 조회 | main / JjikmukOperationsRead | 발급·다운로드 없음 |
| 초기 설치·별도 서버 작업 | production / JjikmukOperationsExecute | 사용자 승인 유지 |

자동 역할은 백엔드 고정 문서·인스턴스, S3 artifacts/backend 및 receipts/backend-cd, 백업 메타데이터 조회에 한정한다. OCR 서버 명령·문서 생성·스냅샷 생성·IAM 변경 권한을 주지 않는다. 넓은 관리용 역할을 자동 CD에 연결하지 않는다.

연결 전에 GitHub 관리자에게 두 환경 설정을 요청하고 실제 OIDC 사전검사를 완료한다. 그 뒤 최종 해시가 고정된 연결안을 승인받아 기관 관리자 CloudShell 한 번으로 연결한다. operator 계정 이동이나 임시 인증 다운로드는 정상 절차에 없다.

서버 설치 전에는 정확한 JDBC 대상, 모든 systemd 참조 파일, 실제 무료 health URL/응답, 백업의 자동 생성 상태를 최종 확인한다. `config.example.json`의 미확정 값은 설치용 설정이 아니다. 같은 DB 백업을 자동 확보할 기존 정책이 없다면 최초 적용안에 필요한 백업 설정을 포함한다.

검토된 main에서 `package_install.py`로 설치 묶음을 만들고, OFF 설치→재시작 없는 사전검사→원본 main의 최초 전환/복구 준비→기준 등록→GitHub 변수 활성화 순서로 진행한다. 초깃값은 `BACKEND_CD_ENABLED=false`. 최초 사용자 승인에는 이후 main 자동 배포와 조건부 JAR 복귀를 켠다는 내용을 포함한다. 각 배포마다 다시 승인받는 변수가 아니다.

## 실패 결과와 재실행

GitHub Actions의 Backend CD 실행과 deployment-result artifact에서 커밋/명령 ID/결과를 확인한다.

- SUCCEEDED: 그 실행의 배포 및 검증 성공.
- ROLLED_BACK: 새 버전 검사 실패 후 이전 JAR 복귀. 해당 배포는 실패다.
- STOP_REVIEW_REQUIRED / MANUAL_RECOVERY_REQUIRED: 불일치 또는 복구 조건 미충족. 변경을 계속하지 않고 원인을 확인한다.
- SEND_OUTCOME_UNKNOWN_NO_REDISPATCH / STATUS_UNKNOWN_DO_NOT_REDISPATCH: 응답 불확실. 재전송하지 않고 기존 명령/서버 기록을 조회한다.

동일 커밋의 실행 의도가 있으면 새 SendCommand를 보내지 않는다. 결과 수집 시도만 하며 commit/run/문서/인스턴스/명령 인자를 재확인한다. 통신 실패 뒤 기존 기록을 삭제해 재실행하지 않는다. 전체 workflow 재실행은 기존 결과를 수집할 수 있지만, deploy job만 재실행하면 attempt가 다른 빌드 artifact 때문에 배포 전 중단될 수 있다.

DB/운영 설정이 변경되거나 불확실한 서버 전환이 남으면 다음 자동 배포도 멈춘다. 이는 매번 승인받는 정상 경로가 아니라 장애 대응이다. Codex가 연결된 조회 통로로 원인을 확인할 수 있으며 필요 변경은 승인받는다. 백업/과거 릴리스 자동 삭제는 하지 않고 디스크 부족 시 중단한다.

## 구현과 검사

- `auto_context.py`: main push 신원, 최신 커밋, 자동 백업 선택.
- `release.py`: 고정 SDK, 정확한 JAR, S3 의도/결과, SSM 1회 전송·수집.
- `manifest.py`, `runtime_contract.py`: 원본 JAR/SQL/설정과 관측한 환경 계약.
- `engine.py`, `host.py`: 원자적 전환·상태 검증·한 번 복귀·중단 기록.
- `install_disabled.py`, `preflight.py`, `commission.py`: 최초 승인된 설치/기준 등록.
- `requirements-sdk.lock`, `requirements-db.lock`, `tools.lock.json`: GitHub SDK·독립 DB probe wheel·서버 AWS CLI 해시 고정.

DB probe는 시스템 Python3.12와 CD 전용 PyMySQL wheel을 격리 실행한다. 챗봇 가상환경을 변경하지 않는다. 서버 실행기/도구/운영 설정은 root 소유·해시 보호하며 자동 JAR 배포로 바꾸지 않는다.

```bash
python3 -m pip install --require-hashes --only-binary=:all: -r ops/cd/requirements-sdk.lock
PYTHONPATH=ops/cd python3 -m unittest discover -s ops/cd/tests -v
./gradlew test bootJar
```

로컬/CI 실패 주입은 가짜 AWS·임시 Linux 파일을 사용한다. 실서버 설치·실제 OIDC 역할·SSM·최초 전환·운영 롤백 성공은 별도 적용 후 검증해야 하며 로컬 검사를 그 증거로 대체하지 않는다.
