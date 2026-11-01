# 가족 표시 정보 · 좋아요 · 최근 본 상품 API

기준: 2026-11-02, `eae67ec` 이후 구현. **로컬 MySQL V16 적용·복제 DB API 검증 완료, AWS/운영 DB 미적용이다.** Git 반영과 운영 배포는 별개다. 가족 추가 필드와 이력 규칙은 이전 v2의 해당 설명보다 이 문서가 우선한다. [V16 배포·검증 안내](v16-deployment-checklist.md)를 함께 확인한다.

## 1. 공통 규칙

- 모든 아래 API는 `Authorization: Bearer {token}`이 필요하다. 미완료 계정은 `403 PROFILE_INCOMPLETE`다.
- 가족/좋아요의 소유자는 JWT로 정한다. Body에 userId/ownerId를 보내지 않는다.
- 관계·이모지·좋아요는 계정별 서버 데이터다. 같은 계정으로 다른 기기에서 조회하면 동일한 상태를 받는다. 실시간 push는 아니므로 화면 복귀·로그인 후 다시 조회한다.
- 좋아요 식별자는 응답의 `product.productId`(양의 Long)다. **바코드를 productId 자리에 넣지 않는다.** 같은 이름이라도 용량/ID가 다르면 별개다.
- 좋아요는 관심 상태이지 안전 판정이 아니다. 상세 분석 API로 현재 선택 대상의 알레르기/식단 판정을 확인한다.
- 아래 상품 객체는 일부 필드만 발췌한 설명용 예시다.

## 2. 기존 가족 API: relation · emoji 추가

| Method | 경로 | 용도 |
|---|---|---|
| GET | `/api/users/me/family-profiles` | 가족 목록 |
| POST | `/api/users/me/family-profiles` | 가족 추가 |
| GET | `/api/users/me/family-profiles/{id}` | 가족 조회 |
| PATCH | `/api/users/me/family-profiles/{id}` | 부분 수정 |
| DELETE | `/api/users/me/family-profiles/{id}?version=0` | 가족 삭제 |

추가 필드는 **`relation: string|null`**, `emoji: string|null`이다. 둘 다 선택이며 최대 32 Unicode 코드 포인트, 제어 문자 금지, 앞뒤 공백 제거 규칙이다. 복합 이모지의 ZWJ·피부색·variation selector는 보존한다. 이모지 여부를 판별하는 고정 화이트리스트는 없다.

FE 요청에 따라 최초 초안의 `relationship` 대신 생성·수정·조회 모두 `relation`으로 통일했다. 요청의 `relationship`은 지원하지 않는 필드로 400을 반환하며 응답에도 없다. DB 내부 열 이름만 `relationship`으로 유지하여 V16 SQL은 변경하지 않았다.

- 생성 시 생략하면 null, 기존 가족도 null이다.
- PATCH 생략은 유지, null/공백 문자열은 해제다.
- 관계는 자유 표시 문자열이다. `어머니`, `자녀`, `친구` 등이며 서버 enum은 아니다.
- 관계/이모지는 화면용이며 알레르기/식단 분석에 합치지 않는다.
- 타인 가족은 `404 FAMILY_NOT_FOUND`다. PATCH/DELETE는 최신 version이 필요하고 충돌은 `409 PROFILE_VERSION_CONFLICT`다.

생성 요청(201):

```http
POST /api/users/me/family-profiles
Authorization: Bearer {token}
Content-Type: application/json
```

```json
{"nickname":"엄마","relation":"어머니","emoji":"👩","allergies":"peanut,soy","specialDiet":"lowSodium"}
```

```json
{
  "message": "가족 프로필 생성 성공",
  "data": {
    "id":41,"nickname":"엄마","allergies":"peanut,soy","specialDiet":"lowSodium",
    "diseases":null,"dislikedIngredients":null,"version":0,"relation":"어머니","emoji":"👩"
  }
}
```

부분 수정(200): `PATCH /api/users/me/family-profiles/41`

```json
{"version":0,"relation":"보호자","emoji":"🧑"}
```

다른 필드는 유지한다. 타입·길이 오류는 `400 VALIDATION_FAILED`와 해당 `field`를 반환한다. 본인 `/api/users/me`에는 이 필드를 추가하지 않는다.

