# 추천·사용자 이력 API 명세

[공통 규칙과 전체 목록](README.md), [Product 전체 필드](products.md). 상품 ID·응답 값은 설명용 예시이다.

2026-10-28 추가: [ID 기반 추천·행동 이력, 용도 MATCH/MISMATCH/UNKNOWN 계약](../catalog-evolution-stage1-3.md).
이력 입력은 barcode 또는 productId 중 하나 이상이며 둘 다 입력 시 동일 상품이어야 한다. 기존 바코드 주소는 유지한다.

## R01. 맞춤 안심 상품 추천·카테고리별 보기

```http
GET /api/products/safe-recommendations
Authorization: Bearer {token}
```

### 기본 정보

| 항목 | 내용 |
|---|---|
| 기능 | 기준 상품 없이 로그인 사용자 조건에 맞춘 상품을 탐색하고 카테고리별로 묶어 반환 |
| 인증 | 필수. URL이 /api/products 아래여도 이 API는 로그인 필요 |
| Body | 없음 |
| 성공 | 200 OK. 결과 없음도 200 |

### Query Parameter

| 이름 | 타입 | 기본값·제한 |
|---|---|---|
| limit | integer | 기본 20, 1~50. 카테고리별 수량이 아닌 고유 상품 전체 수량 |
| cursor | string | 첫 요청 생략. 이후 응답의 nextCursor 그대로 전달. 최대 1000자 |
| seed | integer(Long) | 생략 시 생성. 반복 시 같은 세션의 seed 사용. cursor와 함께 보내면 일치해야 함 |
| excludeBarcodes | string 목록 | 이미 받은 바코드, 쉼표 또는 반복 파라미터. 중복 제거 후 최대 200개 |
| categories | string 목록 | 선택 카테고리 ID. 여러 개면 하나 이상에 속한 상품 |
| userId | integer(Long) | 생략 권장. 본인 자동 적용, 타인 지정은 관리자만 가능 |

page·size·filters·categoryMatch 파라미터는 이 API의 계약에 없다. 선호는 요청 JSON이 아닌 서버의 사용자 specialDiet에서 가져온다.

### 추천 정책

- 알레르기 DANGER·UNKNOWN은 제외하고 PASS만 반환한다.
- 기피 식재료가 표기에서 확인되는 상품 및 질환에서 유도한 건강 조건이 MISMATCH·UNKNOWN인 상품도 제외한다.
- specialDiet는 대체 상품 추천과 동일한 필수 조건이다. 후보가 부족해도 완화하지 않는다. 질병 파생 조건과 합친 dietConstraints가 PASS인 상품만 반환한다.
- diseases에서 유도하는 현재 매핑: 당뇨/혈당→lowSugar, 고혈압/혈압→lowSodium, 고지혈/이상지질/심혈관→lowFat, 비만/체중조절/다이어트→lowCalorie, 셀리악/글루텐→glutenFree. 이는 구현 규칙 설명이며 의학적 기준을 보장하는 설명이 아니다.
- 기피 식재료 매칭은 현재 정규화 후 2자 이상 문자열 포함 기준이다. 임의 식재료에 대한 완전한 알레르기 검증으로 설명하지 않는다.
- 최대 5000개 후보를 스캔하고, 통과 후보가 limit만큼 모이면 탐색을 끝낸다. seed로 시작 지점과 현재 구간의 순서를 달리하는 방식이며 전체 DB 균등 무작위 추출이나 전체 DB 선호 최적 순위를 보장하지 않는다.
- 알레르기 미등록 사용자는 현재 안전성 판정에서 PASS가 된다. ‘모든 알레르기에 안전함’의 의미가 아니다.

### 요청 예시

```http
GET /api/products/safe-recommendations?limit=10&categories=snack,dessert
Authorization: Bearer {token}
```

```http
GET /api/products/safe-recommendations?limit=10&categories=snack,dessert&cursor={직전 nextCursor}&excludeBarcodes=8800000000001,8800000000002
Authorization: Bearer {token}
```

### 성공 응답

아래는 상품 1개를 반환한 예시이다. **product 내부만 일부 필드를 발췌**했으며 실제 Product 전체 필드는 상품 명세 P06을 따른다. 나머지 응답 필드는 모두 표시한다.

