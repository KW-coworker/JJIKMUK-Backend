# 상품 카테고리·알레르기 분류 검색 API 명세

## 1. 개요

상품 카테고리와 제품에 포함된 알레르기 분류를 이용한 검색은 다음 API에서 제공한다.

```http
GET /api/products/filter
```

지원하는 검색 축은 다음 세 가지이며, 서로 다른 축은 항상 `AND`로 결합한다.

1. 식단·영양 속성: `filters`
2. 식품 카테고리: `categories`
3. 제품에 포함된 알레르기 분류: `containsAllergens`

각 축 안에서 여러 값을 결합하는 방식은 해당 `*Match` 파라미터의 `any` 또는 `all`로 정한다.

카테고리와 알레르기 필터는 `products`의 문자열을 `LIKE`로 검색하지 않는다. 다음 인덱스 매핑
테이블을 사용해 완전 일치 ID로 검색한다.

- `product_food_category_memberships(barcode, category_id)`
- `product_allergy_classification_memberships(barcode, allergy_id)`

검색 결과는 화면에 표시되는 상품명·제조사·원재료·이미지가 같은 상품을 하나의 대표 상품으로
묶어서 반환한다. 따라서 `totalElements`는 바코드 원본 행 수가 아니라 중복 제거된 상품 카드 수다.

## 2. 인증

분류 목록과 상품 필터 검색 자체는 비로그인 상태에서도 호출할 수 있다.

- `userId` 생략 + 비로그인: 공용 결과와 `UNKNOWN` 안전성 분석을 반환한다.
- `userId` 생략 + 로그인: JWT의 현재 사용자 기준으로 안전성을 분석한다.
- `userId` 지정 + 비로그인: `401 Unauthorized`
- 다른 사용자의 `userId` 지정: 관리자 이외에는 `403 Forbidden`

로그인 시 다음 헤더를 사용한다.

```http
Authorization: Bearer <JWT>
```

## 3. 분류 메타데이터 조회

프론트엔드는 ID를 하드코딩하기보다 이 API 결과로 필터 목록을 구성하는 것을 권장한다.

```http
GET /api/products/classifications
```

### 성공 응답

```json
{
  "message": "상품 분류 목록 조회 성공",
  "data": {
    "foodCategories": [
      { "id": "snack", "label": "과자·스낵" },
      { "id": "beverage", "label": "음료" }
    ],
    "allergens": [
      { "id": "egg", "label": "계란" },
      { "id": "milk", "label": "우유" }
    ],
    "allergyStates": [
      { "id": "detected", "label": "검출" },
      { "id": "not_detected", "label": "미검출" },
      { "id": "no_information", "label": "정보없음" }
    ]
  }
}
```

`allergyStates`는 상품 응답의 데이터 상태를 설명하기 위한 값이다. 현재 검색 조건은 실제로
분류된 26개 알레르기 ID만 받으며, `not_detected`와 `no_information`은
`containsAllergens`에 전달할 수 없다.

## 4. 상품 필터 검색

```http
GET /api/products/filter
```

### Query parameter

| 이름 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `filters` | `string[]` | 조건부 | 없음 | 비건·저당·글루텐프리 등 식단/영양 필터 ID |
| `match` | `string` | 아니요 | `all` | `filters` 내부 결합 방식: `all`, `any` |
| `categories` | `string[]` | 조건부 | 없음 | 식품 카테고리 ID 또는 표시 이름 |
| `categoryMatch` | `string` | 아니요 | `any` | `categories` 내부 결합 방식: `all`, `any` |
| `containsAllergens` | `string[]` | 조건부 | 없음 | 제품에 포함된 알레르기 ID 또는 표시 이름 |
| `allergenMatch` | `string` | 아니요 | `any` | `containsAllergens` 내부 결합 방식: `all`, `any` |
| `keyword` | `string` | 아니요 | 없음 | 결과 내 상품명 검색어, 2~100자 |
| `page` | `integer` | 아니요 | `0` | 0부터 시작하는 페이지 번호 |
| `size` | `integer` | 아니요 | `20` | 페이지 크기, 1~50 |
| `userId` | `long` | 아니요 | 로그인 사용자 | 개인 알레르기 안전성 분석 대상 사용자 |