## 3. 좋아요 현재 상태 API (신규)

| Method | 경로 | 성공 |
|---|---|---|
| PUT | `/api/users/me/favorites/{productId}` | 200, 등록 |
| DELETE | `/api/users/me/favorites/{productId}` | 200, 해제 |
| GET | `/api/users/me/favorites/{productId}` | 200, 단건 상태 |
| GET | `/api/users/me/favorites?page=0&size=20` | 200, 현재 목록 |

모두 Request Body 없음. 등록/해제는 토글이 아니라 **목표 상태 지정**이다. 같은 요청을 다시 보내도 반대로 바뀌지 않는다. 다른 기기의 상충 요청은 서버에서 직렬 처리되며 마지막 처리 상태를 재조회한다.

등록 응답(단건 GET도 같은 data 구조):

```json
{
  "message":"좋아요 등록 성공",
  "data":{"productId":12345,"isFavorite":true,"favoritedAt":"2026-11-02T10:00:00"}
}
```

해제 또는 미등록 GET 단건의 data:

```json
{"productId":12345,"isFavorite":false,"favoritedAt":null}
```

- GET 단건은 상태 조회다. 미등록 양수 ID는 false이며 상품 존재 검증 API가 아니다.
- 신규 PUT의 상품이 현재 데이터셋에 없으면 `404 PRODUCT_NOT_FOUND`다.
- 재PUT은 등록 날짜/순서를 바꾸지 않는다. 재DELETE도 200이며 이력을 중복 생성하지 않는다.
- 실제 등록 시 `FAVORITE`, 실제 해제 시 `UNFAVORITE` 이력을 상태 변경과 같은 트랜잭션에서 저장한다.
- 해제는 DISLIKE가 아니다. 추천에서는 같은 상품의 최신 좋아요/해제 이벤트만 고려하여 이전 좋아요를 취소하고 반복 클릭 가중치 누적을 방지한다.
- 탈퇴 시 상태/이력을 함께 삭제하며 로그아웃은 삭제하지 않는다.

목록 응답:

```json
{
  "message":"좋아요 상품 목록 조회 성공",
  "data":{
    "items":[{
      "productId":12345,"barcode":"8800000000001","favoritedAt":"2026-11-02T10:00:00",
      "isFavorite":true,"identityStatus":"INTERNAL_ID",
      "product":{"productId":12345,"barcode":"8800000000001","productName":"예시 상품"}
    }],
    "page":0,"size":20,"hasNext":false
  }
}
```

- 최신 등록순, 동시각은 저장 ID 내림차순. page 기본 0, 0~10000; size 기본 20, 1~50.
- **data는 객체, 배열은 data.items**다. 빈 목록은 items=[]다.
- 상품이 카탈로그에서 사라져도 좋아요는 유지한다. product=null, identityStatus=NOT_IN_ACTIVE_DATASET이며 ID로 해제할 수 있다. 같은 바코드가 다른 상품에 재사용되어도 자동 연결하지 않는다.
- Product는 현재 표시 정보이고 분석 결과가 없다. 상세 조회로 최신 분석을 확인한다.
- 다른 기기에서 추가/해제하면 offset이 변할 수 있다. FE는 productId로 중복 제거하고 새로고침 시 0페이지부터 조회한다.
- productId=null인 상품은 기존 ID 발급 절차를 먼저 완료해야 한다. API가 ID를 추측하거나 임의 발급하지 않는다.
- 잘못된 ID/page/size는 400 VALIDATION_FAILED다.

### FE의 두 화면 연결

- 상품 상세 하트: `GET /api/users/me/favorites/{productId}`의 `isFavorite`로 초기 표시하고, 등록은 PUT, 해제는 DELETE 응답을 반영한다.
- MY 즐겨찾기 목록: `GET /api/users/me/favorites?page=0&size=20`의 `data.items`를 표시하고, 상세에서 돌아오면 재조회한다. 같은 서버 상태이므로 로컬 저장소를 별도 원본으로 유지하지 않는다.
- 로그아웃·계정 전환 시 이전 계정의 화면 캐시를 비우고 새 계정 토큰으로 재조회한다. 서버 즐겨찾기 자체를 일괄 삭제하지 않는다.
- 기존 로컬 즐겨찾기는 자동 이전되지 않는다. 서버 이전이 필요하면 계정 확인·동의 후 실제 productId로 PUT한다. 구형 FAVORITE 로그로 현재 상태를 추정하지 않는다.

