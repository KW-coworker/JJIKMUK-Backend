# V17 배포·기존 상품 영양성분 기준량 백필 안내

대상: `nutrition-v1`, 원본 기준량 보존, 100g/100ml/전체 용량 구분.
API 계약은 [nutrition-basis-v1.md](nutrition-basis-v1.md)를 따른다.

**Git push는 배포·DB 적용이 아니다. 이 문서는 서버 담당자가 승인 후 실행할 절차이다.**
이 작업에서 AWS·운영 DB에 접속하거나 변경하지 않았다. 로컬 덤프로 운영 전체를 덮어쓰지 않는다.

## 1. 변경 범위와 배포 준비

- V17: `products.nutrition_basis_raw VARCHAR(255) NULL` 추가.
  기존 `products_staging`, `products_rollback`이 있으면 동일한 열 추가.
- 데이터 백필: 대조를 통과한 상품의 새 열만 UPDATE. 기존 열량·영양값·원재료·알레르기·이미지는 변경하지 않는다.
- 실행 순서: **대상 확인 → 백업/복원 확인 → 복제 DB 검증 → V17 → 대상 DB에서 plan → 검토 후 apply → verify → API/앱 검증**.
- 새 JAR는 이 브랜치의 승인된 커밋으로 빌드한다. 기존 CSV는 JAR/Git에 포함되지 않으며,
  데이터 담당자에게 별도 비공개 경로로 전달받아야 한다. CSV가 없으면 컬럼만 만들 수 있고 백필은 불가능하다.
- Kotlin/Java 빌드와 운영 Java는 JDK 21, 유지보수 실행기는 Python 3.11 이상을 사용한다.
- 코드 배포만으로 기존 데이터가 채워지지 않는다. 기존 적재기에서 CSV 전체 재적재를 켜는 방식으로 해결하지 않는다.
- 이번 브랜치는 최신 main의 챗봇 본인 검증·서명·외부 AI 동의 처리를 유지한다.
  관련 서버 설정을 제거하거나 이전 브랜치의 JAR로 덮어쓰지 않는다.

## 2. 대상 서버와 백업 확인

서버 담당자가 접속한 세션에서 다음을 기록한다. UUID와 MySQL hostname은 접속용 DNS 이름과 다를 수 있다.

```sql
SELECT DATABASE(), @@server_uuid, @@hostname, VERSION();
SELECT installed_rank, version, success
FROM flyway_schema_history ORDER BY installed_rank DESC LIMIT 5;
SHOW CREATE TABLE products;
SHOW INDEX FROM products;
SELECT COUNT(*) AS products FROM products;
SELECT COUNT(*) AS missing_product_id FROM products WHERE product_id IS NULL;
SELECT COUNT(*) AS product_triggers FROM information_schema.triggers
WHERE trigger_schema=DATABASE() AND event_object_table='products';
```

- 성공한 V16이 전제이다. 이미 V17이면 Flyway validate와 실제 컬럼을 확인한다.
  V15 이하 또는 V18 이상이면 이 절차를 그대로 실행하지 말고 버전 차이를 먼저 정리한다.
- 상품 ID가 비어 있으면 먼저 ID 발급 작업을 검증한다. 이번 도구는 ID를 새로 발급하지 않는다.
- 상품 UPDATE trigger가 있으면 부수 효과를 먼저 검토한다. 도구는 trigger가 있는 테이블에 백필하지 않는다.
- 상품 CSV 교체·상품 편집·다른 백필을 작업 중 중단한다. 사용자 계정 테이블은 수정하지 않는다.
- 승인된 전체 DB 백업/스냅샷을 생성하고 SHA-256·시각·대상·복원 방법을 기록한다.
  백업을 별도 DB에 복원해 사용할 수 있는지 확인한다. 단순히 파일이 생겼다는 것만으로 완료 처리하지 않는다.
- 원본 백업, CSV, 계획 파일, 로그는 접근 제한 경로에 보관한다. 공개 GitHub/PR/공개 링크에 첨부하지 않는다.