```json
{
  "message": "맞춤 안심 상품 추천 성공",
  "data": {
    "requestId": "11111111-1111-4111-8111-111111111111",
    "userId": 42,
    "seed": 12345,
    "requestedLimit": 1,
    "returnedItemCount": 1,
    "returnedBarcodes": ["8800000000001"],
    "requestedCategoryIds": ["snack"],
    "preferenceFilterIds": [],
    "hardHealthFilterIds": [],
    "requiredDietFilterIds": [],
    "policyVersion": "unified-hard-constraints-evidence-v5.1",
    "recommendationMode": "PREFERENCE_MATCHED",
    "categories": [{
      "categoryId": "snack",
      "categoryName": "과자·스낵",
      "items": [{
        "product": {"barcode":"8800000000001","productName":"예시 과자","foodCategoryIds":["snack"]},
        "safety": {
          "status": "PASS",
          "conflictingAllergens": [],
          "evidenceSources": ["raw_materials"],
          "evidenceLevel": "INGREDIENT_DERIVED",
          "confidence": 0.7,
          "message": "등록된 알레르기 조건이 없습니다."
        },
        "healthConstraints": {
          "attributes": [],
          "status": "PASS",
          "requiredFilters": [],
          "satisfiedFilters": [],
          "failedFilters": [],
          "uncertainFilters": [],
          "evidenceOrigin": "INFERRED",
          "confidence": null,
          "message": "등록된 필수 식단 조건이 없습니다."
        },
        "preferences": {
          "attributes": [],
          "status": "PASS",
          "requiredFilters": [],
          "satisfiedFilters": [],
          "failedFilters": [],
          "uncertainFilters": [],
          "evidenceOrigin": "INFERRED",
          "confidence": null,
          "message": "등록된 필수 식단 조건이 없습니다."
        },
        "dietConstraints": {
          "status": "PASS",
          "requiredFilters": [],
          "satisfiedFilters": [],
          "failedFilters": [],
          "uncertainFilters": [],
          "evidenceOrigin": "INFERRED",
          "confidence": null,
          "message": "등록된 필수 식단 조건이 없습니다.",
          "attributes": []
        },
        "preferenceRelaxed": false,
        "categoryIds": ["snack"]
      }]
    }],
    "nextCursor": "example-opaque-cursor",
    "hasNext": true,
    "scannedCandidateCount": 1,
    "exclusions": {
      "danger": 0,
      "unknownSafety": 0,
      "dislikedIngredient": 0,
      "healthMismatch": 0,
      "healthUnknown": 0,
      "dietMismatch": 0,
      "dietUnknown": 0,
      "categoryMismatch": 0,
      "alreadyDeliveredOrDuplicate": 0
    },
    "notice": "알레르기·주의성분·필수 식단·건강 조건을 적용한 표기 데이터 기반 추천입니다. 실제 제품 포장 표시를 다시 확인해 주세요."
  }
}
```

### 응답 필드

| data 필드 | 타입 | 설명 |
|---|---|---|
| requestId | string(UUID) | 이번 응답 식별자 |
| userId / seed | integer(Long) | 대상 사용자, 랜덤 세션 seed |
| requestedLimit / returnedItemCount | integer | 요청 상한과 반환 고유 상품 수 |
| returnedBarcodes | string[] | 이번에 반환한 고유 상품 바코드 |
| requestedCategoryIds | string[] | 적용한 카테고리 제한 |
| preferenceFilterIds / hardHealthFilterIds | string[] | 필수 선택 식단(호환 필드명) / 건강 조건 |
| requiredDietFilterIds | string[] | 선택 식단과 건강 조건의 합집합 |
| policyVersion | string | 현재 unified-hard-constraints-evidence-v5.1 |
| recommendationMode | string | 아래 모드 표 참고 |
| categories | CategoryGroup[] | 결과가 있는 카테고리만 반환 |
| categories[].categoryId / categoryName | string | 분류 ID·표시 이름 |
| categories[].items | SafeItem[] | 해당 카테고리 상품 |
| nextCursor | string/null | 다음 탐색 위치. 내부 해석·편집 금지 |
| hasNext | boolean | 다음 탐색 가능 여부 |
| scannedCandidateCount | integer | 이번 탐색 수 |
| exclusions | object | 예시의 9개 정수 카운터. healthMismatch/healthUnknown은 dietMismatch/dietUnknown의 부분집합이며 합산하지 않음 |
| notice | string | 결과 안내 |