`filters`, `categories`, `containsAllergens` 중 하나 이상은 반드시 있어야 한다. `keyword`만으로
호출하려면 `/api/products/search?keyword=...`를 사용한다.

배열 파라미터는 쉼표 형식과 반복 파라미터 형식을 모두 지원한다.

```http
categories=beverage,dairy
```

```http
categories=beverage&categories=dairy
```

API에는 한글 표시 이름도 전달할 수 있지만, 클라이언트 저장값과 통신 계약에는 안정적인 영문
ID 사용을 권장한다.

### 결합 규칙

다음 요청은 `음료 또는 유제품`이면서 `우유와 밀을 모두 포함`하고 `저당`인 상품을 찾는다.

```http
GET /api/products/filter?filters=lowSugar&categories=beverage,dairy&categoryMatch=any&containsAllergens=milk,wheat&allergenMatch=all&page=0&size=20
```

논리식은 다음과 같다.

```text
lowSugar
AND (beverage OR dairy)
AND (milk AND wheat)
```

### 카테고리만 검색

```http
GET /api/products/filter?categories=snack,dessert&categoryMatch=any&page=0&size=20
```

### 알레르기 분류만 검색

```http
GET /api/products/filter?containsAllergens=milk,wheat&allergenMatch=any&page=0&size=20
```

이 요청은 우유 또는 밀이 포함된 상품을 찾는다. 알레르기 제품을 제외하는 안전 검색이 아니다.

### 카테고리와 상품명 함께 검색

```http
GET /api/products/filter?categories=snack&keyword=새우깡&page=0&size=20
```

## 5. 성공 응답

### 결과가 있는 경우: `200 OK`

```json
{
  "message": "필터 검색 성공",
  "data": {
    "items": [
      {
        "product": {
          "barcode": "8800000000000",
          "productName": "예시 상품",
          "manufacturer": "예시 제조사",
          "foodCategories": "과자·스낵|디저트·빙과",
          "foodCategoryIds": ["snack", "dessert"],
          "allergyClassification": "우유|밀",
          "allergyClassificationIds": ["milk", "wheat"],
          "allergyClassificationState": "detected"
        },
        "nutrientPercents": {
          "energyPercent": 10,
          "carbsPercent": 5,
          "proteinPercent": 3,
          "fatPercent": 8,
          "sugarPercent": 4,
          "sodiumPercent": 6,
          "cholesterolPercent": 0,
          "carbsMacroPercent": 60.0,
          "proteinMacroPercent": 10.0,
          "fatMacroPercent": 30.0
        },
        "analysis": {
          "status": "UNKNOWN",
          "isDangerous": false,
          "dangerousIngredients": [],
          "conflictingAllergenIds": [],
          "evidenceSources": ["allergy_classification"],
          "evidenceLevel": "UNKNOWN",
          "verificationRequired": true,
          "message": "사용자 알레르기 정보가 없어 개인 안전성을 판정할 수 없습니다."
        }
      }
    ],
    "page": 0,
    "size": 20,
    "totalElements": 1,
    "totalPages": 1,
    "hasNext": false,
    "appliedFilters": [],
    "appliedCategories": ["snack", "dessert"],
    "containedAllergens": ["milk", "wheat"],
    "match": "all",
    "categoryMatch": "any",
    "allergenMatch": "all",
    "keyword": null
  }
}
```

실제 `product` 객체에는 원재료, 영양성분, 이미지 URL, 식단 속성 등 상품 상세 필드도 함께
포함된다.

### 결과가 없는 경우: `200 OK`

```json
{
  "message": "조건에 맞는 제품을 찾을 수 없습니다.",
  "data": {
    "items": [],
    "page": 0,
    "size": 20,
    "totalElements": 0,
    "totalPages": 0,
    "hasNext": false,
    "appliedFilters": [],
    "appliedCategories": ["snack"],
    "containedAllergens": ["milk"],
    "match": "all",
    "categoryMatch": "any",
    "allergenMatch": "any",
    "keyword": null
  }
}
```

## 6. 지원하는 카테고리 ID