## 4. 최근 본 상품: 기존 이력 API 확장

```http
GET /api/histories/user/{userId}?view=recent&page=0&size=20
Authorization: Bearer {token}
```

본인/관리자만 가능하며 타인 이력은 기존대로 403이다.

| view | 의미 | data 타입 |
|---|---|---|
| 생략 또는 all | 기존 전체 행동, FAVORITE/UNFAVORITE 포함 | 배열 (기존 호환) |
| recent | SCAN/DETAIL_VIEW 중 상품별 최신 조회 | 객체: items/page/size/hasNext |

recent의 page/size 범위는 좋아요 목록과 같다. 잘못된 view/page/size는 400 VALIDATION_FAILED다. all은 기존 전체 목록이며 page/size를 적용하지 않는다.

```json
{
  "message":"사용자 히스토리 조회 성공",
  "data":{
    "items":[{
      "id":321,"actionType":"SCAN","scannedAt":"2026-11-02T10:00:00",
      "productId":12345,"attributeSnapshotId":789,"identityStatus":"INTERNAL_ID",
      "analysisMode":"none","personalizationAllowed":false,
      "product":{"productId":12345,"barcode":"8800000000001","productName":"예시 상품"}
    }],
    "page":0,"size":20,"hasNext":false
  }
}
```

- 최신 조회순, 같은 시각은 이력 ID 내림차순. 같은 productId는 한 번만 표시한다.
- productId 없는 구형 이력은 barcode로 묶고 LEGACY_VERSION_UNKNOWN을 유지한다. 구형 ID 없는 이력과 신규 ID 이력을 임의로 동일 상품이라 합치지 않는다.
- 구형 NO_BARCODE_ROW_...는 현재 상품에 재연결하지 않는다. 데이터셋 교체 시 재사용될 수 있기 때문이다.
- 상품 삭제 시 product=null일 수 있다. 목록의 product는 현재 표시 정보이지 당시 안전 판정이 아니다.
- 좋아요 자체는 조회가 아니므로 recent 순서를 갱신하지 않는다. 좋아요 행동은 view=all로 확인한다.
- 기존 호환 LocalDateTime 문자열에는 UTC offset이 없다. FE가 임의로 Z를 붙이지 않는다. 시간대 표준화는 후속 범위다.

### 자동 기록과 중복 방지

`GET /api/products/{barcode}`, `GET /api/products/id/{productId}` 성공 시 로그인 계정에 SCAN 한 건을 자동 기록한다.

| 조회 조건 | 최근 본 상품 | 본인 취향 신호 |
|---|---|---|
| self | 포함 | 사용 가능 |
| selected (가족 또는 가족+본인) | 포함 | 제외 |
| none (전원 OFF, Bearer 유지) | 포함 | 제외 |
| 비로그인 | 기록 없음 | 제외 |

- SCAN은 기존 코드 호환이다. 자동 SCAN을 실제 카메라 촬영 완료로 해석하면 안 된다.
- 검색/필터 결과·용량 옵션 목록·챗봇 조회는 자동 SCAN을 생성하지 않는다.
- 상세 GET 이후 FE는 SCAN/DETAIL_VIEW를 중복 POST하지 않는다.
- 상세 GET 재호출은 행동 로그에 추가될 수 있으나 recent는 상품별 한 번만 표시한다.
- 관리자 대리 조회는 분석 대상이 아닌 요청한 관리자에게 기록하며 개인화 제외다.

### 기존 POST /api/histories/events

캐시 화면처럼 상세 GET을 호출하지 않는 독립 행동에서만 필요한 이벤트를 전송한다. barcode/productId 중 하나 이상, 함께 주면 동일 상품이어야 한다.

추가 Body 선택 필드: analysisMode, includeSelf, familyProfileIds(Long 배열). 상품 API와 같은 소유권 검증이며 생략은 self, 전원 OFF는 none이다.

