# 속성 이력 · 내부 상품 ID · 카테고리 정책의 단계적 전환

작성일: 2026-10-28. 현재 작업 트리의 구현이며 배포 완료를 뜻하지 않는다.
운영 DB와 로컬 원본 `jjikmuk`에는 이번 변경을 적용하지 않았다.

## 1. 적용 범위

| 단계 | 구현한 내용 | 이번에 하지 않은 내용 |
| --- | --- | --- |
| 속성 이력 | 불변 관측 스냅샷, 이전 관측 연결, 출처·확신도·변경 사유·실행자·데이터 버전 기록 | 실제 제조 리뉴얼 확정, 외부 SQL 변경의 자동 감지, 누락 근거 추정 |
| ID 전환 | 기존 ID 보존, 미할당 ID 배치 발급, ID 조회 API, 신규 행동 이력의 ID/스냅샷 참조 | barcode PK 제거, 기존 이력의 추정 백필, 모든 AI/추천 후보 저장소의 ID 전환 |
| 카테고리 | 복수 카테고리 유지, 미분류 배타 처리, 소비 용도 비교, 알려진 용도 불일치 제외 | 전체 상품 재분류, 모든 용도 확정, 동일 상품 자동 병합 |

`product_group_key`는 화면 중복 제거 키다. 이미지·명칭·원재료가 같다는 이유로 영구 ID를 재사용하지 않는다.
`productId`는 현재 카탈로그 자료 행의 식별자이며 검증된 `variant_id`/`revision_id`가 아니다.
동일 바코드의 새 데이터는 같은 ID에 새 관측을 붙일 수 있지만, 이것만으로 같은 실물 버전이라고 판정하지 않는다.

## 2. 속성 이력

V15가 `product_attribute_snapshots`와 `products.attribute_snapshot_id`를 추가한다.

- 상품명, 제조사, 원재료, 경고, 영양, 총량, 이미지, 분류, 식단 플래그 및 기존 출처/확신도를 화이트리스트 JSON으로 보존한다.
- `datasetVersion`, `observedAt`, `observedBy`, `ruleVersion`, `changeReason`, `changedFields`, `payloadHash`, `previousSnapshotId`를 기록한다.
- 동일 내용 재시도는 새 스냅샷을 생성하지 않는다. 이전 관측은 덮어쓰지 않는다.
- `null` 확신도를 임의 숫자로 바꾸지 않는다. 스냅샷 수집은 판정 근거의 신뢰도를 높이지 않는다.
- 직접 SQL로 상품을 바꿀 때 자동 감사가 생기는 구조는 아니다. 최초 baseline을 확보하고, 이후 승인된 적재/수집 경로를 사용해야 한다.
- 수집 시각은 제조일/리뉴얼 적용일이 아니다. 데이터 수집 이력과 실제 상품 리뉴얼은 별개다.

스테이징에서 만든 관측도 보존한다. 실패한 적재의 관측이 최신 ID일 수 있으므로,
조회 시 `activeSnapshotId`와 비교해야 한다. 단순히 가장 최근 관측을 활성 데이터로 해석하면 안 된다.
미활성 관측은 `datasetVersion`과 적재 실행 기록으로 추적한다.

## 3. ID 발급·재적재 정책

- 기존 `product_id`는 변경하지 않는다. 새 ID는 `product_id_sequence`에서 잠금 후 구간 예약한다.
- 예약은 별도 트랜잭션으로 커밋하고 데이터셋 교체/롤백과 분리한다. 번호의 빈 구간은 허용하되 예약 번호 재사용은 하지 않는다.
- 초기 발급은 활성/스테이징/롤백/관측 테이블에 남은 최대 ID도 확인한다. 이미 삭제된 과거 자료의 번호까지 복원할 수 있다는 뜻은 아니다.
- 실제 바코드가 일치하는 행만 기존 ID와 관측 포인터를 이어받는다.
- `NO_BARCODE_ROW_*`와 화면 그룹 키로 기존 ID를 재사용하는 경로는 제거했다. 출처 키·검수 매핑이 없는 무바코드 재적재 행은 새 임시 ID를 받는다.
- 이 때문에 무바코드 상품의 재적재 전후 즐겨찾기 연결이 끊길 수 있다. 다른 상품으로 잘못 옮기는 것보다 보수적인 과도기 정책이다. 안정적인 원본 키와 승인 매핑 도입이 후속 작업이다.
- 기존 CSV 중복 바코드의 첫 행을 유지하는 동작은 아직 남아 있다. 중복 원본 전체 보관/버전 분류 경로는 별도 구현이 필요하다.

