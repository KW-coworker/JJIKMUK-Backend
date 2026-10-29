# Product 첫 화면 맞춤 안심 상품 추천 API

## 목적

특정 상품의 대체재를 찾는 `GET /api/recommendations/products/{barcode}`와 분리하여,
로그인 사용자의 프로필을 기준으로 Product 첫 화면에 노출할 상품을 카테고리별로 반환한다.

```http
GET /api/products/safe-recommendations
Authorization: Bearer <JWT>
```

## 추천 정책

적용 순서는 다음과 같다.

1. 사용자 알레르기와 충돌하는 `DANGER` 상품 제외
2. 근거가 부족한 `UNKNOWN` 상품 제외
3. 사용자의 `dislikedIngredients`가 포함된 상품 제외
4. 질병에서 파생된 저당·저염·저지방·저칼로리·글루텐프리 조건 유지
5. `specialDiet`의 비건·저당 등을 필수 조건으로 적용하여 `PASS`만 유지
6. 결과가 부족해도 식단 조건을 완화하거나 UNKNOWN으로 빈자리를 채우지 않음
7. 안전 후보를 무작위화한 뒤 카테고리별 그룹으로 반환

알레르기, 주의성분, 선택 식단, 질병 기반 조건은 결과 수가 부족해도 완화하지 않는다.
2026-10-23 정책 `unified-hard-constraints-evidence-v5`부터 대체 상품 추천과 같은 필수 조건을 사용한다.
현재 프로필에 hard/soft 구분 필드가 없으므로 `specialDiet`를 완화 가능한 취향으로 해석하지 않는다.

## Query parameter

| 이름 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `limit` | integer | `20` | 한 번에 반환할 고유 상품 수, 1~50 |
| `cursor` | string | 없음 | 이전 응답의 `nextCursor` |
| `seed` | long | 서버 생성 | 첫 요청의 랜덤 시드. 다음 요청에서는 이전 응답의 값을 그대로 전달 |
| `excludeBarcodes` | string[] | 없음 | 이미 화면에 표시한 바코드, 최대 200개 |
| `categories` | string[] | 전체 | 요청할 카테고리 ID. 쉼표/반복 파라미터 지원 |
| `userId` | long | 로그인 사용자 | 관리자 테스트 외에는 생략 권장 |

첫 요청 예시:

```http
GET /api/products/safe-recommendations?limit=20&categories=snack,beverage
```

추가 로딩 예시:

```http
GET /api/products/safe-recommendations?limit=20&cursor={nextCursor}&seed={seed}&excludeBarcodes=8800000000001,8800000000002
```

`ORDER BY RAND()`는 134만 건 테이블 전체 정렬을 유발하므로 사용하지 않는다. 서버가 랜덤한
바코드 시작점을 만들고 PK keyset 방식으로 순회한다. 커서는 같은 추천 세션에서 이미 순회한
행을 다시 읽지 않게 하며, `excludeBarcodes`는 재시작 또는 동일 표시 상품의 다른 바코드까지
제외하는 데 사용한다.

## 성공 응답

```json
{
  "message": "맞춤 안심 상품 추천 성공",
  "data": {
    "requestId": "uuid",
    "userId": 1,
    "seed": 123456,
    "requestedLimit": 20,
    "returnedItemCount": 1,
    "returnedBarcodes": ["8800000000001"],
    "requestedCategoryIds": ["snack", "beverage"],
    "preferenceFilterIds": ["vegan"],
    "hardHealthFilterIds": ["lowSugar"],
    "requiredDietFilterIds": ["lowSugar", "vegan"],
    "policyVersion": "unified-hard-constraints-evidence-v5.1",
    "recommendationMode": "PREFERENCE_MATCHED",
    "categories": [
      {
        "categoryId": "snack",
        "categoryName": "과자·스낵",
        "items": [
          {
            "product": {
              "barcode": "8800000000001",
              "productName": "예시 상품",
              "foodCategoryIds": ["snack"]
            },
            "safety": { "status": "PASS" },
            "healthConstraints": { "status": "PASS" },
            "preferences": { "status": "PASS" },
            "dietConstraints": { "status": "PASS", "requiredFilters": ["lowSugar", "vegan"] },
            "preferenceRelaxed": false,
            "categoryIds": ["snack"]
          }
        ]
      }
    ],
    "nextCursor": "opaque-cursor",
    "hasNext": true,
    "scannedCandidateCount": 500,
    "exclusions": {
      "danger": 4,
      "unknownSafety": 30,
      "dislikedIngredient": 2,
      "healthMismatch": 5,
      "healthUnknown": 3,
      "dietMismatch": 8,
      "dietUnknown": 5,
      "categoryMismatch": 100,
      "alreadyDeliveredOrDuplicate": 2
    }
  }
}
```

`limit`는 중복 제거된 고유 상품 수다. 한 상품이 여러 카테고리에 속하면 여러 카테고리 그룹에
표시될 수 있으므로 각 그룹의 `items` 개수 합은 `returnedItemCount`보다 클 수 있다.

## recommendationMode

| 값 | 의미 |
| --- | --- |
| `PREFERENCE_MATCHED` | 기존 이름 유지. 모든 반환 상품이 선택 식단 및 건강 조건까지 충족 |
| `MIXED` / `PREFERENCE_RELAXED` | 구버전 호환 enum으로만 남기며 현재 서비스에서는 반환하지 않음 |
| `EMPTY` | 현재 순회 범위에서 안전성이 확인된 상품이 없음 |

## 프론트엔드 처리

1. `categories` 배열을 그대로 카테고리 섹션 또는 탭에 표시한다.
2. `dietConstraints`로 전체 필수 식단 판정을 확인한다. `preferenceRelaxed`는 항상 false이다.
3. 다음 로딩 때 `nextCursor`, `seed`, 지금까지 받은 `returnedBarcodes`를 함께 보낸다.
4. `nextCursor=null`이면 더 불러올 상품이 없다.
5. `UNKNOWN`과 `DANGER`는 이 API 결과에 포함되지 않는다.

`preferences`와 `preferenceFilterIds`는 호환 필드명이며 현재는 **필수 선택 식단**이다.
`healthConstraints`/`hardHealthFilterIds`는 건강 조건 부분집합이고, 전체는 `dietConstraints`/`requiredDietFilterIds`이다.
`exclusions.dietMismatch`, `dietUnknown`은 전체 식단 제외 수이며 health 카운터는 그 중 건강 조건에서의 수이다.
서로 더해서 총 제외 수로 계산하지 않는다. UNKNOWN 사유와 개별 속성은
[추천 정책·평가 변경사항](recommendation-policy-v5.md)을 참고한다.

현재 Android의 `ProductRepositoryImpl`은 더미 데이터를 반환하므로, 실제 화면 연결 시 추천 응답
DTO와 `foodCategoryIds: List<String>` 모델을 추가하고 이 API 호출로 교체해야 한다.