| ID | 표시 이름 |
| --- | --- |
| `snack` | 과자·스낵 |
| `dessert` | 디저트·빙과 |
| `convenience` | 간편·즉석식품 |
| `beverage` | 음료 |
| `dairy` | 유제품 |
| `bakery` | 베이커리·떡 |
| `noodles` | 면류 |
| `meat` | 육류·가공육 |
| `seafood` | 수산물·해조류 |
| `plant` | 농산·곡물·두부류 |
| `sides` | 김치·절임·반찬 |
| `condiments` | 소스·조미료·식용유 |
| `special` | 특수영양·건강기능식품 |
| `unclassified` | 미분류 |

상품 하나는 여러 카테고리에 동시에 포함될 수 있다. `categoryMatch=all`은 선택한 모든
카테고리에 동시에 포함된 상품만 반환한다.

## 7. 지원하는 알레르기 ID

| ID | 표시 이름 | ID | 표시 이름 |
| --- | --- | --- | --- |
| `egg` | 계란 | `milk` | 우유 |
| `soy` | 대두 | `wheat` | 밀 |
| `pork` | 돼지고기 | `chicken` | 닭고기 |
| `shrimp` | 새우 | `crab` | 게 |
| `squid` | 오징어 | `mackerel` | 고등어 |
| `shellfish` | 조개류 | `oyster` | 굴 |
| `mussel` | 홍합 | `abalone` | 전복 |
| `peach` | 복숭아 | `tomato` | 토마토 |
| `peanut` | 땅콩 | `walnut` | 호두 |
| `buckwheat` | 메밀 | `pine_nut` | 잣 |
| `sulfites` | 아황산류 | `sesame` | 참깨 |
| `almond` | 아몬드 | `mustard` | 머스타드 |
| `celery` | 셀러리 | `beef` | 소고기 |

`밀가루`는 별도 ID가 아니며 `wheat`로 해석한다.

## 8. 오류 응답

### 검색 조건 없음: `400 Bad Request`

```json
{
  "message": "식단 필터, 식품 카테고리, 알레르기 분류 중 하나 이상 선택해주세요.",
  "supportedFilters": ["vegan", "lowSugar"],
  "supportedCategories": ["snack", "dessert"],
  "supportedAllergens": ["egg", "milk"]
}
```

### 지원하지 않는 카테고리: `400 Bad Request`

```json
{
  "message": "지원하지 않는 식품 카테고리가 있습니다: unknown",
  "supportedCategories": ["snack", "dessert", "convenience"]
}
```

### 지원하지 않는 알레르기: `400 Bad Request`

```json
{
  "message": "지원하지 않는 알레르기 분류가 있습니다: unknown",
  "supportedAllergens": ["egg", "milk", "soy"]
}
```

다음 경우에도 `400 Bad Request`를 반환한다.

- `match`, `categoryMatch`, `allergenMatch`가 `all` 또는 `any`가 아님
- `page < 0`
- `size`가 1~50 범위를 벗어남
- `keyword`가 공백 제거 후 2자 미만 또는 100자 초과

인증 관련 오류는 공통 오류 형식으로 반환한다.

```json
{
  "status": 401,
  "message": "특정 사용자의 기준으로 조회하려면 로그인이 필요합니다."
}
```

## 9. 안전성 관련 주의사항

`containsAllergens`는 해당 알레르기가 **포함된 상품을 조회**하는 조건이다. 사용자의 알레르기와
충돌하지 않는 상품을 찾기 위한 제외 조건이 아니다.

또한 `allergyClassificationState=not_detected`는 26개 분류 결과에서 성분이 검출되지 않았다는
뜻일 뿐 안전성을 확정하는 `PASS` 근거가 아니다. 사용자별 안전 판단과 추천 제외 정책은
`AllergySafetyService`의 `DANGER/PASS/UNKNOWN` 결과를 사용해야 한다.

## 10. DB 배포 전제

다음 데이터는 같은 버전으로 적재되어야 한다.

- `products`
- `product_food_category_memberships`
- `product_allergy_classification_memberships`

현재 구조에서는 `Product.csv` 적재 시 세 테이블을 스테이징에 함께 구성하고 원자적으로
교체한다. 분류 매핑 테이블 없이 API를 실행하면 분류 필터 결과가 비어 있거나 SQL 오류가
발생할 수 있다.