새 행동/스캔 이력은 `productId`, `attributeSnapshotId`를 함께 저장한다. ID가 기록된 이력은 그 ID가 사라져도 바코드로 다른 상품을 찾아 붙이지 않는다.
구형 무바코드 이력은 현재 상품과 연결하지 않는다. 구형 실제 바코드 이력은 `LEGACY_VERSION_UNKNOWN`으로 표시한다.
이력 응답의 `product`는 현재 활성 정보이며 당시 화면 복원본이 아니다. 당시 관측 ID를 별도로 보존한다.
개인화 이력 조회에도 같은 ID 우선 규칙을 적용한다.

## 4. 소비 용도 정책

탐색용 14개 카테고리 ID는 유지한다:
`snack`, `dessert`, `convenience`, `beverage`, `dairy`, `bakery`, `noodles`, `meat`,
`seafood`, `plant`, `sides`, `condiments`, `special`, `unclassified`.

- 복수 분류는 모두 유지한다. 알려진 분류가 있으면 `unclassified`를 함께 노출하지 않는다.
- 지원하지 않는 저장값은 원문을 지우지 않고 `categoryAssessment.unknownStoredValues`에 표시한다.
- 상품 응답에 `categoryAssessment`를 추가한다: `policyVersion`, `categoryIds`, `usage`, `evidence`, `needsReview`, `unknownStoredValues`.
- 대체 추천에는 별도 `categoryCompatibility`를 제공한다: `MATCH`, `MISMATCH`, `UNKNOWN`과 양쪽 용도, 사유, 규칙 버전.
- 아이스크림/어묵, 소스/장아찌, 만두/육가공품, 완제품/제조용 믹스처럼 **알려진 용도 차이**만 차단한다.
- 이름·식품유형 충돌이나 근거 부족은 `UNKNOWN`이다. UNKNOWN을 식품 안전성 PASS나 같은 상품으로 변환하지 않는다.
- 용도 UNKNOWN 후보는 이번 단계에서 자동 제외하지 않는다. 따라서 아직 부적절한 대체가 남을 수 있다. 안전/필수 식단 UNKNOWN 처리와 별개의 축이다.
- 우유와 두유처럼 탐색 카테고리가 달라도 같은 음료 용도이면 대체 후보가 될 수 있다. 알레르기·식단 검사는 별도로 먼저 수행한다.

규칙은 작고 보수적인 진단용 규칙집 `consumer-purpose-v1`이다. 모든 식품을 분류한 공인 기준이 아니다.
기존 DB의 membership 행은 수정하지 않았다. 새 적재는 정규화된 분류를 사용하지만,
기존 membership 검색/분류 통계는 별도 재구축 전까지 원래 저장값을 따를 수 있다.

설정 `RECOMMENDATION_CATEGORY_POLICY`:

| 값 | 동작 |
| --- | --- |
| `enforce-known` (기본값) | 알려진 용도 MISMATCH를 일반 추천과 fallback에서 모두 제외 |
| `observe` | 용도 판정/횟수만 관찰, 용도 때문에 후보를 제외하지 않음 |

`excluded.categoryMismatch`는 후보-조건별 불일치 횟수다. observe에서는 실제 제외 횟수가 아니다.
`excluded.categoryUnknown`은 불확실 관찰 횟수이지 제외 횟수가 아니다.
기존 안전·식단·기피성분 제한은 두 모드 모두 그대로 유지한다. 최종 추천 점수 가중치도 변경하지 않았다.
홈의 카테고리별 탐색은 기준 상품 간 대체 비교가 아니므로 기존 복수 카테고리 방식을 유지한다.

## 5. 추가/확장 API

### 사용자 API

