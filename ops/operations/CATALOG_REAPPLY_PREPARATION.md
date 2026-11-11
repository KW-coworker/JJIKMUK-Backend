# 복구 이후 상품 재적용 준비

후속 구현은 [V21 재적용 실행안](CATALOG_V21_REAPPLY.md)을 따른다. 아래는 PR58 준비 당시 기록이며, 갱신 세션과 읽기 재시도는 새 `catalog-reapply` 경로에 연결했다. 실제 재적용은 아직 실행하지 않았다. 용량 읽기 run42955655025는 20GiB gp3/자동확장 상한40GiB/남은9,749,024,768바이트를 확인했다. 결과 파일 저장 누락은 기존 실행 로그로 회수했으며 새 분기에 저장을 추가했다.

백엔드 복구 실행 42953603757은 정상 종료했다. 기존 main 원본 JAR의 60초 health와 DB 메타데이터 검증, 챗봇 동일성, 원본 기록 보존을 확인했다. 상품은 원래 값으로 복원됐고 V21 구조는 유지된다. 이번 준비에서는 상품을 다시 적용하거나 서비스를 정지하지 않는다.

## 장시간 실행

`catalog_credentials.py`는 같은 GitHub 실행의 새 OIDC 토큰으로 같은 Executor 역할의 1시간 자격을 메모리에서 갱신하는 준비 코드다. IAM 설정은 바꾸지 않는다. wall/monotonic 절대 종료 시각은 갱신으로 연장되지 않는다. 모든 서명 요청 직전에 종료·실패 여부를 검사한다. 갱신 실패 시 유효한 이전 자격으로 계속 진행하지 않는다.

이 코드는 아직 실제 재적용 파이프라인에 연결하지 않았다. 연결 시 모든 장기 클라이언트와 Monitor가 같은 갱신 세션을 써야 하며, 호스트·SSM·job·로컬 controller의 apply와 recovery 예산을 함께 설정해야 한다. DB 쓰기나 SendCommand를 자격 갱신 때문에 재전송하지 않는다.

공식 근거: [Boto3 자격 갱신](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html), [GitHub OIDC 요청](https://docs.github.com/en/actions/reference/security/oidc), [AWS Web Identity 발급](https://docs.aws.amazon.com/boto3/latest/reference/services/sts/client/assume_role_with_web_identity.html). 실제 사용 SDK는 기존 lock의 botocore 1.43.119이며, 동시 갱신·강제 실패·서명 전 차단을 그 버전으로 검증한다.

## 제한된 읽기 재시도

기존 Guard의 기본 시도 횟수는 1회다. 새 선택 옵션은 S3 GET 또는 body read의 지정된 transport 오류에만 최초 1회+재시도 1회를 허용한다. 권한·JSON·STOP·binding·TTL·공간 검사는 재시도하지 않는다. 부분 body를 닫고, 성공 응답을 받은 현재 시각으로 다시 검증하며 phase 예산 초과 시 다음 시도로 넘어가지 않는다. 아직 운영 경로에서 이 옵션을 켜지 않았다.

## 용량 확인

`catalog-capacity`는 기존 유지보수 보류 소유자를 확인한 뒤 지정 RDS의 현재 할당 크기·자동 확장 상한·대기 중인 크기 변경과 최신 CloudWatch 여유 공간만 읽는다. SQL·SSM·RDS 수정은 없다.

2026-11-11 03:37 UTC 조회에서 free는 9,749,008,384바이트였고, 5GiB reserve를 제외한 작업 여유는 4,380,299,264바이트다. 로컬 전체 적용·복구 후 파일 크기 증가는 약 5.5GB였지만 이전 132,060건의 부분 적용·복구도 포함되어 정확한 새 작업량과 같지는 않다. 적용뿐 아니라 복구·인덱스·여유분까지 따로 산정하고, 부족하면 서비스가 정상인 현재 상태에서 공간을 확보해야 한다. 자동 확장을 기대하며 reserve를 낮추거나 먼저 쓰기를 시작하지 않는다.

새 재적용은 V21을 포함한 현재 상태를 baseline으로 검증하고 새 dataset·저널·백업을 만든다. 이미 소비된 apply/recover/service 복구, 원본 state와 저널을 재사용해 재실행하지 않는다. 이후 최종 전수 검증과 최신 main 반영을 마친 뒤에만 CD 보류를 해제한다.