V17은 `ALGORITHM=INSTANT`를 명시한다. FULLTEXT가 있는 테이블 등에서는 지원되지 않을 수 있다.
**운영과 같은 FULLTEXT·스키마를 복제해 먼저 실행해야 한다.** 오류가 나면 자동으로 인덱스를 지우거나
INPLACE/COPY로 바꾸지 않는다. 테이블 재구성·락·여유 공간·작업 시간을 검토하고 별도 승인을 받는다.
INSTANT여도 시작 시 metadata lock을 기다릴 수 있으므로 장기 트랜잭션을 확인한다.

## 3. 유지보수 도구 실행 환경

도구는 Spring 애플리케이션을 시작하지 않는다. 같은 bootJar의 클래스·MySQL/Flyway 라이브러리를
임시 경로에 풀어 Java 유지보수 프로그램만 실행한다. 테스트 프로필·전체 상품 적재를 켜지 않는다.

```bash
./gradlew test bootJar
```

서버에서는 승인된 CI 빌드 JAR를 사용할 수도 있다. `plan`과 `apply`는 동일한 JAR여야 한다.
아래 Linux 예시는 저장소 루트에서 실행한다. Windows도 같은 Python 실행기를 사용할 수 있으며,
환경변수는 `$env:NUTRITION_SCHEMA='...'` 형식으로 지정한다.

```bash
export NUTRITION_URL='jdbc:mysql://<DB_HOST>:3306/jjikmuk?sslMode=VERIFY_IDENTITY&useCursorFetch=true&serverTimezone=Asia/Seoul'
export NUTRITION_SCHEMA='jjikmuk'
export NUTRITION_UUID='<직접 조회한 server_uuid>'
export NUTRITION_HOST='<직접 조회한 MySQL hostname>'
export NUTRITION_USER='<작업 계정>'
read -r -s -p 'DB password: ' NUTRITION_PASSWORD
export NUTRITION_PASSWORD
export NUTRITION_CSV='/secure/nutrition/Product.csv'
```

- 비밀번호는 환경의 Secret Manager/보호된 주입 방식 또는 위와 같은 비표시 입력으로 전달한다.
  명령행 인수·Git·로그·채팅에 넣지 않는다. 환경변수도 같은 OS 계정의 다른 프로세스에 노출될 수 있으므로
  전용 작업 계정을 사용하고 작업 후 해제한다. 셸 추적(`set -x`)을 켜지 않는다.
- 원격 DB는 서버 환경에 맞는 인증서/TLS 설정을 사용한다. 접속 오류 해결 목적으로 TLS를 임의 해제하지 않는다.
- `NUTRITION_UUID/HOST/SCHEMA`가 실제 접속 대상과 다르면 중단한다.
- DDL 단계는 승인된 migration 계정, 데이터 단계는 필요한 SELECT/해당 컬럼 UPDATE 권한만 가진 계정을 권장한다.
- 아래 `/secure/nutrition/*`는 예시 경로이다. 각 단계는 **새 output 디렉터리**를 사용한다.
  파일을 덮어쓰지 않으며 실패 후 기존 로그를 지우고 재시도하지 않는다.

## 4. 복제 DB에서 먼저 검증

복원한 DB의 URL/스키마/UUID/hostname으로 위 변수를 바꾸고 아래 5~7단계를 수행한다.
`NUTRITION_WRITE_APPROVAL=backup-clone-reviewed`는 담당자의 확인 표시이며,
도구가 백업 생성이나 복원 검증을 대신했다는 뜻은 아니다.
복제 DB에서 계획·변경 건수, 기존 필드 보존, 부하, 잠금, 포키 환산값을 확인한 후 운영 작업 시간을 승인한다.
운영 적용 시 운영의 새 백업과 새 계획을 만든다. 복제 DB용 plan을 운영에 재사용할 수 없다.

## 5. V17 적용 (스키마만)

```bash
export NUTRITION_WRITE_APPROVAL='backup-clone-reviewed'
python3 scripts/run_nutrition_maintenance.py migrate \
  --jar build/libs/backend-0.0.1-SNAPSHOT.jar --output /secure/nutrition/migrate-01
```