| Method | 주소 | 설명 |
| --- | --- | --- |
| GET | `/api/products/id/{productId}` | 내부 ID로 현재 상품 조회·분석 |
| GET | `/api/products/id/{productId}/variants` | 내부 ID로 용량 옵션 조회 |
| GET | `/api/recommendations/products/id/{productId}` | 내부 ID 기준 대체 추천 |
| POST | `/api/histories/events` | 기존 barcode 외 productId 입력도 지원 |

기존 바코드 주소는 삭제하지 않았다. 상세/용량 조회는 기존 인증·가족 선택 계약을 그대로 사용하고,
대체 추천은 로그인이 필요하다. `analysisMode`, `includeSelf`, `familyProfileIds`, 호환 `userId` 처리도 같다.
대체 추천의 `limit=10`, `minScore=0.2` 기본값도 유지한다.
양수가 아닌 ID는 400, 현재 활성 상품이 없는 ID는 404다. 은퇴한 ID를 다른 상품으로 리다이렉트하지 않는다.
아직 ID 미할당인 환경의 상품 응답은 `productId=null`일 수 있다. baseline 전에는 `attributeSnapshotId=null`이다.

```json
{"productId": 90001, "actionType": "FAVORITE"}
```

`barcode`와 `productId` 중 하나 이상이 필요하다. 둘 다 보내면 동일 상품을 가리켜야 하며 불일치는 400이다.
응답 `data`에 기존 `eventId`, `barcode`, `actionType`, `createdAt`과 함께 `productId`, `attributeSnapshotId`가 추가된다.

`GET /api/products/classifications`의 `data.categoryPolicy`:

```json
{"version":"consumer-purpose-v1","multiLabel":true,"unclassifiedExclusive":true,"substitutionUsesPurpose":true}
```

### 관리자 작업 API

아래 주소는 JWT의 `ROLE_ADMIN`만 허용한다. 무인증 401, 일반 사용자 403이다.
관리자 계정을 자동 생성하지 않는다. 승인된 유지보수 창에서만 사용한다.

| Method | 주소 | 요청/응답 |
| --- | --- | --- |
| POST | `/api/admin/catalog/ids/backfill?batchSize=500` | 1~1,000행, `data.attempted`, `data.assigned` 반환. attempted=0까지 반복 |
| POST | `/api/admin/catalog/attributes/capture` | 아래 JSON. `data.scanned`, `data.changed`, `data.nextAfterBarcode` 반환 |
| GET | `/api/admin/catalog/products/{productId}/attribute-history?page=0&size=20` | `data` 관측 목록, `activeSnapshotId`, `semantics` 반환 |

```json
{
  "datasetVersion": "실제_활성_데이터셋_버전",
  "reason": "INITIAL_BASELINE_BEFORE_NEXT_IMPORT",
  "afterBarcode": "",
  "batchSize": 200
}
```

첫 요청은 빈 afterBarcode로 시작하고 반환된 nextAfterBarcode를 다음 요청에 사용한다.
`scanned=0`이 종료 조건이다. `changed=0`은 동일 데이터일 수 있으므로 종료 조건이 아니다.
작업자는 서버가 `ADMIN:<인증 사용자 ID>`로 기록한다. observedBy를 앱에서 임의 지정하지 않는다.
history의 page는 0~10,000, size는 1~100이다. 스냅샷 `payloadJson`은 JSON 문자열이므로 필요 시 한 번 파싱한다.

## 6. 실제 DB 적용 순서 — 아직 미실행

