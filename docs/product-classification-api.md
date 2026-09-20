# 상품 분류 DB/API 계약

## 저장 컬럼

- `products.food_categories`: `|`로 구분한 비배타적 식품 분류 표시명
- `products.allergy_classification`: `|`로 구분한 알레르기 표시명 또는 `미검출`, `정보없음`

원본의 `food_type`, `allergy`, `raw_materials`, `allergy_warning`은 그대로 보존한다.
`미검출`은 26개 지원 항목이 분류 결과에 없다는 뜻일 뿐 안전(PASS)을 뜻하지 않는다.

필터 조회는 TEXT 전체 스캔 대신 다음 인덱스 매핑 테이블을 사용한다.

- `product_food_category_memberships(barcode, category_id)`
- `product_allergy_classification_memberships(barcode, allergy_id)`

두 테이블은 `Product.csv` 적재 때 스테이징으로 함께 생성되고 `products`와 한 번에 교체된다.
따라서 세 테이블을 서로 다른 데이터 버전으로 배포하면 안 된다.

상품을 반환하는 상세·검색·필터·추천 API에는 다음 필드가 함께 노출된다.

- `foodCategories`: DB 원문
- `foodCategoryIds`: 안정적인 영문 ID 배열
- `allergyClassification`: DB 원문
- `allergyClassificationIds`: 26개 알레르기 영문 ID 배열
- `allergyClassificationState`: `detected`, `not_detected`, `no_information`

## 메타데이터

```http
GET /api/products/classifications
```

식품 카테고리 14개(미분류 포함), 알레르기 26개, 알레르기 분류 상태의 ID와 표시명을 반환한다.

## 필터

```http
GET /api/products/filter?categories=beverage,dairy&categoryMatch=any&containsAllergens=milk,wheat&allergenMatch=all&page=0&size=20
```

- `filters`: 기존 식단·영양 boolean 필터
- `match`: 기존 필터 축의 `all` 또는 `any`
- `categories`: 식품 카테고리 ID 또는 표시명. 쉼표/반복 파라미터 지원
- `categoryMatch`: 카테고리 축 내부의 `all` 또는 `any`
- `containsAllergens`: 제품에 포함된 알레르기 분류 ID 또는 표시명
- `allergenMatch`: 알레르기 축 내부의 `all` 또는 `any`

서로 다른 축은 항상 AND로 결합한다. 예를 들어 카테고리 `any`와 알레르기 `any`를 함께 보내면,
선택 카테고리 중 하나 이상이면서 선택 알레르기 중 하나 이상인 상품만 반환한다.

`containsAllergens`는 포함 상품을 찾는 데이터 조회 조건이다. 사용자에게 안전한 상품을 찾는
제외 조건은 아니며, 개인 안전 판정과 추천 hard constraint는 `AllergySafetyService`를 사용한다.