- Flyway validate 후 V17까지만 migrate한다. V1~V16 checksum은 수정하지 않는다.
- V17 적용 후 다시 실행할 경우 새 output 경로에서 `executed=0`이어야 한다.
- MySQL DDL은 전체 트랜잭션 롤백이 아니다. products 이후 staging/rollback ALTER에서 실패할 수도 있다.
  부분 실패 시 실제 열·Flyway 이력을 확인하고 중단한다. 무조건 재실행하거나 `flyway repair`로 성공 처리하지 않는다.
- V17 후 새 코드를 `ddl-auto=validate`로 배포할 수 있다. 백필 전 상품은 기준량 UNKNOWN으로 나오는 것이 정상이다.
  실행 환경의 `HIBERNATE_DDL_AUTO=validate`, `PRODUCT_IMPORT_ENABLED=false`,
  `PRODUCT_IMPORT_ROLLBACK_ENABLED=false`, `RECOMMENDATION_IMPORT_ENABLED=false`,
  `PRODUCT_DATA_MODEL_BACKFILL_ENABLED=false`, `PRODUCT_SEARCH_BACKFILL_ENABLED=false`를 확인한다.
  이 영양 기준량 작업과 무관한 전체 적재·분류/검색 백필을 동시에 켜지 않는다.

## 6. 대상 DB의 기존 상품과 CSV 대조 (읽기 전용)

```bash
python3 scripts/run_nutrition_maintenance.py plan \
  --jar build/libs/backend-0.0.1-SNAPSHOT.jar --output /secure/nutrition/plan-01
```

`plan-summary.json`과 `plan.jsonl`을 검토한다.

- 바코드/합성 키로 후보를 찾고 **상품명·제조사·품목보고번호·원천·전체 용량·일곱 영양 수치**를 모두 대조한다.
- DB에 기준량이 이미 있거나 CSV 기준량이 없으면 건너뛴다. 기존 빈 문자열도 자동 덮어쓰지 않는다.
- 중복 바코드는 제외한다. `NO_BARCODE_ROW_n` 합성 키는 원본 CSV의 행 순서와 데이터셋이 같다는 확인이 필요하다.
  키만 같고 상품/수치가 다르면 수정하지 않는다. 행 순서·데이터셋이 다르면 해당 상품을 억지로 연결하지 않는다.
- 계획에 DB의 `productId`와 비교 필드 해시를 고정한다. apply에서 현재 행과 다시 비교한다.
- CSV SHA-256, JAR SHA-256, DB 대상, plan SHA-256을 기록하고 대표 표본을 검수한다.
- 로컬 결과 289,044건은 참고치일 뿐 서버의 목표 건수가 아니다. 서버 데이터가 다르면 다른 건수가 정상일 수 있다.
- `0g` 같은 잘못된 원본 기준도 원문 보존 대상이며 API에서는 UNKNOWN이다. 전부 100g으로 보정하지 않는다.

## 7. 검토한 계획만 적용

```bash
export NUTRITION_PLAN_DIR='/secure/nutrition/plan-01'
export NUTRITION_PLAN_SHA256='<plan-summary.json에서 검토한 planSha256>'
python3 scripts/run_nutrition_maintenance.py apply \
  --jar build/libs/backend-0.0.1-SNAPSHOT.jar --output /secure/nutrition/apply-01
```

- 명시한 SHA-256, 계획의 대상 DB, CSV/JAR 해시가 다르면 거부한다.
- 500건마다 행 잠금 → ID/원본 필드/기준량 NULL 재확인 → 새 열만 UPDATE → 읽기 재확인 → 커밋한다.
- 잠금 대기는 5초로 제한한다. 서비스 응답·DB I/O·복제 지연을 감시하고 문제가 있으면 중단한다.
- 모든 배치가 하나의 트랜잭션은 아니다. 중간 실패 시 **앞서 커밋된 배치는 남고 현재 배치는 롤백**된다.
  프로세스가 commit 직후 종료되면 로그의 건수보다 실제 반영이 많을 수도 있다. 현재 DB와 계획을 대조해야 한다.
- 실패 후 같은 계획을 무작정 재적용하지 않는다. 변경 행을 대조한 다음 새 plan을 만들고 새 해시를 승인한다.
  이미 채워진 기준량은 새 계획에서 제외한다. 전체 작업을 처음부터 재적재하지 않는다.

