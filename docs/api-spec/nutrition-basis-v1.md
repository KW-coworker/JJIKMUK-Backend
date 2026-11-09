# 영양성분 기준량 계약 (nutrition-v1)

작성일: 2026-11-09. 기존 API 주소·상품 식별자·알레르기 판정 계약은 유지한다.

## 변경 이유

포키 녹차의 원본 CSV에는 `영양성분함량기준량=100g`, `energy_kcal=500`,
`total_weight=44g`가 함께 있다. 기존 적재기는 기준량을 저장하지 않아 앱이
100g의 열량을 한 상자 열량으로 표시할 수 있었다. 44g 전체의 환산 열량은 220kcal이다.

V17은 `products.nutrition_basis_raw VARCHAR(255) NULL`을 추가한다.
기존 staging/rollback 테이블이 있으면 같은 컬럼을 추가한다. 기본값 100g이나 대량 UPDATE는 없다.
새 CSV 적재는 원본 기준량을 보존한다. 기존 행은 별도 대조·백필이 필요하다.
속성 이력 수집 대상에도 `nutrition_basis_raw`가 추가되며, 과거 스냅샷은 소급 수정하지 않는다.

## 응답

상품 객체에 `nutritionBasisRaw`와 `nutrition`을 추가한다. 다음은 필드 일부를 발췌한 예시이다.

```json
{
  "barcode": "8801019311673",
  "totalWeight": "44g",
  "energyKcal": 500.0,
  "nutritionBasisRaw": "100g",
  "nutrition": {
    "contractVersion": "nutrition-v1",
    "sourceBasis": {
      "raw": "100g",
      "status": "KNOWN",
      "amount": 100,
      "unit": "g"
    },
    "sourceValues": { "energyKcal": 500.0 },
    "packageQuantity": { "amount": 44, "unit": "g" },
    "per100g": {
      "amount": 100,
      "unit": "g",
      "values": { "energyKcal": 500.0 },
      "dailyReferencePercents": { "energyPercent": 25 }
    },
    "per100ml": null,
    "perPackage": {
      "amount": 44,
      "unit": "g",
      "values": { "energyKcal": 220.0 },
      "dailyReferencePercents": { "energyPercent": 11 }
    },
    "packageCalculationStatus": "CALCULATED",
    "packageCalculationReason": null
  }
}
```

`sourceValues`와 각 `values`에는 다음 일곱 필드가 모두 들어간다.

| 필드 | 단위 |
| --- | --- |
| energyKcal | kcal |
| carbsG, proteinG, fatG, sugarG | g |
| sodiumMg, cholesterolMg | mg |

모두 nullable number이다. 0은 실제 0, null은 결측 또는 계산 불가이다.
`sourceValues`는 저장값을 그대로 보존한다. 파생 값에서는 음수·비유한 수치를 null로 처리한다.
계산 결과는 소수 넷째 자리까지 반올림한다. 원본 값의 반올림 때문에 포장지의 정수 표기와
소수점 차이가 날 수 있으므로 파생 값은 '환산값'으로 표시한다.

### 계산 규칙

- 환산값 = 원본 수치 × 목표 기준량 ÷ 원본 기준량.
- `per100g`는 질량 기준인 경우만, `per100ml`는 부피 기준인 경우만 제공한다.
- g↔kg, ml↔L은 정규화한다. 밀도 정보 없이 g↔ml 변환은 하지 않는다.
- `44g x 4봉`처럼 명확한 묶음은 전체 176g으로 계산한다.
- `총내용량당`, `1개`, 기준량 누락·0·음수·복수 기준 표현은 추정하지 않는다.
- 원재료, 상품명, `nutrientText`의 숫자로 원본 수치의 기준량을 임의 복구하지 않는다.
- `CALCULATED`는 기준량과 용량의 환산이 가능하다는 뜻이지 모든 영양값이 존재하거나
  원본 라벨을 재검증했다는 뜻은 아니다. 각 영양 필드의 null 여부도 확인해야 한다.
- `dailyReferencePercents`는 각 portion에 해당하는 기존 공통 기준치 대비 비율이다.
  개인별 섭취 목표나 의학적 권고가 아니다. 누락 영양값의 비율도 null이다.