SafeItem은 product(Product), safety(SafetyDecision), healthConstraints(DietConstraintDecision), preferences(DietConstraintDecision), dietConstraints(DietConstraintDecision), preferenceRelaxed(boolean, 항상 false), categoryIds(string[])를 가진다. dietConstraints는 전체 필수 조건이고 healthConstraints/preferences는 부분집합 판정이다. 판정 객체는 R03을 참고한다.

| recommendationMode | 의미·message |
|---|---|
| PREFERENCE_MATCHED | `맞춤 안심 상품 추천 성공` |
| MIXED / PREFERENCE_RELAXED | 구버전 호환 enum. 현재 서비스에서는 생성하지 않음 |
| EMPTY | `현재 범위에서 안전성이 확인된 추천 상품을 찾지 못했습니다.` |

### 카테고리·추가 로딩 규칙

- 한 상품이 여러 카테고리에 속하면 여러 그룹에 반복 등장한다. 이는 다중 분류 표현이며 반환 고유 수량은 returnedItemCount로 판단한다. 전체 카드를 합칠 때는 barcode로 중복을 제거한다.
- categories에 한 분류만 요청해도 선택 상품이 속한 다른 카테고리 그룹이 응답에 함께 있을 수 있다. 요청 분류는 후보 포함 조건이며 출력 그룹을 자르는 조건이 아니다.
- EMPTY라도 아직 탐색하지 않은 데이터가 있으면 hasNext=true일 수 있다. hasNext=true는 다음 요청에서 상품을 반드시 찾는다는 보장이 아니다.
- 다음 요청에는 이전 nextCursor와 같은 카테고리·사용자 조건을 사용한다. seed를 같이 보낼 경우 기존 값으로 유지한다. 조건 변경·새로고침 시 cursor를 초기화한다.
- 서버가 배송/노출 세션 목록을 저장하는 방식은 아니다. excludeBarcodes에 전달한 상품과 동일 표시 그룹은 제외하지만 최대 200개 제한이 있다. 긴 탐색에서는 프론트도 이미 표시한 바코드·상품을 관리한다. 무제한 전역 중복 방지를 보장하는 API로 문서화하지 않는다.

### 오류

400 REQUEST_FAILED(limit·cursor·seed·분류·제외 수량 오류), 401 REQUEST_FAILED(토큰 없이 호출), 403 REQUEST_FAILED(타인 userId), 404 REQUEST_FAILED(사용자 없음) 및 공통 인증 필터 오류이다.

## R02. 특정 상품의 대체 상품 추천

```http
GET /api/recommendations/products/{barcode}
Authorization: Bearer {token}
```

### 요청

| 이름 | 위치·타입 | 필수·기본값 |
|---|---|---|
| barcode | Path, string | 필수 기준 상품 |
| limit | Query, integer | 기본 10, 1~20 |
| minScore | Query, number | 기본 0.2, 0~1 |
| userId | Query, Long | 선택. 본인 자동 적용 권장 |

로그인 필수, Body 없음, 성공 200이다. 이 API에는 categories·cursor·page 파라미터가 없다. 기준 상품에 사전 계산 추천 후보가 필요하다. Product 첫 화면 추천은 R01을 사용한다.

```http
GET /api/recommendations/products/8800000000001?limit=3&minScore=0.2
Authorization: Bearer {token}
```

### 응답 data 전체 필드

응답은 `{message: string, data: ProductRecommendationResponse}`이다.

| 필드 | 타입 | 설명 |
|---|---|---|
| requestId | string(UUID) | 추천 요청 식별자 |
| referenceProduct | Product | 기준 상품 |
| referenceSafety | SafetyDecision | 기준 상품 알레르기 판정 |
| userContext | object | 아래 사용자 조건 |
| policyVersion / modelVersion | string | 정책·사전 후보 데이터 버전 |
| precomputedCandidateCount | integer | 사전 저장 후보 수 |
| eligibleCandidateCount | integer | 엄격 조건 통과 후보 수 |
| requestedLimit | integer | 요청 limit |
| minSimilarityScore | number | 적용 minScore |
| items | RecommendedProduct[] | 엄격 조건을 통과한 추천 |
| excluded | object | missingProduct, lowSimilarity, danger, unknownSafety, dietMismatch, dietUnknown, dislikedIngredient: 각각 integer |
| timing | object | neighborLookupMicros, productFetchMicros, historyFetchMicros, rankingMicros, totalMicros: 각각 정수 마이크로초 |
| fallbackItems | RecommendedProduct[] | 엄격 후보가 전혀 없을 때 대안 최대 1개 |
| resultMode | string | 아래 모드 표 참고 |
| fallbackCandidateCount | integer | 해당 대안 단계의 후보 수 |
| fallbackReason | string/null | null 또는 MINIMUM_SIMILARITY_RELAXED / INSUFFICIENT_VERIFICATION_DATA / NO_RETURNABLE_CANDIDATE |
| requiredActions | string[] | 사용자에게 필요한 다음 행동 |
| notice | string | 판정 한계·안내 |