1. 원본 백업과 복제 스테이징을 확보하고 활성/롤백 테이블, Flyway 버전, 여유 디스크를 확인한다.
2. 현재 소스의 선행 V14와 V15를 복제 스테이징에서 먼저 검증한다. 이번 테스트는 V15의 신규 ID/기존 AUTO_INCREMENT 두 경로를 작은 별도 스키마에서 검증한 것이며 전체 운영 스키마 리허설이 아니다.
3. `product_id` 유일 인덱스 존재 여부·중복을 검사한다. 없을 때만 `db/operations/index_product_internal_id.sql`을 측정된 작업 시간에 실행한다. 기존 AUTO_INCREMENT의 유일 인덱스는 재생성하지 않는다. 과거 `add_product_internal_id.sql`을 V15 이후 다시 실행하지 않는다.
4. 유지보수 API로 ID 백필을 작게 나눠 실행한다. 인덱스 없이 전체 백필을 시작하지 않는다. 오류/부하가 생기면 중단하고 조사한다.
5. 변경 전 현재 데이터의 baseline 관측을 수집한다. ID와 baseline이 비어 있는 기존 행이 있으면 다음 CSV 교체는 의도적으로 거부한다.
6. ID 결측/중복, 관측 포인터와 product_id 일치, 미처리 페이지, 실행자·데이터셋 버전을 검증한다.
7. 승인된 CSV 적재를 별도 프로세스로 실행한다. 신규 ID 예약 → 실제 바코드 ID/이전 관측 유지 → 신규 ID 발급 → 변경 관측 생성 → 검증 → 원자적 교체 순서다.
8. ID API와 프론트 이력 저장을 순차 전환한다. 기존 후보 집합·분류 membership·챗봇은 아직 바코드 소비자가 있으므로 barcode PK를 제거하지 않는다.

관리자 백필/관측 수집과 적재/롤백/외부 상품 쓰기는 동시에 실행하지 않는다. ID 예약 자체의 동시성은 보호되지만 카탈로그 전체 쓰기의 조정은 별도 유지보수 절차다.
관측 JSON과 인덱스로 저장량/redo가 늘어난다. 134만 행의 소요 시간·디스크·I/O를 이번 소형 테스트로 예측할 수 없다.
V15 이전 롤백 테이블에는 새 열이 없을 수 있다. 자동 롤백은 이를 거부하며, 먼저 스키마 호환성을 검증해야 한다.
DB 전체 복원 시 상품만 복원하지 말고 관측·시퀀스·이력·버전 기록도 함께 보존해야 한다.

## 7. 검증과 남은 작업

- 최종 `test bootJar` 성공: 전체 184개 중 178개 성공, 6개 건너뜀, 실패 0개. 건너뜀은 기존 CSV 의존 4개와 opt-in 평가 2개다. 고정 추천 평가는 별도로 실행했다. localhost HTTP 상태 검사 65/65도 통과했다.
- H2: ID 보존/동시 예약/구형 롤백 최대 ID, 관측 추가·동일 재시도·잘못된 연결 거부, 구형 합성 바코드 이력의 오연결 방지, 용도 차단을 검증한다.
- HTTP: 내부 ID 상세·용량·추천·행동 저장과 관리자 경로 401/403을 검증한다.
- 별도 localhost MySQL 8.0.44: V15 신규/기존 ID 스키마, 합성 ID 미재사용, 실제 바코드 ID 보존, swap/rollback을 검증했다. 임시 스키마는 제거했고 원본 DB 쓰기는 0건이다.
- 고정 상품·후보로 추천 1,270회를 재실행했다. 1,050개 확대 조건에서 알려진 용도 불일치 5,440회가 제외되었다(고유 상품 수 아님). 기존 20개 모드 일치와 Hit@10 13/13, NDCG@10 0.870583은 유지되었다.
- 확대 조건 모드: VERIFIED 420→418, RELAXED_SAFE 169→165, VERIFICATION_REQUIRED 446→452, ACTION_REQUIRED 15→15. 용도 필터 때문에 일부 검증 추천이 확인 후보로 바뀐다.
- 평가기의 메밀가루/밀가루 라벨 경고 2건은 양쪽 모두 남는다. 기존 검수 이력을 유지하며 신규 탐지 누락이나 안전 성공으로 재해석하지 않는다.

용도 UNKNOWN의 잔존 오추천, 근거 보강, 제조사/원본 레코드의 안정적 연결, 전문가 gold/독립 holdout 구축,
전체 DB/실제 적재/프론트·AI 호환 검증, 속성별 승인 수정 경로, 완전한 옵션·리뉴얼 모델은 후속 단계다.
이번 변경은 검색 오타/복합어 처리나 FULLTEXT 인덱스 도입까지 수행한 것은 아니다.

로컬 비교 결과: `C:/Visual_Studio_Code/식품DB/catalog-evolution-20261028/report.html`.