| packageCalculationStatus | packageCalculationReason | 처리 |
| --- | --- | --- |
| CALCULATED | null | perPackage의 해당 영양값을 확인하고 표시 |
| UNAVAILABLE | NUTRITION_BASIS_UNKNOWN | 원본 기준량 없음/해석 불가 |
| UNAVAILABLE | PACKAGE_QUANTITY_UNKNOWN | 상품 전체 용량 없음/해석 불가 |
| UNAVAILABLE | UNIT_MISMATCH | 원본 기준량과 전체 용량이 g/ml로 서로 다름 |

환산 불가일 때 `perPackage=null`이다. 전체 용량을 몰라도 원본 기준량이 명확하면
`per100g` 또는 `per100ml`는 존재할 수 있다.

## 적용 API

각 응답 안의 상품 객체에 같은 `nutrition` 구조가 추가된다.

- `GET /api/products/{barcode}`, `GET /api/products/id/{productId}`
- `GET /api/products/{barcode}/variants`, `GET /api/products/id/{productId}/variants`
- `GET /api/products/search`, `GET /api/products/filter`
- `GET /api/products/safe-recommendations`
- `GET /api/recommendations/products/{barcode}`, `GET /api/recommendations/products/id/{productId}`
- `GET /api/users/me/favorites`
- `GET /api/histories/user/{userId}` (존재하는 상품 객체에 적용)
- `POST /api/chat`: 백엔드가 AI로 보내는 `product.nutrition`에 포함한다.

`/filters`, `/classifications`, 즐겨찾기 여부/행동 기록 응답 등 상품 객체가 없는 응답은 대상이 아니다.
식단 검색의 저장된 boolean이나 추천 가중치는 이번 변경으로 재산정하지 않는다.

## FE 담당자 전달 사항

1. 상품 전체 열량에는 `product.nutrition.perPackage.values.energyKcal`을 사용한다.
   포키 녹차는 '총 44g · 환산 열량 220kcal'로 표시한다.
2. 100g 비교 화면은 `per100g`, 음료의 100ml 비교는 `per100ml`를 사용하고 단위를 표시한다.
3. 용량 옵션 변경 시 해당 옵션의 `data.product.nutrition`을 사용한다.
   대표 상품의 수치를 다른 용량 옵션에 재사용하지 않는다.
4. 새 중첩 필드와 영양 수치는 nullable로 선언한다. 구 서버에서 `nutrition`이 없거나
   `perPackage` 또는 해당 값이 null이면 '전체 용량 기준 정보 없음'으로 표시한다.
   기존 `energyKcal`을 전체 열량으로 대체 표시하거나 null을 0으로 바꾸지 않는다.
5. 기존 최상위 `energyKcal`, `carbsG` 등은 **원본 기준 값**을 유지한다.
   기존 `nutrientPercents` 역시 호환용 원본 수치 기준이며 전체 용량 기준이 아니다.
   응답의 `nutrientPercentsBasis=SOURCE_VALUES_LEGACY_NOT_PACKAGE`로 이를 명시한다.
   새 화면의 기준치 비율은 선택한 portion의 `dailyReferencePercents`를 사용한다.
6. 백엔드만 배포하면 기존 앱의 잘못된 전체 열량 표시가 자동으로 고쳐지지 않는다.
   FE의 표시 필드 변경이 함께 필요하다.

## AI 담당자 전달 사항

1. 선택 상품의 전체 열량/영양 설명은 `product.nutrition.perPackage.values`를 사용한다.
   100g 비교는 `per100g`, 100ml 비교는 `per100ml`만 사용한다. 답변에 기준량을 명시한다.
2. `weight=44g`와 기존 `energyKcal=500`을 묶어 '44g에 500kcal'라고 설명하지 않는다.
3. 계약값이 이미 환산되어 있으므로 다시 44/100을 곱하지 않는다.
4. `nutrition`이 없거나 필요한 값이 null이면 계산 불가 사유를 설명하고 라벨 확인을 안내한다.
   다른 상품·다른 용량·일반적인 식품 수치로 보충하지 않는다.
5. AI 요청 DTO/Pydantic 모델의 `nutrition` 수용과 프롬프트를 수정한다.
   선택 상품이 없는 질문에서는 기존과 같이 product=null이다.