userContext 필드는 userId(Long), allergies(string[]), requiredDietFilters(string[]), dislikedIngredients(string[]), usableHistorySignals(integer), usableHistoryProducts(integer), positiveHistoryWeight(number), negativeHistoryWeight(number)이다. 식단 조건은 specialDiet와 질환 기반 조건의 합집합이다.

| RecommendedProduct 필드 | 타입 | 설명 |
|---|---|---|
| product | Product | 상품 본체 |
| originalRank | integer | 사전 후보 원 순위 |
| baseSimilarityScore | number | 기준 상품 유사도 |
| preferenceScore | number/null | 사용자 행동 기반 취향 점수. 이력 부족 시 null 가능 |
| dataQualityScore / finalScore / mmrScore | number | 자료 품질·합성·다양성 재정렬 점수 |
| safety | SafetyDecision | 알레르기 판정 |
| dietConstraints | DietConstraintDecision | 요구 식단 판정 |
| dataEvidence | object | 아래 출처·신뢰도 |
| scoreBreakdown | object | 아래 가중치·기여도 |
| reasons | string[] | 추천 근거 |
| recommendationTier | string | VERIFIED / RELAXED_SAFE / VERIFICATION_REQUIRED |
| verificationRequired | boolean | 라벨 확인 필요한 대안인지 |
| warnings / requiredActions | string[] | 경고와 다음 행동 |

dataEvidence는 allergyEvidenceLevel(string), allergyConfidence(number/null), nutritionOrigin(string), nutritionConfidence(number/null), dietaryOrigin(string), dietaryConfidence(number/null)이다. scoreBreakdown은 similarityWeight, preferenceWeight, dataQualityWeight, similarityContribution, dataQualityContribution(number) 및 preferenceContribution(number/null)이다.

### 모드별 표시

| resultMode | 반환 위치 | 표시 규칙 |
|---|---|---|
| VERIFIED | items | 엄격 안전·식단·유사도 조건 통과. message=`개인화 대체 상품 추천 성공` |
| RELAXED_SAFE | fallbackItems | 알레르기·식단 조건 유지, 유사도만 완화 |
| VERIFICATION_REQUIRED | fallbackItems | 자료 부족 대안. 안전 추천과 분리하고 warnings·requiredActions 표시 |
| ACTION_REQUIRED | 두 배열 모두 빈 배열 | 반환 가능한 상품 없음. requiredActions 표시 |

items가 1개라도 있으면 limit보다 적더라도 fallback으로 부족분을 채우지 않는다. UNKNOWN 대안은 items와 분리하고 DANGER·명시적인 식단 MISMATCH·기피 식재료 확인 상품은 대안에도 넣지 않는다. R01과 동일하게 specialDiet와 건강 조건을 필수로 적용한다. 홈은 UNKNOWN을 반환하지 않으며 대체 추천만 별도 경고 대안을 제공한다.

예시는 핵심 분기 필드만 발췌한다. 실제 응답에는 위 표의 전체 필드가 포함된다.

```json
{
  "message": "위험 상품을 대신 표시하지 않았습니다. 제품 라벨 확인 또는 다른 상품 선택이 필요합니다.",
  "data": {
    "requestId": "22222222-2222-4222-8222-222222222222",
    "items": [],
    "fallbackItems": [],
    "resultMode": "ACTION_REQUIRED",
    "fallbackCandidateCount": 0,
    "fallbackReason": "NO_RETURNABLE_CANDIDATE",
    "requiredActions": ["다른 상품을 선택하거나 제품 뒷면의 원재료와 알레르기 표시를 촬영해 주세요."]
  }
}
```

### 오류

- 400 REQUEST_FAILED: limit·minScore 범위 오류.
- 404 REQUEST_FAILED: 사용자·기준 상품 없음 또는 해당 상품의 사전 계산 후보 없음. ‘후보를 검사했지만 안전한 결과가 없음’의 200과 구분한다.
- 403 REQUEST_FAILED: 타인 userId 요청.
- 공통 인증 401 및 서버 500.

