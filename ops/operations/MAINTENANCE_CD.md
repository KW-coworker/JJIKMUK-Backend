# DB·OCR 수동 배포와 백엔드 CD 자동 조정

`maintenance_control.py` 한 번으로 승인된 작업의 대기·실행·검증·최신 main 반영·자동 CD 재개까지 관리한다. 기존 GitHub 로그인을 사용하며 새 AWS 키, CloudShell, 관리자 권한 확대를 요구하지 않는다. 구체 SQL·상품 데이터·OCR 파일은 각 작업 계획에 따로 지정하고 승인받는다.

## 실행 순서

1. 작업·검증 계획의 원본 main 커밋, 파일 해시, 승인 기록을 확인한다.
2. `Server maintenance`가 백엔드 CD와 같은 실행 그룹에서 기다린다. 실행 중인 CD를 강제로 취소하지 않는다. `queue: max`로 대기 작업을 보존하되 GitHub의 100개 상한을 넘거나 실행이 취소되면 완료로 처리하지 않는다.
3. 기존 비공개 S3에 작업 ID별 불변 기록과 조건부 중단 상태를 저장한다. 일반 CD는 이 상태에서 서버 반영을 보류한다. 저장소 `BACKEND_CD_ENABLED` 값은 건드리지 않는다.
4. GitHub 실행기가 사라진 뒤에도 남을 수 있는 두 서버의 SSM 명령 종료를 기다린다. 백엔드 공통 잠금·기존 미완료 기록과 실제 실행 파일·환경·DB·상태 API를 확인한다.
5. 고정 작업 계획을 한 번 실행하고, 별도 검증 계획과 백엔드 전체 상태 검사를 통과하면 `VERIFIED`로 기록한다. 아직 CD를 재개하지 않는다.
6. 관리 workflow 종료 후 컨트롤러가 현재 main을 읽는다. 서버에 없으면 `Backend CD`에 해당 작업 ID를 전달해 테스트·빌드·배포·검증한다. 작업 중 main이 더 바뀌면 최신 커밋을 다시 따라간다. 최대 10회이며 계속 바뀌면 중단 상태를 유지한다.
7. 별도 `finish` 실행이 공통 잠금 아래 현재 백엔드 프로세스·JAR·환경·DB·6개 상태 검사를 60초 연속 재확인한다. 앞뒤로 main도 확인해 일치할 때만 S3 상태를 `OPEN`으로 바꾸고 일반 CD를 재개한다. 이후 새로 병합되는 코드는 일반 CD가 처리한다.

`WORKING → VERIFIED → OPEN`은 S3 ETag 조건부 쓰기와 전이별 고유 ID로 보호한다. 자동 만료나 무조건 잠금 해제는 없다. 별도 서버의 OCR 작업도 이 전체 절차 안에서 백엔드 CD와 겹치지 않게 수행한다. 직접 SSH·DB 관리 도구로 실행한 명령까지 자동 통제하는 기능은 아니다.

## 작업 계획과 승인 입력

main의 `ops/operations/plans/*.json`에 고정 작업 계획과 고정 검증 계획을 둔다. 기존 `run.load_plan` 형식이며 두 계획은 같은 `db` 또는 `ocr` 컴포넌트·승인 ID를 사용한다. 작업의 operation은 `deploy`, `install`, `verify` 중 하나, 검증은 `verify`다. 개인정보·운영 SQL 데이터·모델 같은 비공개 내용은 기존 비공개 패키지 전달 경로를 사용한다.

SQL이나 보호 설정을 바꾸는 작업은 **승인된 구·신 계약 및 필요한 baseline 전환과 검증을 작업 계획에 포함**해야 한다. 이 자동 조정 기능이 임의 SQL을 만들거나 기존 DB/설정 호환성 검사를 완화하지 않는다. 데이터만 바뀌고 구조·설정이 같으면 기준 전환이 불필요할 수 있다. 작업 자체의 백업·복구는 각 패키지가 담당한다.

컨트롤러 요청 JSON은 `inputs`와 `approval`을 담는다. `inputs`는 `mode=apply`, `expected_sha`, 고유 32자리 `request_id`, `work_plan`, `work_sha256`, `verify_plan`, `verify_sha256`, `confirm=true`다. `approval.status=APPROVED`, `approval.input_sha256=connection.sha(connection.canonical(inputs))`로 승인된 정확한 입력을 묶는다. 이 파일을 만드는 것만으로 사용자 승인이 생기는 것은 아니다. Codex가 실제 사용자의 승인 범위를 기록한 뒤 준비한다.

```powershell
python -B ops/operations/maintenance_control.py --request <승인된-요청.json> --journal <새-기록-폴더>
```

사용자는 작업 내용과 범위를 승인하고 Codex가 위 실행을 관리한다. 관리용 `production` 환경 승인도 그 기록에 따라 컨트롤러가 제출한다. 일반 팀원의 main 배포는 계속 별도 승인 없이 동작한다.

## 실패·통신 단절·조회

- 작업/검증/새 배포 실패: 중단 상태를 유지하고 원본 기록을 보존한다. 같은 SQL·SSM 명령·패키지를 재전송하지 않는다.
- 프로세스/통신 단절: 새 실행으로 작업을 덮어쓰지 않는다. `--collect`는 현재 S3 상태만 조회하며 SQL·설치·재시작·서버 명령을 실행하지 않는다.
- 마지막 OPEN 쓰기가 성공한 뒤 응답만 유실될 수 있다. 쓰기를 재시도하지 않고 정확한 전이 ID를 읽어 확인한다. 마지막 artifact만 유실됐다면 컨트롤러가 상태 조회로 최종 검증 증거를 수집한다. 조회까지 실패하면 **재개 여부 불명확**이며, 중단 유지나 완료를 단정하지 않는다.
- 사람이 `BACKEND_CD_ENABLED=false`로 비상 중단한 경우 그 값을 자동으로 다시 켜지 않는다.
- 실행 사이에 예상치 못한 서버 변경이나 실패한 과거 배포 기록이 있으면 자동 우회하지 않는다.

```powershell
python -B ops/operations/maintenance_control.py --collect --journal <기존-기록-폴더>
```

DB/OCR 실데이터 변경 없이 시험하려면 별도로 승인된 고정 조회 전용 작업·검증 계획을 사용한다. 조회 리허설 성공이 새 SQL/모델의 품질·복구 가능성을 대신 증명하지는 않는다.

## 검사와 도입

S3 조건부 갱신·소유자 충돌·중단 후 재실행 거부·실행 중인 SSM·각 작업 단계 실패·main 연속 변경·최종 응답 유실·수동 비상 중단을 회귀검사한다. 기존 서버의 CD 파일을 교체하지 않고 설치된 검증기를 사용한다.

GitHub는 [`concurrency.queue: max`](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)를 지원한다. actionlint 1.7.12는 이 키를 아직 인식하지 못하는 [알려진 제한](https://github.com/rhysd/actionlint/issues/657)이 있어 이 키의 값·공통 그룹·중단 옵션은 별도 검사하고, 나머지 workflow 문법은 actionlint로 검사한다.

최초 도입 때에는 변경 이전 버전의 실행 중/대기 workflow가 남지 않았는지 먼저 확인한다. 새 concurrency 설정은 과거 실행에 소급되지 않는다. 코드 PR 병합은 이미 활성화된 일반 CD를 실행하므로 배포 승인 범위를 함께 확인한다.
