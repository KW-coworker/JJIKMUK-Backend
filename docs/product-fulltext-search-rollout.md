# Product search — stage 3

## 구현 범위

3단계에서는 검색어 공백 유무에 관계없이 같은 상품을 찾고, 검색 성능과 품질을
운영 데이터로 비교할 수 있도록 다음 항목을 구현했다.

- `search_keywords` 버전형·재개 가능한 배치 백필
- MySQL `ngram_token_size=2` FULLTEXT 인덱스 생성/검증 절차
- LOCATE와 FULLTEXT에 동일한 NFKC·소문자·공백/기호 제거 규칙 적용
- ngram 일부 토큰만 일치하는 잡음을 줄이는 Boolean phrase 조건
- 정확히 일치하는 정제 상품명, 상품명, 접두·부분 일치 순의 재정렬
- 코드로 버전 관리되는 relevance seed 평가셋
- Hit@K, MRR, 0건 비율, 평균/P95 지연시간과 공백 쌍 결과 겹침 측정
- 검색어, 필터, 결과 수와 지연시간의 비동기 검색 로그
- MySQL FULLTEXT와 LOCATE 실행 계획/한계 측정 SQL

`search_keywords`에는 상품명, 정제 상품명, 제조사와 각각의 compact 값만
들어간다. 원재료와 알레르기 문구는 이름 검색에서 오탐을 만들고 인덱스 크기를
늘리기 때문에 포함하지 않는다.

## 검색 동작

예를 들어 `매운 새우깡`과 `매운새우깡`은 모두 `매운새우깡`으로 정규화된다.
`search_keywords`에는 원문과 compact 값을 함께 저장하므로 공백 경계에 걸친
bigram도 생성할 수 있다.

FULLTEXT 후보 조건은 `+"매운새우깡"` 형태의 Boolean phrase를 사용한다.
후보 안에서는 다음 순서로 가산점을 적용한다.

1. 정제 상품명 전체 일치
2. 상품명 전체 일치
3. 상품명 접두 일치
4. 상품명 부분 일치
5. 제조사 전체 일치
6. MySQL natural-language FULLTEXT 점수

FTS 장애 시 사용하는 LOCATE 모드도 같은 compact 쿼리와 우선순위를 사용한다.
다만 컬럼에 함수를 적용하므로 전체 테이블 스캔이 발생할 수 있으며 운영의
주 검색 방식으로 사용하지 않는다.

## 1. 배포 및 백필

일반 API 실행에서는 백필이 비활성화되어 있다. Flyway V4 배포 후 별도
non-web 프로세스로 실행한다.

```powershell
.\gradlew.bat bootJar
java -jar build\libs\backend-0.0.1-SNAPSHOT.jar `
  --spring.profiles.active=search-backfill
```

기본값은 3,000건씩 커밋하고 배치 사이에 100ms를 기다린다. 다음 값으로
운영 부하를 조절할 수 있다.

```text
PRODUCT_SEARCH_BACKFILL_BATCH_SIZE=1000~10000
PRODUCT_SEARCH_BACKFILL_DELAY_MS=0~60000
PRODUCT_SEARCH_KEYWORD_VERSION=v1
```

마지막 바코드와 상태는 `system_configs`에 기록되어 중단 후 이어서 실행된다.
완료 조건은 다음과 같다.

- `PRODUCT_SEARCH_BACKFILL_STATUS=COMPLETED`
- `PRODUCT_SEARCH_KEYWORD_VERSION=v1`
- `search_keywords IS NULL`인 행이 0개
- `PRODUCT_SEARCH_UNSEARCHABLE_ROWS` 수치 확인

키워드 생성 규칙을 바꿀 때는 버전을 올리고
`PRODUCT_SEARCH_BACKFILL_REBUILD_ALL=true`로 전체를 다시 생성한다. FULLTEXT
인덱스가 이미 있으면 행마다 FTS도 갱신되어 부하가 커지므로 기본적으로 실행을
거부한다. 정말 필요하면 측정된 점검 시간에만
`PRODUCT_SEARCH_BACKFILL_ALLOW_WHEN_INDEXED=true`를 사용한다.

## 2. FULLTEXT 인덱스 생성

백업과 스테이징 리허설 후 저트래픽 점검 시간에
`db/operations/create_products_search_fulltext_index.sql`을 수동 실행한다.
스크립트는 백필 결측, `ngram_token_size`, 기존 인덱스, `FTS_DOC_ID`, 장기
트랜잭션을 먼저 확인한다.

MySQL의 ngram parser는 CJK를 지원하지만, `ngram_token_size=2`이면 한 글자
검색어를 인덱싱할 수 없다. 그래서 API는 검색어를 2~100자로 제한한다.
첫 InnoDB FULLTEXT 인덱스 추가는 사용자 정의 `FTS_DOC_ID`가 없을 경우 테이블
재구성이 발생할 수 있고, `ALGORITHM=INPLACE`여도 동시 DML은 허용되지 않는다.
따라서 스크립트는 `LOCK=SHARED`로 조회만 허용하고 상품 쓰기를 중단하는
점검 시간을 전제로 한다.

참고:

- https://dev.mysql.com/doc/refman/8.0/en/fulltext-search-ngram.html
- https://dev.mysql.com/doc/refman/8.0/en/innodb-online-ddl-operations.html
- https://dev.mysql.com/doc/refman/8.0/en/create-index.html

## 3. relevance 기준선 측정

`ProductSearchRelevanceDataset`의 v1 seed는 다음을 포함한다.

- 단백질칩 / 단백질 칩
- 두유바 / 두유 바
- 매운새우깡 / 매운 새우깡
- 포키, 초코파이, 신라면, 꼬깔콘

각 케이스는 화면에 보이는 상품명 또는 정제 상품명에 사람이 지정한 compact
상품명이 포함되는지를 판단한다. 실제 `Product.csv`를 끝까지 확인하여 모든
seed 판단에 대응 상품이 존재하는 것도 검증했다.

먼저 LOCATE 기준선을 저장한다.

```powershell
$env:PRODUCT_SEARCH_EVALUATION_MODE='locate'
java -jar build\libs\backend-0.0.1-SNAPSHOT.jar `
  --spring.profiles.active=search-evaluation
```