## R03. 추천 공통 판정 객체

| SafetyDecision 필드 | 타입 | 설명 |
|---|---|---|
| status | string | PASS / DANGER / UNKNOWN |
| conflictingAllergens | string[] | 충돌 알레르기 ID. 상품 검색의 conflictingAllergenIds와 키 이름이 다름 |
| evidenceSources | string[] | 판단 자료 |
| evidenceLevel | string | VERIFIED_SOURCE / DECLARED_LABEL / INGREDIENT_DERIVED / INFERRED / UNKNOWN |
| confidence | number/null | 저장된 근거 신뢰도 |
| message | string | 판단 설명 |

| DietConstraintDecision 필드 | 타입 | 설명 |
|---|---|---|
| status | string | PASS / MISMATCH / UNKNOWN |
| requiredFilters | string[] | 요구 조건 |
| satisfiedFilters | string[] | 충족 조건 |
| failedFilters | string[] | 불충족 조건 |
| uncertainFilters | string[] | 판단 불가 조건 |
| attributes | DietaryAttributeDecision[] | 요구된 개별 속성의 근거·3상태 판정 |
| evidenceOrigin | string | SOURCE / NORMALIZED / INFERRED / IMPUTED / CALCULATED / UNKNOWN |
| confidence | number/null | 근거 신뢰도 |
| message | string | 판단 설명 |

DietaryAttributeDecision은 key(string), status(MET/NOT_MET/UNKNOWN), storedValue(boolean), evidenceOrigin(string), confidence(number/null), reason(string), ingredientEvidence(string[])이다.
reason은 STORED_CLASSIFICATION / UNRELIABLE_ORIGIN / INSUFFICIENT_CONFIDENCE / MISSING_OR_INVALID_EVIDENCE / EXPLICIT_INGREDIENT_CONFLICT / AMBIGUOUS_INGREDIENT_EVIDENCE 중 하나이다.
비건 요구 시 원재료의 젓갈 등 명시적 동물성 근거를 저장 분류보다 우선한다. 충돌은 EXPLICIT_INGREDIENT_CONFLICT 및 NOT_MET, 향·식물성 대체 등의 모호한 표현은 AMBIGUOUS_INGREDIENT_EVIDENCE 및 UNKNOWN이다. ingredientEvidence는 사용한 성분 키워드이며 없으면 []이다.
명시적 충돌 없이 근거가 부족한 경우 true/false 모두 UNKNOWN으로 판정하며, 명시적 NOT_MET와 UNKNOWN이 섞여도 failedFilters와 uncertainFilters를 모두 보존한다. storedValue는 원본 Boolean이므로 true라도 NOT_MET일 수 있다. UI는 status와 reason을 사용하고 새 reason을 모르면 공통 안내로 처리한다.
종합 판정은 NOT_MET가 있으면 MISMATCH, 없고 UNKNOWN이 있으면 UNKNOWN, 나머지는 PASS이다.
현재 출처·신뢰도는 상품 단위 자료를 사용하며 속성별 독립 검수·인증을 의미하지 않는다.

PASS는 서비스의 표기 데이터 기반 결과이고, 어떤 사용자에게도 실제 섭취 안전을 보증하는 값이 아니다. 등록 조건 없음에 따른 PASS도 있으므로 message·요구 조건 배열을 함께 사용한다.

## R04. 추천 피드백 기록

```http
POST /api/recommendations/feedback
Authorization: Bearer {token}
```

로그인 필수, Query 없음, 성공 200이다.

| Body 필드 | 타입 | 필수·제한 |
|---|---|---|
| requestId | string(UUID) | 필수, 추천 응답의 ID |
| productBarcode | string | 필수, 실제 상품 |
| feedbackType | string | 필수, IMPRESSION / CLICK / ACCEPT / DISMISS |
| rankPosition | integer/null | 선택, 있으면 1~20 |

```json
{"requestId":"22222222-2222-4222-8222-222222222222","productBarcode":"8800000000001","feedbackType":"CLICK","rankPosition":1}
```

```json
{
  "message": "추천 피드백 기록 성공",
  "data": {
    "requestId": "22222222-2222-4222-8222-222222222222",
    "productBarcode": "8800000000001",
    "feedbackType": "CLICK",
    "rankPosition": 1,
    "createdAt": "2026-10-08T15:00:00"
  }
}
```