```json
{"productId":12345,"actionType":"DETAIL_VIEW","analysisMode":"none"}
```

응답과 기존 전체 이력에도 analysisMode/personalizationAllowed가 추가된다.

**FAVORITE 이력과 현재 좋아요 상태는 별개다.** 기존 FAVORITE POST는 호환을 위해 유지하지만 현재 상태를 등록하지 않는다. 새 화면은 PUT/DELETE만 호출하고 별도 FAVORITE POST는 하지 않는다. UNFAVORITE는 서버가 생성하는 코드이며 events API의 직접 입력 허용값에는 추가하지 않는다.

## 5. 배포·추가 협의

1. V15 스키마와 stable productId 발급 상태 확인 후 승인된 절차로 백업한다.
2. V16은 가족 표시 열, 이력 문맥 열·인덱스, product_favorites 테이블을 추가한다. histories ALTER/인덱스 생성의 부하·락은 스테이징 복제본에서 측정 후 적용한다. 신규 Entity에는 V16이 필요하며 ddl-auto=update로 대체하지 않는다.
3. 기존 가족 metadata는 null, 기존 이력은 self/personalizationAllowed=true다. 과거 누락된 가족 조회를 소급 생성하거나 기존 이력의 실제 대상을 추정하지 않는다.
4. 기존 FAVORITE 로그만으로 현재 좋아요를 복원하지 않는다. 해제·현재 상태를 알 수 없기 때문이다.
5. 로컬 가족/좋아요의 서버 이전은 계정 소유 확인·사용자 동의가 필요한 별도 FE 작업이다. 자동 업로드하지 않았다.
6. 관계 ID enum/표시명, 이모지 카탈로그, 기기 간 활성 토글 동기화는 추가 협의다. 이번에는 표시 값 자체만 저장한다.
7. FE는 새 nullable 가족 필드와 좋아요/최근 목록 DTO(data.items)를 준비하고 서버 배포 버전을 맞춘다. none이어도 Bearer를 유지해야 계정 이력이 남는다.

## 6. 검증 범위

격리 H2 통합 테스트: 가족 필드 왕복·부분 수정·검증·version 충돌·타 계정 차단, 세션 간 좋아요 공유, 중복/동시 PUT·DELETE, 상품 소실·바코드 재사용, 탈퇴 정리, 최근 목록 정렬·중복 제거·페이지·가족/none, 전체 이력 호환, 추천 개인화 분리.

이는 실제 기기 연동·운영 MySQL 마이그레이션이나 대규모 histories 실측 성능을 대신하지 않는다.

2026-11-02 MySQL 8.0.44 검증: 전체 백업을 새 복제 DB에 복원한 뒤 V16 한 건 적용, checksum 검증, 반복 migrate 0건을 확인했다. 복제 DB의 실제 HTTP·DB 제약 검증 41개 항목이 통과했고 이후 로컬 원본 jjikmuk에도 V16을 적용했다. 상품 1,348,425건·추천 후보 세트 233,658건·사용자 10건·기존 이력 2건 등 주요 기존 데이터의 원본 필드 해시가 적용 전후 일치했다. 상품 속성 기록 1,348,425건도 유지되었다. 테스트 계정/쓰기 검증은 복제 DB에서만 실행했다. 로컬 histories는 2건이므로 운영 이력 규모의 인덱스 생성 시간·락을 대표하지 않는다.

실행 결과: relation 계약 반영 후 전체 313개 중 **307개 성공, 6개 건너뜀, 실패/오류 0**. 건너뛴 항목은 명시적으로 활성화해야 하는 대용량 CSV/외부 평가셋 테스트다. 이번 신규 통합 테스트 13개는 모두 성공했고 bootJar도 성공했다.

기본 재현 명령: `./gradlew test bootJar`. 이 PC는 Windows 한글 경로의 Java 테스트 클래스 로딩 문제를 피하기 위해 저장소 밖 로컬 init script로 빌드 산출물만 영문 경로로 옮겨 같은 태스크를 실행했다. 작업 브랜치는 `feat/family-favorites-history`이며 기존 미커밋 작업은 보존했다.