인덱스 생성 후 같은 데이터와 장비에서 FULLTEXT를 측정한다.

```powershell
$env:PRODUCT_SEARCH_EVALUATION_MODE='fulltext'
java -jar build\libs\backend-0.0.1-SNAPSHOT.jar `
  --spring.profiles.active=search-evaluation
```

각 쿼리는 기본 1회 warm-up 후 3회 측정한다. 결과는
`product_search_evaluation_runs`와 `product_search_evaluation_results`에
남는다. 기본 통과 기준은 다음과 같다.

- Hit@K 80% 이상
- MRR 0.5 이상
- 공백 유무 쌍의 Top-K Jaccard overlap 80% 이상
- P95 DB 검색 시간 1,000ms 이하

현재 10개 케이스는 파이프라인 검증용 seed일 뿐 최종 품질을 대표하지 않는다.
검색 로그에서 자주 검색되는 쿼리와 0건 쿼리를 표본 추출하고, 사람이 관련
상품을 판정하여 최소 50~100개 케이스로 확장해야 한다. 평가셋 버전이 바뀌면
기존 실행 결과와 섞이지 않도록 `VERSION`도 올린다.

## 4. 검색 로그

검색 및 필터 API는 다음 값을 `product_search_logs`에 비동기로 기록한다.

- SEARCH/FILTER 구분
- 정규화 검색어와 compact 검색어 SHA-256
- 적용 필터와 match 모드
- LOCATE/FULLTEXT 모드
- 결과 수
- DB 검색 소요시간
- 선택적으로 사용자 ID

로그 큐가 가득 차거나 DB 로그 INSERT가 실패해도 상품 검색 응답은 실패하지
않는다. 기본적으로 검색어 원문은 저장하고 사용자 ID는 저장하지 않는다.
개인정보 정책에 따라 다음 환경 변수로 바꿀 수 있다.

```text
PRODUCT_SEARCH_LOGGING_STORE_QUERY_TEXT=false
PRODUCT_SEARCH_LOGGING_STORE_USER_ID=false
```

`db/operations/analyze_product_search_logs.sql`로 일별 검색량, 0건 비율, 평균
지연시간, 빈번한 0건 검색어와 평가 결과를 확인한다. 로그 보존 기간은 팀 정책을
정한 뒤 배치 삭제해야 하며, 예제 SQL은 90일을 제안만 하고 자동 삭제하지 않는다.

## 5. 확인할 MySQL 한계

`db/operations/measure_product_search_limits.sql`은 같은 검색어의 FTS와 LOCATE
실행 계획, 데이터/전체 인덱스 크기, 단일 문자 점수를 측정한다. 운영과 같은
스펙의 복사 DB에서 실행한다.

현재 설계의 알려진 한계는 다음과 같다.

- bigram이므로 한 글자 검색을 지원하지 않는다.
- 오타, 초성 검색, 동의어와 의미 기반 검색은 처리하지 않는다.
- Boolean phrase는 잡음을 줄이지만 글자 순서가 달라진 표현에는 엄격하다.
- MySQL natural-language 점수는 도메인 학습 랭커가 아니므로 로그 기반 조정이
  필요하다.
- FULLTEXT 인덱스는 디스크와 상품 적재/수정 비용을 증가시킨다.
- 인덱스 생성 DDL은 중단·부하 제한이 어렵고 복제 지연을 만들 수 있다.

이 한계로 Hit@K나 0건 비율이 목표를 충족하지 못하면 MySQL에 동의어 사전을
계속 덧붙이기보다 OpenSearch/Elasticsearch 또는 별도 검색 서비스 도입을
검토한다.

## 롤백

장애 시 `PRODUCT_SEARCH_MODE=locate`로 재시작한다. 긴급 상황에서 컬럼이나
FULLTEXT 인덱스를 바로 삭제하지 않는다. 조회 복구 후 별도 점검 시간에 제거
여부를 판단한다.
