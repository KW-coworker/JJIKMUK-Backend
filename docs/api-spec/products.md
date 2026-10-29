# 상품·필터·분류 API 명세

[공통 규칙과 전체 목록](README.md). 아래 응답 예시는 정적 목록을 제외하면 설명용 데이터이다.

2026-10-28 추가: [내부 ID 조회·용량 조회, 관측 이력, categoryAssessment 계약](../catalog-evolution-stage1-3.md#5-추가확장-api).
기존 바코드 API는 유지하며 이 추가 계약이 신규 필드와 경로에 우선한다. 실제 DB 적용은 별도 절차다.

## P01. 식단·영양 필터 종류 조회

```http
GET /api/products/filters
```

### 기본 정보

| 항목 | 내용 |
|---|---|
| 기능 | 통합 조건 검색과 사용자 식이조건 입력에 사용할 필터 메타데이터 조회 |
| Method | GET |
| URL | `/api/products/filters` |
| 인증 | 불필요 |
| Query Parameter | 없음 |
| Request Body | 없음 |
| 성공 | 200 OK |

### 기능 설명

상품을 반환하지 않고 12개 식단·영양 필터의 ID, 표시 이름, 설명을 반환한다. 응답의 `key`를 상품 검색의 `filters`에 사용한다. 카테고리·알레르기는 `/api/products/classifications`에서 조회한다.

### 요청 예시

```http
GET http://localhost:8080/api/products/filters
```

### 성공 응답

```json
{
  "message": "필터 목록 조회 성공",
  "data": [
    {"key":"vegan","label":"비건","description":"오직 식물성 음식만 섭취해요"},
    {"key":"lactoVegetarian","label":"락토","description":"식물성 음식과 유제품을 섭취해요"},
    {"key":"ovoVegetarian","label":"오보","description":"식물성 음식과 계란을 섭취해요"},
    {"key":"lactoOvoVegetarian","label":"락토 오보","description":"식물성 음식, 유제품, 계란을 섭취해요"},
    {"key":"pescatarian","label":"페스코","description":"채식에 해산물까지 섭취해요"},
    {"key":"pollotarian","label":"폴로","description":"채식, 해산물, 가금류까지 섭취해요"},
    {"key":"lowSugar","label":"저당","description":"당류 섭취 제한"},
    {"key":"lowSodium","label":"저염","description":"나트륨 섭취 제한"},
    {"key":"glutenFree","label":"글루텐프리","description":"밀단백질 제외"},
    {"key":"lowCalorie","label":"저칼로리","description":"다이어트 체중조절"},
    {"key":"lowFat","label":"저지방","description":"지방 섭취 제한"},
    {"key":"highProtein","label":"고단백","description":"단백질 위주 식단"}
  ]
}
```

### 응답 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| message | string | 처리 결과 메시지 |
| data | array | 필터 목록 |
| data[].key | string | 요청에 사용하는 필터 ID |
| data[].label | string | 화면 표시 이름 |
| data[].description | string | 사용자용 설명 |

### 사용 예시·오류·참고

```http
GET /api/products/filter?filters=vegan,lowSugar&match=all&page=0&size=20
```

- 경로 끝 `filters`(복수)는 목록, `filter`(단수)는 상품 검색이다.
- 가입·프로필의 `specialDiet`에는 같은 ID를 쉼표 연결 문자열로 사용한다. 단, 사용자 프로필에서는 채식 6종 중 최대 1종만 저장할 수 있다. 이 제한을 상품 검색 API의 조합 규칙과 혼동하지 않는다.
- 목록 자체의 전용 업무 오류는 없다. 잘못된 Bearer 토큰을 보내면 공통 401, 서버 장애 시 공통 오류가 발생할 수 있다.
- 이 목록은 저장된 분류 값의 선택지를 설명한다. 해당 상품이 특정 사용자에게 안전함을 보증하지 않는다.

## P02. 카테고리·알레르기 분류 조회

```http
GET /api/products/classifications
```

### 기본 정보

| 항목 | 내용 |
|---|---|
| 기능 | 검색 UI용 식품 카테고리·알레르기·알레르기 분류 상태 목록 |
| 인증 | 불필요 |
| Query / Body | 없음 |
| 성공 | 200 OK |

### 성공 응답

```json
{
  "message": "상품 분류 목록 조회 성공",
  "data": {
    "foodCategories": [
      {"id":"snack","label":"과자·스낵"},
      {"id":"dessert","label":"디저트·빙과"},
      {"id":"convenience","label":"간편·즉석식품"},
      {"id":"beverage","label":"음료"},
      {"id":"dairy","label":"유제품"},
      {"id":"bakery","label":"베이커리·떡"},
      {"id":"noodles","label":"면류"},
      {"id":"meat","label":"육류·가공육"},
      {"id":"seafood","label":"수산물·해조류"},
      {"id":"plant","label":"농산·곡물·두부류"},
      {"id":"sides","label":"김치·절임·반찬"},
      {"id":"condiments","label":"소스·조미료·식용유"},
      {"id":"special","label":"특수영양·건강기능식품"},
      {"id":"unclassified","label":"미분류"}
    ],
    "allergens": [
      {"id":"egg","label":"계란"},
      {"id":"milk","label":"우유"},
      {"id":"soy","label":"대두"},
      {"id":"wheat","label":"밀"},
      {"id":"pork","label":"돼지고기"},
      {"id":"chicken","label":"닭고기"},
      {"id":"shrimp","label":"새우"},
      {"id":"crab","label":"게"},
      {"id":"squid","label":"오징어"},
      {"id":"mackerel","label":"고등어"},
      {"id":"shellfish","label":"조개류"},
      {"id":"oyster","label":"굴"},
      {"id":"mussel","label":"홍합"},
      {"id":"abalone","label":"전복"},
      {"id":"peach","label":"복숭아"},
      {"id":"tomato","label":"토마토"},
      {"id":"peanut","label":"땅콩"},
      {"id":"walnut","label":"호두"},
      {"id":"buckwheat","label":"메밀"},
      {"id":"pine_nut","label":"잣"},
      {"id":"sulfites","label":"아황산류"},
      {"id":"sesame","label":"참깨"},
      {"id":"almond","label":"아몬드"},
      {"id":"mustard","label":"머스타드"},
      {"id":"celery","label":"셀러리"},
      {"id":"beef","label":"소고기"}
    ],
    "allergyStates": [
      {"id":"detected","label":"검출"},
      {"id":"not_detected","label":"미검출"},
      {"id":"no_information","label":"정보없음"}
    ]
  }
}
```

### 응답·사용 규칙

세 목록은 모두 `{id: string, label: string}[]`이다. `foodCategories[].id`는 검색의 `categories`, `allergens[].id`는 검색의 `containsAllergens` 또는 프로필의 `allergies`에 사용한다. 한 상품은 여러 카테고리에 속할 수 있다.

`allergyStates`는 상품 분류 상태를 설명하기 위한 메타데이터이다. 현재 검색 API에 이를 직접 받는 상태 검색 파라미터는 없다. `not_detected`는 분류상 미검출이며 개인 안전성 `PASS`와 다르다. 밀가루 별도 ID는 없고 `wheat`를 사용한다.

전용 업무 오류는 없고 공통 인증 필터·서버 오류가 적용된다.

## P03. 통합 조건 검색

```http
GET /api/products/filter
```

### 기본 정보

| 항목 | 내용 |
|---|---|
| 기능 | 식단·영양, 카테고리, 포함 알레르기 분류, 키워드 복합 상품 검색 |
| 인증 | 선택. 토큰 전달 시 본인 알레르기 분석 포함 |
| Request Body | 없음 |
| 성공 | 200 OK. 결과가 없어도 200 |

### Query Parameter

| 이름 | 타입 | 필수·기본값 | 규칙 |
|---|---|---|---|
| filters | string 목록 | 선택 | P01의 key, 쉼표 또는 같은 파라미터 반복 |
| match | string | `all` | filters 내부 `all`=모두, `any`=하나 이상 |
| categories | string 목록 | 선택 | P02 카테고리 id |
| categoryMatch | string | `any` | categories 내부 all/any |
| containsAllergens | string 목록 | 선택 | P02 알레르기 id. **포함된 상품 검색** |
| allergenMatch | string | `any` | containsAllergens 내부 all/any |
| keyword | string | 선택 | trim 후 2~100자. 공백만 있으면 조건 없음 |
| page | integer | `0` | 0부터 시작, 0 이상 |
| size | integer | `20` | 1~50 |
| userId | integer(Long) | 선택 | 토큰이 있으면 생략 권장. 본인 또는 관리자 권한 |

`filters`, `categories`, `containsAllergens` 중 하나 이상은 있어야 한다. 키워드만으로 검색하려면 `/api/products/search`를 사용한다. 서버는 호환용 한글명·일부 별칭도 받지만 프론트는 위 공식 영문 ID를 사용한다.

### 조건 결합

조건 묶음 사이에는 AND가 적용된다.

```text
(filters의 all/any 결과)
AND (categories의 all/any 결과)
AND (containsAllergens의 all/any 결과)
AND (keyword 결과)
```

예를 들어 `filters=lowSugar,highProtein&match=any&keyword=두유`는 ‘저당 또는 고단백’인 상품 중 키워드가 두유에 해당하는 상품이다. ‘두유 또는 저당 또는 고단백’이 아니다.

`containsAllergens=milk`는 우유 분류를 **포함**하는 상품을 찾는다. 우유를 제외하는 기능이나 사용자 알레르기 자동 제외 기능이 아니다. 일반 검색은 DANGER·UNKNOWN 상품도 결과에 포함한다. 안전성 필터링 추천은 `/api/products/safe-recommendations`를 사용한다.

### 요청 예시

```http
GET /api/products/filter?filters=vegan,glutenFree&match=all&page=0&size=20
GET /api/products/filter?filters=lowSugar,highProtein&match=any&keyword=두유&page=0&size=20
GET /api/products/filter?categories=snack,dessert&categoryMatch=any&page=0&size=20
GET /api/products/filter?containsAllergens=milk,wheat&allergenMatch=all&page=0&size=20
GET /api/products/filter?categories=snack&filters=lowSugar&match=all&keyword=단백질칩&page=0&size=20
```

한 글자 검색어 `keyword=칩`은 400이다. `keyword=단백질칩` 등 2자 이상을 사용한다. 개인 알레르기 분석을 함께 받으려면 다음과 같이 로그인 토큰을 전달한다.

```http
GET /api/products/filter?categories=snack&filters=lowSugar&match=all&keyword=단백질칩&page=0&size=20
Authorization: Bearer {token}
```

### 성공 응답

결과 없음 예시이다. 결과가 있으면 message는 `필터 검색 성공`이고 items의 원소는 P06의 `ProductAnalysis` 구조이다.

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
    "appliedFilters": ["vegan", "glutenFree"],
    "appliedCategories": [],
    "containedAllergens": [],
    "match": "all",
    "categoryMatch": "any",
    "allergenMatch": "any",
    "keyword": null
  }
}
```

| data 필드 | 타입 | 설명 |
|---|---|---|
| items | ProductAnalysis[] | 상품·영양 비율·개인 알레르기 분석 |
| page / size | integer | 요청 페이지와 페이지 크기 |
| totalElements | integer(Long) | 표시 중복 제거 후 전체 결과 수 |
| totalPages | integer | 전체 페이지 수 |
| hasNext | boolean | 다음 페이지 존재 여부 |
| appliedFilters / appliedCategories / containedAllergens | string[] | 실제 적용한 정규 ID |
| match / categoryMatch / allergenMatch | string | 실제 적용한 all/any |
| keyword | string 또는 null | trim한 키워드, 없으면 null |

검색 전에 조건을 적용하고 같은 표시 그룹에서 대표 상품을 고른다. 따라서 데이터 전체가 아닌 현재 조건에 맞는 결과 집합에서 중복을 제거한다. 표시 그룹은 상품명·제조사·원재료·이미지 기준이다. 설정 `product.grouping.mode=key`에서는 적재된 product_group_key를 사용한다. 키워드가 있으면 검색 점수를 우선 사용하고, 없으면 표시 정보 및 바코드로 안정 정렬한다. 요청 `sort` 파라미터는 지원하지 않는다.

### 오류

| HTTP | 발생 조건 | 응답 특징 |
|---|---|---|
| 400 | 세 종류 조건 모두 없음 | message, supportedFilters, supportedCategories, supportedAllergens |
| 400 | 지원하지 않는 필터/카테고리/알레르기 | message와 해당 supported 목록 |
| 400 | all/any 모드 오류, page/size 범위 오류, keyword 길이 오류 | message만 포함 |
| 401 | 비로그인 상태에서 userId 지정 | 공통 형식, code=`REQUEST_FAILED` |
| 403 | 일반 사용자가 다른 userId 지정 | 공통 형식, code=`REQUEST_FAILED` |
| 401 | 전달한 로그인 토큰 만료·무효 | 공통 인증 코드 |

```json
{"message":"page는 0 이상, size는 1~50 범위여야 합니다."}
```

미정의 값에 대한 message 문자열을 새로운 고정 오류 code가 있는 것으로 해석하지 않는다.

## P04. 키워드 상품 검색

```http
GET /api/products/search?keyword=매운새우깡
```

| 항목 | 내용 |
|---|---|
| 인증 | 선택 |
| Body | 없음 |
| keyword | 필수 string, trim 후 2~100자 |
| userId | 선택 Long, 본인 ID 자동 적용 권장 |
| 성공 | 200 OK |
| 결과 상한 | 중복 제거 후 최대 50개 |
| 페이지네이션 | 현재 page/size/cursor 없음 |

상품명·정제 상품명·제조사 검색을 수행한다. 기본 설정은 공백·일부 특수문자를 정규화한 LOCATE 검색이고, 서버 설정에 따라 ngram FULLTEXT를 사용할 수 있다. RapidFuzz 유사도 임계값을 사용하는 API가 아니다.

결과 있음: `{message: "검색 성공", data: ProductAnalysis[]}`이다. 결과 없음은 다음과 같다.

```json
{"message":"'매운새우깡'에 해당하는 제품을 찾을 수 없습니다.","data":[]}
```

키워드 길이 오류는 400과 message만 반환한다. 로그인/userId 관련 오류는 P03과 같다. 필수 keyword 자체 누락 시 동작은 공통 문서의 파라미터 바인딩 제한사항을 참고한다.

## P05. 바코드 상품 조회

```http
GET /api/products/{barcode}
```

| 항목 | 내용 |
|---|---|
| Path | barcode: string, 상품 식별자 |
| Query | userId: 선택 Long |
| 인증 | 선택 |
| Body | 없음 |
| 성공 | 200 OK, `{message: "조회 성공", data: ProductAnalysis}` |
| 상품 없음 | 404, code=`REQUEST_FAILED` |

로그인 사용자로 단건 조회하면 SCAN 이력이 자동 저장된다. 같은 화면을 새로고침하거나 다시 조회하면 이력이 추가될 수 있으므로 단순 재시도·중복 호출을 주의한다. 같은 동작을 `/api/histories/events`의 SCAN으로도 전송하면 별도 이력이 하나 더 생긴다.

```json
{
  "status": 404,
  "code": "REQUEST_FAILED",
  "message": "해당 바코드(0000000000000)의 제품을 찾을 수 없습니다."
}
```

## P06. 공통 상품 분석 응답 구조

바코드 조회의 data, 키워드 검색의 data[], 통합 검색의 data.items[]는 아래 구조이다. 추천 API는 다른 포장 구조를 사용하며 Product 본체만 공유한다.

### ProductAnalysis 전체 예시

아래는 로그인하지 않고 설명용 상품을 조회한 예시이다.

```json
{
  "product": {
    "barcode": "8800000000001",
    "productName": "예시 우유과자",
    "manufacturer": "예시식품",
    "reportNo": null,
    "allergy": "우유, 밀",
    "nutrientText": null,
    "imageUrl": null,
    "source": "예시 출처",
    "rawMaterials": "밀가루, 설탕, 탈지분유",
    "energyKcal": 100.0,
    "carbsG": 15.0,
    "proteinG": 2.0,
    "fatG": 4.0,
    "sugarG": 5.0,
    "sodiumMg": 100.0,
    "cholesterolMg": null,
    "allergyWarning": "우유, 밀 함유",
    "cleanProductName": "예시 우유과자",
    "totalWeight": "30g",
    "foodType": "과자",
    "foodCategories": "과자·스낵",
    "allergyClassification": "우유|밀",
    "carbsPercent": null,
    "proteinPercent": null,
    "fatPercent": null,
    "sodiumG": 0.1,
    "cholesterolG": null,
    "vegan": false,
    "lactoVegetarian": true,
    "ovoVegetarian": false,
    "lactoOvoVegetarian": true,
    "pescatarian": true,
    "pollotarian": true,
    "lowSugar": false,
    "lowSodium": false,
    "glutenFree": false,
    "lowCalorie": false,
    "lowFat": false,
    "highProtein": false,
    "foodCategoryIds": ["snack"],
    "allergyClassificationIds": ["milk", "wheat"],
    "allergyClassificationState": "detected"
  },
  "nutrientPercents": {
    "energyPercent": 5,
    "carbsPercent": 5,
    "proteinPercent": 4,
    "fatPercent": 7,
    "sugarPercent": 5,
    "sodiumPercent": 5,
    "cholesterolPercent": 0,
    "carbsMacroPercent": 0.0,
    "proteinMacroPercent": 0.0,
    "fatMacroPercent": 0.0
  },
  "analysis": {
    "status": "UNKNOWN",
    "isDangerous": false,
    "dangerousIngredients": [],
    "conflictingAllergenIds": [],
    "evidenceSources": ["allergy_warning", "raw_materials", "allergy", "allergy_classification"],
    "evidenceLevel": "DECLARED_LABEL",
    "verificationRequired": true,
    "message": "사용자 알레르기 정보가 없어 개인 안전성을 판정할 수 없습니다."
  }
}
```

### Product 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| barcode | string | 상품 식별자 |
| productName, manufacturer, reportNo | string/null | 상품명, 제조사, 품목제조보고번호 |
| allergy, rawMaterials, allergyWarning | string/null | 알레르기 문자열, 원재료, 경고 표기 |
| nutrientText, source, imageUrl | string/null | 원 영양표기, 데이터 출처, 이미지 URL |
| cleanProductName, totalWeight, foodType | string/null | 정제 이름, 중량 문자열, 원 식품유형 |
| foodCategories, allergyClassification | string/null | DB 원 분류 문자열. 복수 값은 `|`로 구분될 수 있음 |
| foodCategoryIds, allergyClassificationIds | string[] | 화면에서 사용할 정규 ID 배열 |
| allergyClassificationState | string | detected / not_detected / no_information |
| energyKcal | number/null | 저장된 에너지(kcal) |
| carbsG, proteinG, fatG, sugarG | number/null | 저장된 탄수화물·단백질·지방·당류(g) |
| sodiumMg, cholesterolMg | number/null | 저장된 나트륨·콜레스테롤(mg) |
| sodiumG, cholesterolG | number/null | g 단위 값 |
| carbsPercent, proteinPercent, fatPercent | number/null | 저장된 탄단지 비율 |
| vegan, lactoVegetarian, ovoVegetarian, lactoOvoVegetarian, pescatarian, pollotarian | boolean | 저장된 채식 분류 값 |
| lowSugar, lowSodium, glutenFree, lowCalorie, lowFat, highProtein | boolean | 저장된 식단·영양 분류 값 |

`searchKeywords`, `productGroupKey`, 내부 출처 신뢰도 필드는 Product JSON에 노출하지 않는다. API에는 영양 수치의 100g/1회/총내용량 기준을 명시하는 공통 필드가 없어 `totalWeight`만으로 환산 기준을 단정하지 않는다.

이 버전에는 `imageUrl`만 있으며 상품 대표 사진과 카테고리 참고 사진을 구분하는 `imageRole`·`imageDisplayNotice` 등의 필드는 없다. Firebase 업로드와 운영 DB 반영은 별도 작업이다.

### nutrientPercents

현재 코드에서 energy는 2000, carbs는 324g, protein은 55g, fat은 54g, sugar는 100g, sodium은 2000mg, cholesterol은 300mg을 분모로 저장값의 비율을 반올림한다. 이는 현 구현 계산 설명이며 개인별 섭취 권장량 판정이 아니다. Macro 3종은 Product의 저장 비율을 사용한다.

현재 결측 영양값의 퍼센트도 0으로 반환된다. UI는 원래 `product` 영양값이 null인지 확인해 ‘정보 없음’과 실제 0을 구분한다.

### analysis와 화면 표시

| 필드 | 타입 | 설명 |
|---|---|---|
| status | string | PASS / DANGER / UNKNOWN. SAFE는 사용하지 않음 |
| isDangerous | boolean | DANGER일 때만 true |
| dangerousIngredients | string[] | 충돌 알레르기의 한글 표시 이름 |
| conflictingAllergenIds | string[] | 충돌 알레르기 ID |
| evidenceSources | string[] | allergy_warning, raw_materials, allergy, allergy_classification 등 |
| evidenceLevel | string | VERIFIED_SOURCE / DECLARED_LABEL / INGREDIENT_DERIVED / INFERRED / UNKNOWN |
| verificationRequired | boolean | UNKNOWN일 때 true |
| message | string | 판정 사유 |

- PASS: 등록된 알레르기에 대해 현재 자료에서 충돌이 확인되지 않음. ‘먹어도 안전함’으로 단정하지 않는다.
- DANGER: 등록된 알레르기와 충돌하는 근거가 있음.
- UNKNOWN: 비로그인·자료 부족·출처 부족·포괄적 원재료 표기 등의 이유로 판정할 수 없음.
- 로그인한 사용자가 알레르기를 등록하지 않았다면 현재 구현은 PASS와 `등록된 알레르기 조건이 없습니다.`를 반환한다. 자료가 충분하다는 의미는 아니다.
- UNKNOWN도 isDangerous=false이므로 이 boolean만으로 안심 표시를 하지 않는다.
- 일반 검색 analysis는 개인 알레르기 판정이다. 사용자의 모든 식단·질환 조건을 통합 판정한 결과가 아니다. 추천의 diet/health 판단과 구분한다.

## P07. 상품 전체 용량 옵션 조회

```http
GET /api/products/{barcode}/variants
```

### 기본 정보

| 항목 | 내용 |
|---|---|
| 기능 | 검색에서 하나로 묶인 상품의 전체 용량별 선택지와 상세 분석 반환 |
| 인증 | 선택. Bearer 토큰이 있으면 해당 사용자 기준으로 알레르기 분석 |
| Path Parameter | barcode: string. 검색 결과의 `product.barcode` |
| Query Parameter | userId: Long, 선택. 일반 앱은 생략하고 Bearer 토큰만 전송 |
| Request Body | 없음 |
| 성공 | 200 OK |
| 이력 | 읽기 전용. 조회 및 옵션 전환 자체는 SCAN/DETAIL_VIEW를 자동 기록하지 않음 |

### 그룹과 용량 규칙

1. 기존 검색의 상품 그룹을 그대로 사용한다. 상품명·제조사·원재료·이미지가 같은 그룹 안에서만 비교한다. 이름이나 제조사가 다르거나 원재료·이미지로 다른 그룹에 속하는 상품을 새로 합치지는 않는다.
2. 그룹 내에서는 `totalWeight`만 옵션 키로 사용한다. 영양성분·출처·품목보고번호·바코드 등의 차이로 옵션을 늘리지 않는다.
3. `1kg`, `1000g`, `1000.0 g`는 `g:1000` 하나로 합친다. `1L`과 `1000ml`도 같다. `50g×2개`처럼 명시된 묶음은 총 100g으로 합친다. 총량이 같으면 포장 개수 차이도 별도 옵션이 아니다.
4. 질량(g)과 부피(ml)는 서로 환산하지 않는다. `100g`과 `100ml`는 별개이다. g 오름차순, ml 오름차순, 용량 정보 없음 순으로 반환한다.
5. 빈 값·단위 없는 값·0 이하·범위·해석 불가능한 값은 모두 `unknown`/`용량 정보 없음` 옵션 하나로 합친다. 이름·영양성분을 이용해 부족한 용량을 추측하지 않는다. `100g(50gx2)`와 같은 복합 설명도 현재는 불명으로 처리한다.
6. 용량 옵션이 하나면 `hasSelectableOptions=false`이며 옵션 선택 UI를 숨기고 그 항목의 상세 정보를 표시한다. 알려진 용량과 용량 불명 자료가 함께 있으면 불명 옵션도 하나 포함한다.
7. `selectedOptionKey`는 요청한 바코드의 용량이다. 배열 첫 항목을 무조건 선택하지 않는다.

기본 key 모드는 기존 `product_group_key`를 조회한다. 미백필(null key) 상품과 상품명이 없는 상품은 관련 없는 행을 묶지 않도록 자기 자신만 반환한다. legacy 모드도 지원하며 현재 검색과 같은 정규화 조건을 사용한다.

### 요청 예시

```http
GET http://localhost:8080/api/products/8800000000001/variants
Authorization: Bearer {token}
```

### 성공 응답 예시

설명용 축약 예시이다. `options[].data.product`와 `nutrientPercents`, `analysis`의 전체 필드는 P06과 동일하다. 용량별로 서로 다른 원본 행의 영양값을 혼합하거나 총중량 비율로 재계산하지 않는다.

```json
{
  "message": "상품 용량 옵션 조회 성공",
  "data": {
    "referenceBarcode": "8800000000001",
    "selectedOptionKey": "g:50",
    "optionCount": 2,
    "hasSelectableOptions": true,
    "options": [
      {
        "key": "g:50",
        "label": "50g",
        "amount": 50,
        "unit": "g",
        "barcode": "8800000000001",
        "sourceRowCount": 3,
        "hasSafetyDifferences": false,
        "analysisScope": "CAPACITY_GROUP",
        "data": {
          "product": {"barcode": "8800000000001", "productName": "예시 과자", "manufacturer": "예시 제조사", "totalWeight": "50g", "energyKcal": 200},
          "nutrientPercents": {"energyPercent": 10},
          "analysis": {"status": "UNKNOWN", "isDangerous": false, "verificationRequired": true, "message": "같은 용량의 자료 중 개인 알레르기 판정이 불가능한 자료가 있습니다. 실제 포장 라벨을 확인해 주세요."}
        }
      },
      {
        "key": "g:100",
        "label": "100g",
        "amount": 100,
        "unit": "g",
        "barcode": "8800000000004",
        "sourceRowCount": 1,
        "hasSafetyDifferences": false,
        "analysisScope": "CAPACITY_GROUP",
        "data": {
          "product": {"barcode": "8800000000004", "productName": "예시 과자", "manufacturer": "예시 제조사", "totalWeight": "0.1kg", "energyKcal": 390},
          "nutrientPercents": {"energyPercent": 20},
          "analysis": {"status": "UNKNOWN", "isDangerous": false, "verificationRequired": true, "message": "사용자 알레르기 정보가 없어 개인 안전성을 판정할 수 없습니다."}
        }
      }
    ]
  }
}
```

### 응답 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| data.referenceBarcode | string | 검색에서 선택한 요청 바코드 |
| data.selectedOptionKey | string | 최초 표시할 옵션 key |
| data.optionCount | integer | 중복 용량을 합친 실제 옵션 수 |
| data.hasSelectableOptions | boolean | optionCount > 1 |
| data.options | array | 정렬된 용량별 옵션 |
| options[].key | string | `g:50`, `ml:200`, `unknown` 등. 현재 상품 그룹 안에서 선택에 사용 |
| options[].label | string | 선택 버튼 문구. `50g`, `200ml`, `용량 정보 없음` |
| options[].amount | number/null | g 또는 ml로 정규화한 총량. 불명이면 null |
| options[].unit | string/null | g / ml / null |
| options[].barcode | string | 해당 용량의 대표 행 바코드. 요청 바코드와 다를 수 있음 |
| options[].sourceRowCount | integer | 같은 용량으로 합친 DB 행 수. 상품 개수·포장 개수가 아님 |
| options[].hasSafetyDifferences | boolean | 같은 용량 안에서 개인 알레르기 판정 또는 충돌 알레르기 집합이 서로 다름 |
| options[].analysisScope | string | `CAPACITY_GROUP`. 분석은 대표 행만이 아니라 해당 용량의 모든 행 기준 |
| options[].data | ProductAnalysis | P06과 같은 구조. product/영양값은 대표 한 행, analysis는 용량별 합산 판정 |

대표 행은 보유 영양 필드 및 원재료·경고·이미지·보고번호 필드 수가 많은 행을 우선하고 동률이면 바코드 오름차순으로 선택한다. 정보량은 정확성이나 안전성의 보증이 아니다. `totalWeight` 원문은 보존하므로 버튼에는 `product.totalWeight`가 아니라 `label`을 사용한다.

### 알레르기 분석과 프론트 연결

- 같은 용량의 행 중 하나라도 DANGER이면 해당 용량은 DANGER이다.
- DANGER는 없지만 UNKNOWN이 하나라도 있으면 UNKNOWN이다. 모두 PASS인 경우에만 PASS이다.
- 서로 다른 용량끼리는 판정을 합치지 않는다. 예를 들어 50g의 DANGER가 100g까지 전파되지 않는다.
- `hasSafetyDifferences=true`일 때 ‘동일 용량 자료 간 표기가 다릅니다. 실제 라벨을 확인해주세요’ 안내를 함께 표시한다. 숨겨진 원본의 경고 때문에 대표 product의 표기만으로 설명되지 않는 DANGER가 발생할 수 있다.
- 옵션 클릭 시 해당 `options[].data`의 상품·영양·analysis를 함께 교체한다. 대표 상품의 판정만 재조회해서 용량 그룹의 보수적 판정을 덮어쓰면 안 된다.
- 기존 `GET /api/products/{barcode}`는 특정 바코드 한 행 조회이며 로그인 시 SCAN 기록을 남기는 기존 동작을 유지한다. 옵션 전환에는 이 API를 반복 호출하지 않는다.
- 사용자 행동 기록이 필요하면 최종 선택된 `options[].barcode`로 `POST /api/histories/events`의 `SEARCH_CLICK` 또는 `DETAIL_VIEW`를 의도한 시점에 호출한다.
- 로그인·사용자 프로필이 바뀌면 옵션 응답도 다시 조회한다. 개인 분석 응답을 다른 계정에 재사용하지 않는다.
- 기존 검색 응답과 중복 제거 방식은 변경하지 않았다. 검색 결과를 누를 때 이 API를 호출하면 되며, 검색 결과에 별도 variantCount 필드는 아직 추가하지 않았다.

### 오류·운영 주의

| HTTP | code | 의미 |
|---|---|---|
| 401 | REQUEST_FAILED 또는 공통 인증 코드 | 비로그인 상태에서 userId 지정 또는 유효하지 않은 토큰 |
| 403 | REQUEST_FAILED | 일반 사용자가 타인의 userId 지정 |
| 404 | REQUEST_FAILED | 바코드에 해당하는 상품 또는 지정 사용자가 없음 |
| 422 | PRODUCT_VARIANT_GROUP_TOO_LARGE | 같은 상품 그룹이 1,000행 초과. 경고가 있는 행을 조용히 누락하지 않고 명시적으로 실패 |

DB/CSV의 행 삭제·병합·수정은 수행하지 않는다. 새 DB 컬럼이나 마이그레이션은 필요하지 않다. key 모드에서는 `product_group_key = ?` 동등 비교를 사용한다. 운영에는 기존 `idx_products_product_group_key` 인덱스와 그룹 키 백필 상태를 확인한다. 인덱스가 없으면 기존 운영 스크립트 `src/main/resources/db/operations/create_product_group_index.sql`에 따라 별도 점검 시간에 구성한다. 이번 기능 구현에서 운영 DB에 인덱스를 자동 생성하지 않았다.
