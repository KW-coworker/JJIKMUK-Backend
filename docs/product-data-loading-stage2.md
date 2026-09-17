# Product data loading — stage 2

## 목표와 적용 결과

상품 CSV 적재를 API 애플리케이션 시작 과정에서 분리하고, 잘못된 파일이
운영 `products`를 비우는 일을 방지한다. 일반 실행에서는 상품과 추천 CSV
적재가 모두 꺼져 있으며 별도의 non-web 프로필을 사용해야만 실행된다.

새 상품 데이터는 다음 순서로 처리된다.

1. MySQL advisory lock을 획득해 두 적재/롤백 프로세스의 동시 실행을 막는다.
2. CSV 전체를 먼저 읽어 필수 헤더 36개, 모든 행의 컬럼 수, 숫자·식단 플래그
   형식, 전체 행 수, 빈 행 수와 상품명 커버리지를 검증하고 SHA-256을 계산한다.
3. `products_staging`을 현재 `products`와 같은 스키마·인덱스로 생성한다.
4. 스테이징에 배치 적재한다. 중복 바코드는 첫 행을 유지하고 개수를 검증한다.
5. 두 번째 읽기의 SHA-256을 다시 비교하여 검증 도중 파일이 바뀌지 않았는지
   확인한다.
6. 스테이징 DB 행 수, 바코드, 상품명, `product_id` 유일성을 검증한다.
7. `product_id`가 이미 도입된 DB라면 같은 바코드의 기존 내부 ID를 보존한다.
8. 준비가 끝난 경우에만 하나의 MySQL `RENAME TABLE` 문으로 기존 테이블을
   `products_rollback`으로, 스테이징을 `products`로 원자적으로 교체한다.
9. 데이터 버전·원본 SHA-256·활성 행 수와 실행 결과를 기록한다.

검증 또는 스테이징 적재가 실패하면 운영 `products`는 변경되지 않는다.
교체 직후 메타데이터 기록이 실패하면 코드가 즉시 기존 테이블을 복구한다.
프로세스가 강제 종료된 경우에는 테이블 comment에 기록한 데이터셋 마커로
다음 실행 시 버전 상태를 복원한다.

## 실행 전 준비

- Flyway V3가 적용되어 `product_data_import_runs`가 생성되어야 한다.
- 새 파일을 배포할 때마다 `product.import.version`을 반드시 올린다.
- `product.import.expected-rows`를 RFC 4180 기준 논리 행 수와 맞춘다.
- 현재 테이블, 스테이징 테이블, 한 세대 롤백 테이블과 인덱스를 함께 둘 수
  있도록 충분한 디스크 공간을 확보한다. 적재 중에는 최대 약 3세대 공간이
  필요할 수 있다.
- `CREATE TABLE LIKE`가 보존하지 못하는 외래키나 trigger가 `products`에 있으면
  적재기는 안전을 위해 실행을 중단한다.
- 스테이징 적재는 운영 조회를 막지 않지만 디스크 I/O를 사용한다. 트래픽이
  적은 시간에 실행하고 교체 시점의 짧은 metadata lock 대기를 감안한다.
- 현재 상품 테이블은 읽기 중심이다. 적재 중 운영에서 상품 행을 직접 수정하면
  새 CSV 테이블로 교체될 때 그 수정이 사라질 수 있으므로 상품 쓰기를 중지한다.

## 상품 적재 실행

일반 API 실행에서는 `product.import.enabled=false`이다. 빌드한 JAR을 별도
프로세스로 실행한다.

```powershell
.\gradlew.bat bootJar
java -jar build\libs\backend-0.0.1-SNAPSHOT.jar `
  --spring.profiles.active=product-import `
  --product.import.resource=file:C:/absolute/path/Product.csv `
  --product.import.version=V4.0-PRODUCTCSV `
  --product.import.expected-rows=1348436
```

현재 `Product.csv`를 읽기 전용으로 완전 검증한 결과는 1,348,436행, 빈 행
0개, 원본 바코드 결측 1,114,637개, 상품명과 정제 상품명이 모두 없는 행
49개였다. 원본 SHA-256은
`25b56f737e33ca1d501d2677712a1d55ab44e7bca87be414b9ea42db7e018c3e`이다.
이 기준에 맞춰 기본값은
빈 행 0개, 중복 바코드 최대 20개, 상품명 보유율 최소 99%로 설정했다. 새
데이터셋의 검증된 기준이 달라지면 다음 옵션을 함께 변경한다.

```text
--product.import.validation.max-empty-rows=검증된_빈_행_상한
--product.import.validation.max-duplicate-barcodes=검증된_중복_상한
--product.import.validation.minimum-named-ratio=검증된_상품명_비율_하한
```

실행 후 `db/operations/verify_product_data_import.sql`로 활성 버전, 행 수, 최근
실행 기록과 테이블 마커를 확인한다. `PRODUCT_DB_IMPORT_STATUS=COMPLETED`이며
가장 최근 import run도 `COMPLETED`여야 한다.

## 롤백

성공한 적재는 직전 `products`를 삭제하지 않고 `products_rollback`으로 한
세대 보관한다. 문제가 발견되면 별도 프로세스에서 다음과 같이 되돌린다.

```powershell
java -jar build\libs\backend-0.0.1-SNAPSHOT.jar `
  --spring.profiles.active=product-rollback
```

롤백 또한 하나의 원자적 table rename이며 현재 테이블과 이전 테이블을 서로
교환한다. 따라서 같은 명령을 다시 실행하면 직전 상태로 다시 전환할 수 있다.
스키마 마이그레이션으로 두 테이블의 구조가 달라진 뒤에는 실행하지 말고 먼저
호환성을 확인해야 한다.

원본 바코드가 없는 행은 아직 `NO_BARCODE_ROW_<행 번호>` 호환 키를 사용한다.
`product_id`가 도입된 환경에서는 실제 바코드는 바코드로, 그 밖의 행은 유일한
`product_group_key`로 기존 내부 ID를 보존한다. 다만 행 번호 기반 호환 키
자체는 CSV 정렬 변경 시 달라질 수 있으므로, 이를 nullable barcode와 완전히
분리하는 작업은 1단계 문서의 최종 contract 단계로 남아 있다.

## 저장되는 운영 메타데이터

`system_configs`에는 활성·롤백 데이터셋의 버전, SHA-256과 행 수가 저장된다.
`product_data_import_runs`에는 각 실행의 단계, 원본/스테이징/활성 행 수,
중복·결측 통계, 시작·종료 시간과 오류가 남는다. CSV 원본 자체는 저장하지
않으므로 배포한 파일은 기록된 SHA-256과 함께 별도 보관해야 한다.

## 범위

이 단계에서 상품 적재와 추천 후보 적재 모두 일반 애플리케이션 시작에서
분리했다. 추천 후보 파일은 기존의 전체 사전 검증과 스테이징 교체 방식을
유지하며 `recommendation-import` 프로필로만 실행한다. 상품과 추천 데이터의
버전 호환성을 강제하는 기능은 추천 개선 단계에서 추가한다.