6. 기존 `chat-analysis-v2`와 확인 응답 헤더는 유지한다. 영양 구조만 가산한 변경이며,
   알레르기·가족 판정의 권한 및 정책을 변경하지 않는다.
   최신 main의 본인 확인·서명·외부 AI 동의 전달도 유지한다.
   실제 AI 서비스의 파싱/답변까지 보장하는 테스트는 AI 담당자와 별도로 수행해야 한다.

## 배포 및 기존 데이터

- V17이 적용된 DB에 새 코드를 실행한다. `ddl-auto=update`로 대신 적용하지 않는다.
- 코드 배포 또는 V17만으로 기존 행에 기준량이 생기지 않는다. 백업 후 CSV와 상품 식별·용량·
  일곱 영양 수치가 일치하는 행에만 원본 기준량을 백필한다.
- 누락 기준량을 100g으로 일괄 채우지 않는다. 원본 영양 수치와 기존 이미지/알레르기 필드는 유지한다.
- 백필 계획의 중복 바코드는 제외한다. 기존 기준량이 있으면 덮어쓰지 않는다.
- V17 마이그레이션은 큰 테이블에 대한 INSTANT 컬럼 추가를 명시한다.
  해당 서버에서 불가능하면 오류가 나므로 별도 점검 없이 더 무거운 DDL로 바꾸지 않는다.
- 서버 담당자는 [V17 배포 절차](v17-deployment-checklist.md)와
  `scripts/run_nutrition_maintenance.py`의 단계별 도구를 사용한다.
  기존 PC 전용 로컬 스크립트나 로컬 전체 덤프를 운영에 그대로 적용하지 않는다.
- 속성 이력 수집기는 새 기준량을 기록할 수 있다. 기존 스냅샷과 과거 이력은 소급 수정하지 않는다.
  이번 메타데이터 백필의 변경 목록은 별도 plan/commit 로그로 보존한다.
- 생성된 **before-v17 백업은 롤백용**이며, 새 기준량이 반영된 배포용 덤프가 아니다.

## 로컬 적용 및 검증 결과 (2026-11-09)

- 로컬 `jjikmuk` 전체 백업 후 별도 복제 DB에서 V17과 백필을 먼저 검증했다.
  검증을 통과한 동일 계획만 로컬 원본 DB에 적용했다. AWS 및 운영 DB는 변경하지 않았다.
- 전체 1,348,425개 상품 중 289,044개 행에 `nutrition_basis_raw`를 추가했다.
  기존 상품 필드 전체의 적용 전후 해시가 같아, 영양 수치·상품명·용량·이미지·알레르기 등은 유지됐다.
- 백필된 행 중 전체 용량 환산 가능 276,330개, 용량 불명 12,698개,
  g/ml 불일치 12개, 잘못된 원본 기준량 4개이다. 나머지 상품에 기준량을 임의로 만들지 않았다.
- 포키 녹차 `8801019311673`, `8801019312137` 두 상품 모두
  원본 100g당 500kcal, 전체 44g당 환산 220kcal를 확인했다.
- 최초 로컬 작업본은 전체 자동 테스트 355개 중 349개 통과, 6개 조건부 생략, 실패 0개이다.
  실제 원본 CSV 행 확인, 적재 바인딩, H2 기반 상세·검색·용량 옵션 응답,
  인증된 챗봇 요청의 AI 전달 데이터, 기준량 누락·단위 불일치·null 보존을 검증했다.
- 실제 로컬 MySQL 상품에 대한 환산 검증도 별도로 완료했다.
  실제 Android 화면과 원격 AI 답변은 이번 자동 테스트 대상이 아니므로 담당자 연동 검증이 필요하다.
- 최신 main 기반 업로드본의 회귀 테스트는 363개 중 357개 통과, 6개 조건부 생략, 실패 0개이다.
  실행 JAR 빌드도 성공했다. 최신 챗봇 인증·서명 계약을 보존했다.
- 계획·백필·포키 환산·기존 필드 해시 검증 산출물은 Git 외부의 비공개 작업 경로에 보관한다.
  전체 DB 백업에는 개인정보가 포함될 수 있어 Git에 올리거나 공개 공유하지 않는다.