필드 타입은 요청과 같으며 createdAt은 LocalDateTime 문자열이다. 400 REQUEST_FAILED(형식·유형·순위), 404 REQUEST_FAILED(사용자·상품 없음), 409 REQUEST_FAILED(동일 추천 피드백 중복), 공통 401/500이 가능하다.

rankPosition 상한이 20이므로 최대 50개를 주는 첫 화면 추천의 21번째 이후 위치를 그대로 전송하면 400이다. 생략 또는 null은 허용한다. 이 피드백은 추천 평가 테이블에 저장되며 현재 취향 이력 학습용 `/api/histories/events`를 자동 생성하지 않는다.

현재 서버는 requestId의 UUID 형식, 사용자·상품 존재와 동일 피드백 중복을 검사한다. 실제 발급된 추천 요청인지, 본인 소유인지, 해당 상품이 그 응답에 포함됐는지는 검증하지 않는다. 프론트는 실제 응답의 ID·상품을 전송해야 하며 서버 측 소유권 검증은 별도 보완이 필요하다.

## H01. 사용자 행동·스캔 이력 조회

```http
GET /api/histories/user/{userId}
Authorization: Bearer {token}
```

로그인 본인 또는 관리자, userId 필수 Long, Body 없음, 성공 200이다. view 생략/all은 기존 전체 이력 배열을 반환한다. 2026-11-02 추가한 view=recent는 SCAN/DETAIL_VIEW의 상품별 최신 조회를 data.items/page/size/hasNext로 반환한다. 상세는 [좋아요·최근 본 상품 계약](family-favorites-recent-v1.md)을 따른다.

아래 product는 일부 필드 발췌이다. 전체 구조는 Product이다.

```json
{
  "message": "사용자 히스토리 조회 성공",
  "data": [{
    "id": 100,
    "actionType": "SCAN",
    "scannedAt": "2026-10-08T15:00:00",
    "product": {"barcode":"8800000000001","productName":"예시 과자"}
  }]
}
```

data[].id는 이력 ID(Long), actionType은 string, scannedAt은 LocalDateTime 문자열, product는 Product/null이다. 상품이 DB에서 없어졌으면 null일 수 있다. 이력이 없으면 data=[]이며 현재 서비스는 대상 사용자 존재를 별도로 검증하지 않는다. 공통 401, 403 REQUEST_FAILED(타인 이력 요청), 서버 500을 처리한다.

## H02. 사용자 행동 기록

```http
POST /api/histories/events
Authorization: Bearer {token}
```

로그인 필수, 사용자 ID는 토큰에서 자동 확인, Query 없음, 성공 200이다.

| Body 필드 | 타입 | 규칙 |
|---|---|---|
| barcode | string | 필수. trim 후 비어 있지 않고 최대 32자, DB에 존재해야 함 |
| actionType | string | 필수. 아래 6종, 대소문자 무시 입력 가능 |

| actionType | 의미 |
|---|---|
| SCAN | 스캔 |
| DETAIL_VIEW | 상세 조회 |
| SEARCH_CLICK | 검색 결과 클릭 |
| FAVORITE | 즐겨찾기 행동 |
| EAT | 섭취 행동 |
| DISLIKE | 비선호 행동 |

```json
{"barcode":"8800000000001","actionType":"FAVORITE"}
```

```json
{
  "message": "사용자 행동 기록 성공",
  "data": {
    "eventId": 101,
    "barcode": "8800000000001",
    "actionType": "FAVORITE",
    "createdAt": "2026-10-08T15:02:00"
  }
}
```

eventId는 Long, barcode/actionType은 string, createdAt은 LocalDateTime 문자열이다. OTHER는 구형 데이터 해석용이며 신규 요청에서 허용하지 않는다. 400 REQUEST_FAILED(바코드·행동 유형), 404 REQUEST_FAILED(사용자·상품 없음), 공통 401/500이 가능하다.

반복 전송은 별도 이력을 생성한다. 이 API는 행동 기록용이며 현재 좋아요 상태 API와 다르다. 2026-11-02 추가한 `/api/users/me/favorites/{productId}` PUT/DELETE가 상태와 FAVORITE/UNFAVORITE 이력을 함께 처리한다. 새 FE는 이력 POST를 중복 호출하지 않는다. 상세 GET의 자동 SCAN과 중복해서 DETAIL_VIEW/SCAN을 POST하지 않는다.
