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
5. `specialDiet`의 비건·저당 등 선호 조건을 만족하는 상품 우선
6. 결과가 부족한 경우에만 `specialDiet` 선호 조건 완화
7. 안전 후보를 무작위화한 뒤 카테고리별 그룹으로 반환

알레르기, 주의성분, 질병 기반 조건은 결과 수가 부족해도 완화하지 않는다.

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
  "message": "선호 조건을 우선 적용하고 일부 완화한 안심 상품 추천 성공",
  "data": {
    "requestId": "uuid",
    "userId": 1,
    "seed": 123456,
    "requestedLimit": 20,
    "returnedItemCount": 20,
    "returnedBarcodes": ["8800000000001"],
    "requestedCategoryIds": ["snack", "beverage"],
    "preferenceFilterIds": ["vegan"],
    "hardHealthFilterIds": ["lowSugar"],
    "recommendationMode": "MIXED",
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
| `PREFERENCE_MATCHED` | 모든 반환 상품이 선호 조건까지 충족 |
| `MIXED` | 선호 조건 충족 상품을 우선하고 부족분만 완화 |
| `PREFERENCE_RELAXED` | 안전 조건은 충족했지만 선호 조건을 완화한 상품만 반환 |
| `EMPTY` | 현재 순회 범위에서 안전성이 확인된 상품이 없음 |

## 프론트엔드 처리

1. `categories` 배열을 그대로 카테고리 섹션 또는 탭에 표시한다.
2. `PREFERENCE_RELAXED` 상품은 필요하면 "선호 조건 일부 완화" 표시를 붙인다.
3. 다음 로딩 때 `nextCursor`, `seed`, 지금까지 받은 `returnedBarcodes`를 함께 보낸다.
4. `nextCursor=null`이면 더 불러올 상품이 없다.
5. `UNKNOWN`과 `DANGER`는 이 API 결과에 포함되지 않는다.

현재 Android의 `ProductRepositoryImpl`은 더미 데이터를 반환하므로, 실제 화면 연결 시 추천 응답
DTO와 `foodCategoryIds: List<String>` 모델을 추가하고 이 API 호출로 교체해야 한다.