## 8. 검증과 FE·AI 배포

```bash
python3 scripts/run_nutrition_maintenance.py verify \
  --jar build/libs/backend-0.0.1-SNAPSHOT.jar --output /secure/nutrition/verify-01
```

`applied.json`, `verification.json`, `pocky-samples.json`을 기록한다.
포키 두 바코드가 없으면 검증 건수가 0~1일 수 있으므로 이를 성공 2건으로 보고하지 않는다.
동일 바코드의 배합/용량이 변경돼 220kcal와 다르면 도구가 중단하므로 실제 라벨을 다시 확인한다.
상품·사용자·이력 건수와 새 열을 제외한 기존 상품 필드 보존도 백업/복제본과 별도로 대조한다.

실제 배포 API에서 다음을 확인한다(환경에 따라 로그인 토큰 필요).

```text
GET /api/products/8801019311673
GET /api/products/8801019311673/variants
GET /api/products/search?keyword=포키

data.product.nutrition.sourceBasis.raw = "100g"
data.product.nutrition.per100g.values.energyKcal = 500.0
data.product.nutrition.perPackage.amount = 44
data.product.nutrition.perPackage.values.energyKcal = 220.0
```

위 경로는 상세 응답 기준이다. 검색은 `data[].product`, 옵션은 `data.options[].data.product`를 확인한다.
원본 기준량 미상·용량 미상·g/ml 불일치 상품은 전체 용량 열량이 null인지 확인한다.

- FE: 전체 열량 표시를 `nutrition.perPackage.values.energyKcal`로 변경한다. 기존 `energyKcal=500`을
  `44g`와 붙여 표시하지 않는다. null을 0 또는 기존 값으로 대체하지 않는다.
- AI: `product.nutrition`을 수용하고 기준량을 명시한다. 환산값에 44/100을 다시 곱하지 않는다.
  기존 chat-analysis-v2, 본인 확인·서명·동의 계약을 그대로 유지한다.
- 실제 휴대폰/AI 답변 QA를 완료하기 전에는 서버 응답 검증만으로 앱 표시까지 완료했다고 보고하지 않는다.

## 9. 실패 시 복구

1. 상품 적재/편집과 추가 백필을 멈추고 실패 로그·plan·DB 현재 상태를 보존한다.
2. 앱 표시 문제면 우선 이전 정상 앱/백엔드 릴리스로 되돌릴 수 있다. 추가 nullable 컬럼은 유지한다.
3. 데이터 보정 취소가 필요하면 백업을 **별도 복구 DB**에 복원해 적용 대상 행을 대조한다.
   운영 사용자·이력까지 로컬 전체 덤프로 덮어쓰지 않는다.
4. 계획의 productId/바코드/원본 필드가 그대로이며 현재 기준량이 이번에 넣은 값인 행만,
   백업의 이전 기준량(NULL)으로 되돌리는 역보정을 검토한다. 이후 다른 사람이 바꾼 행은 자동 복구하지 않는다.
5. 새 열을 DROP하거나 Flyway 이력을 삭제하지 않는다. DDL 부분 실패는 별도 스키마 복구 계획으로 처리한다.
6. 작업 종료 후 작업용 자격증명을 폐기/회수하고 비밀번호 환경변수를 해제한다.

## 10. 이번 검증 범위

- 기존 로컬 전체 백업·복제 검증 후 로컬 289,044행 백필, 포키 두 바코드 220kcal 확인.
- 업로드 브랜치는 최신 main에 영양 변경만 적용했다. 별도 알레르기·추천 미커밋 작업은 포함하지 않았다.
- 최종 회귀 363개 중 357개 통과, 6개 조건부 생략, 실패 0개. `test bootJar` 성공.
- 배포 도구는 별도 로컬 MySQL 격리 스키마에서 V17 적용/재실행 0건, 포키 2건 백필/220kcal,
  재계획 0건/빈 계획 적용, 잘못된 계획 해시/서버 UUID 거부를 검증했다.
- AWS·운영 DB와 FE/AI 저장소는 변경하지 않았다. 서버 실제 버전·FULLTEXT 구성·부하 검증은 담당자 작업이다.
