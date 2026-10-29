# 프론트 인증·프로필 연동 변경 계약 v2

기준: 2026-10-23 로컬 구현. 프론트가 전달한 「인증 연동: 백엔드 답변 및 계약 확인 요청」의 12개 항목을 반영한다. **운영 배포·DB 마이그레이션 완료를 의미하지 않는다.** 기존 `auth-users.md`, `API_REFERENCE.md`의 인증/사진/가족/분석 대상 설명과 충돌하면 이 문서가 우선이다. 그 외 상품 검색·용량·이력 계약은 기존 문서를 따른다.

## 1. 확정 요구와 임시 구현값

| 구분 | 구현 | 프론트와 추가 합의할 내용 |
|---|---|---|
| 부분 수정 | PATCH 추가. 미전송 유지, 선택 필드 null/빈 문자열 해제 | CSV 문자열 유지 여부. 현재 배열은 거절한다. |
| 자동 로그인 | Access 15분, Refresh 최초 로그인부터 30일 고정, 회전 및 재사용 감지 | 정확한 수명, 고정/슬라이딩, 갱신 응답 유실 시 재로그인 UX |
| Google 연결 | 기존 비밀번호로 소유 확인 후 연결. 5분 증명, 오입력 최대 5회 | 증명 수명/횟수, 연결 확인·취소·재설정 이동 UI |
| Google 완료 | 별도 최종 완료 API만 profileCompleted=true 설정 | 추가 입력 화면의 최종 제출 버튼과 연결 |
| 새 비밀번호 | 영문/숫자 필수. ASCII 출력 가능 특수문자 선택 허용. 한글/공백/기타 Unicode 불가 | 특수문자 범위와 기타 Unicode 불허 정책은 아직 합의 전이다. |
| 사진 | 인증된 본인만 접근하는 DB 저장. JPEG/PNG, 2MiB, 최대 4096×4096 | 장기적으로 비공개 객체 저장소로 옮길지, 크기/해상도/보존 정책 |
| 가족 | 계정별 서버 CRUD, 최대 20명, version 충돌 검사 | 인원/이름 제한, 기존 로컬 자료 이전, 선택 상태 동기화 |
| 복수 분석 | 선택한 사람들의 제한을 합집합으로 적용. 식단은 모두 충족해야 함 | 충돌 조건/후보 부족 안내, 일반 추천 UI 문구 |

임시값은 이미 최종 합의된 정책으로 간주하지 않는다. Access 수명은 `JWT_ACCESS_EXPIRATION_MS`(기본 900000), Refresh 수명은 `AUTH_REFRESH_LIFETIME_DAYS`(기본 30, 허용 1~90)로 설정한다. 앱은 상수보다 서버의 expiresAt/refreshExpiresAt을 사용한다.

## 2. 신규·변경 요청주소

| Method | 주소 | 용도 | 인증 |
|---|---|---|---|
| POST | `/api/auth/login` | 로그인 및 Access/Refresh 발급 | 이메일/비밀번호 |
| POST | `/api/auth/refresh` | Refresh 회전 및 Access 갱신 | body의 Refresh |
| POST | `/api/auth/logout` | 현재 기기 서버 세션 폐기 | Bearer |
| POST | `/api/auth/google` | Google 검증, 신규 가입 또는 연결 필요 분기 | Google idToken |
| POST | `/api/auth/google/link` | 기존 비밀번호 확인 후 명시적 연결 | linkToken + 비밀번호 |
| POST | `/api/auth/google/link/cancel` | 임시 연결 증명 폐기 | linkToken |
| GET | `/api/users/me` | 본인/완료 상태/인증 방법/사진 경로 조회 | Bearer |
| PATCH | `/api/users/me` | 프로필 부분 수정 | Bearer |
| PUT | `/api/users/me` | 기존 전체 교체(호환 유지) | Bearer |
| POST | `/api/users/me/profile/complete` | 최종 프로필 제출 및 완료 | Bearer |
| GET | `/api/users/me/photo` | 비공개 사진 바이너리 조회 | Bearer |
| PUT | `/api/users/me/photo` | multipart 사진 등록/교체 | Bearer |
| DELETE | `/api/users/me/photo` | 기본 사진으로 초기화 | Bearer |
| GET | `/api/users/me/family-profiles` | 가족 목록 조회 | Bearer |
| POST | `/api/users/me/family-profiles` | 가족 생성 | Bearer |
| GET | `/api/users/me/family-profiles/{id}` | 가족 단건 조회 | Bearer |
| PATCH | `/api/users/me/family-profiles/{id}` | 가족 부분 수정 | Bearer |
| DELETE | `/api/users/me/family-profiles/{id}?version={version}` | 가족 삭제 | Bearer |

신규 Method·주소 조합은 13개다. 기존 27개와 합쳐 40개다. 서버 주소는 배포 담당자가 해당 버전을 배포한 후 확인해야 하며, 기존 Tailscale 주소가 열린다고 이 API가 배포된 것은 아니다.

## 3. 로그인·Refresh·로그아웃

로그인 body는 기존 `{"email":"user@example.com","password":"Example123!"}`를 유지한다. 로그인 성공, 직접 Google 로그인 성공, Google 연결 성공, 갱신 성공은 다음 모델을 **data 없이 최상위**에 반환한다. 값과 시각은 예시다.

```json
{
  "message": "로그인 성공",
  "token": "<access-token>",
  "tokenType": "Bearer",
  "userId": 17,
  "email": "user@example.com",
  "expiresAt": "2026-10-23T12:15:00Z",
  "expiresInSeconds": 900,
  "refreshToken": "<opaque-refresh-token>",
  "refreshExpiresAt": "2026-11-22T12:00:00Z",
  "isNewUser": false,
  "profileCompleted": true,
  "authProvider": "LOCAL",
  "hasPassword": true
}
```

`authProvider`는 LOCAL/GOOGLE/LOCAL_AND_GOOGLE이다. Google 전용 계정은 hasPassword=false이며 비밀번호 로그인·찾기·변경 대신 Google 로그인 안내를 제공한다. 연결 계정은 비밀번호 사용이 가능하다.

```http
POST /api/auth/refresh
Content-Type: application/json

{"refreshToken":"<현재 저장된 refreshToken>"}
```

- Refresh는 32바이트 난수의 43자 base64url 문자열이며 JWT가 아니다. DB에는 SHA-256 해시만 저장한다.
- 성공할 때마다 이전 Refresh를 소비하고 새 Refresh를 반환한다. Access와 Refresh를 함께 원자적으로 교체 저장한다. Refresh 만료일은 연장하지 않는다.
- 같은 Refresh 재사용은 `401 REFRESH_TOKEN_REUSED`다. 해당 기기 세션 전체를 폐기하므로 방금 받은 새 토큰도 사용할 수 없다. 다른 기기 세션까지 폐기하지는 않는다.
- 앱은 갱신 요청을 한 번만 진행(single-flight)하고 대기 중인 요청들이 결과를 공유해야 한다. 동시 요청/무조건 재시도 금지다.
- 만료·폐기된 Refresh는 `401 REFRESH_TOKEN_INVALID`다. 서버에 접속할 수 없는 경우는 이를 뜻하지 않는다.
- 갱신 응답이 유실되면 서버에서 이미 회전했을 수 있다. 현재 구현은 재사용 응답 복구/idempotency를 제공하지 않으므로 기존 Refresh를 반복하지 않고 재로그인한다.
- login/google/refresh/google-link 경로는 오래된 Bearer 헤더 때문에 별도 소유 증명 검증이 차단되지 않는다. 일반적으로 이 요청에는 Bearer를 넣지 않는다.
- 로그아웃은 body 없이 호출한다. 응답은 `{"message":"...","data":{"userId":17,"serverTokenRevoked":true}}`다. 현재 세션의 Access/Refresh가 모두 폐기되며 사진·가족은 남는다.
- 구형 sid 없는 JWT는 기존 만료까지 호환한다. 해당 토큰으로 로그아웃하면 기기를 식별할 수 없어 보수적으로 모든 세션을 폐기한다.
- 비밀번호 변경·재설정은 tokenVersion 증가와 모든 서버 세션 폐기를 함께 처리한다. 명확한 실패 시에는 유지한다. 탈퇴 시 세션·사진·가족 등 계정별 자료를 함께 삭제한다.
- 앱은 민감 토큰을 Android 보안 저장소에 보관하고 로그·분석 이벤트·공유 문서에 기록하지 않는다. 앱 시작 시 GET me, Access 만료라면 Refresh, 회복 불가능한 인증 실패면 재로그인한다. 네트워크 오류/503은 세션 유지 후 재시도 화면이다.

## 4. Google 명시적 연결과 최종 완료

`POST /api/auth/google`의 body는 `{"idToken":"<Google ID token>"}`다. 서버는 issuer, audience, 만료, 이메일 검증 여부, Google subject를 검사한다. 앱/서버의 OAuth Client ID를 배포 전에 맞춰야 한다.

신규 Google 계정은 서비스를 위한 Access/Refresh를 발급하되 profileCompleted=false다. 재로그인해도 완료 전에는 false를 유지한다. 앱이 추가 입력 화면으로 이동한다. API 전체를 미완료 계정에 금지하는 접근 정책은 이번에 추가하지 않았다.

같은 이메일의 일반 계정이 있으면 **200이더라도 로그인 성공이 아니다.** 다음 응답에는 Access/Refresh가 없다.

```json
{
  "message": "기존 계정 소유 확인 후 Google 계정을 연결해주세요.",
  "code": "GOOGLE_LINK_REQUIRED",
  "linkToken": "<one-time-link-proof>",
  "expiresAt": "2026-10-23T12:05:00Z",
  "expiresInSeconds": 300,
  "loginGranted": false
}
```

사용자가 연결을 선택하고 기존 비밀번호를 입력하면 다음 요청을 보낸다.

```http
POST /api/auth/google/link
Content-Type: application/json

{"linkToken":"<one-time-link-proof>","currentPassword":"Example123!"}
```

- 성공 시 LOCAL_AND_GOOGLE로 저장하고 위 로그인 모델을 반환한다.
- 비밀번호 오입력: `400 GOOGLE_LINK_PASSWORD_INVALID`, field=currentPassword. 최대 5회 실패 이후 추가 사용은 불가하다.
- 만료·취소·이미 소비·5회 소진: `410 GOOGLE_LINK_EXPIRED`. Google 로그인부터 다시 진행한다.
- 다른 Google 계정 연결 충돌: `409 GOOGLE_ACCOUNT_ALREADY_LINKED` 또는 Google identity 검증 단계의 `401 GOOGLE_TOKEN_INVALID`다.
- 취소: `POST /api/auth/google/link/cancel`에 `{"linkToken":"..."}`. 200 메시지 반환. 유효 형식의 이미 없어진 증명 취소는 성공으로 처리한다.
- 연결 전 linkToken은 API 인증용 Bearer로 사용할 수 없다. 비밀번호를 모르면 기존 password_reset 흐름을 진행한 뒤 Google 연결을 새로 시작한다.
- 이미 연결된 Google subject는 이후 정상 로그인한다. 이전 GOOGLE 전용 계정의 subject가 비어 있으면 검증된 Google 이메일로 최초 1회 subject를 등록한다. LOCAL 계정 자동 연결과는 다르다.

최종 추가 입력 완료:

```http
POST /api/users/me/profile/complete
Authorization: Bearer <access-token>
Content-Type: application/json

{"nickname":"찍먹사용자","allergies":"egg,wheat","specialDiet":"lactoOvoVegetarian,lowSugar,highProtein"}
```

필수는 nickname이고 나머지는 선택이다. 선택하지 않아도 완료 가능하다. 이 요청은 전체 프로필 제출이며 선택 필드를 생략하면 비운다. 부분 저장은 PATCH를 사용한다. 완료 응답은 `{"message":"추가 프로필 입력 완료","data":{...최신 프로필...,"profileCompleted":true}}`다. 성공 응답을 잃으면 GET me로 확인하며, 다시 동일 최종 프로필을 제출해도 완료 상태는 true다.

## 5. 프로필 조회·부분 수정

GET/PATCH/PUT/완료 응답의 data:

```json
{
  "id": 17, "email": "user@example.com", "nickname": "찍먹사용자",
  "allergies": "egg,wheat", "diseases": null,
  "specialDiet": "lactoOvoVegetarian,lowSugar,highProtein", "dislikedIngredients": null,
  "role": "USER", "authProvider": "LOCAL", "profileCompleted": true,
  "hasPassword": true, "photoUrl": "/api/users/me/photo"
}
```

사진이 없으면 photoUrl=null이다. photoUrl은 공개 Firebase URL이 아니라 현재 로그인 계정용 상대 경로다. 관리자용 타인 프로필 응답에서는 이 경로를 그 타인의 사진 URL로 해석하지 않는다.

PATCH 허용 필드는 nickname/allergies/diseases/specialDiet/dislikedIngredients뿐이다.

| 전송 | 의미 |
|---|---|
| `{ "nickname":"새닉네임" }` | 닉네임만 바꾸고 기존 조건 유지 |
| `{ "allergies":null, "specialDiet":"" }` | 해당 선택 조건 전체 해제 |
| `{}` | 변경 없음, 최신 프로필 반환 |
| `{ "nickname":null }` 또는 빈 nickname | 400, 필수 닉네임을 비울 수 없음 |
| `{ "allergies":[] }` | 400, 문자열/null 계약이며 배열 미지원 |
| `{ "profileCompleted":true }` | 400, 클라이언트가 완료 상태 직접 변경 불가 |

PATCH/기존 PUT은 완료 상태를 바꾸지 않는다. 기존 PUT은 전체 교체이므로 생략한 선택 필드를 비운다. 공개 닉네임 중복 확인은 현재 사용 중인 이름에 available=false를 반환할 수 있지만, 본인 수정 시 본인 닉네임 유지/대소문자 변경은 허용한다. 사전 확인은 예약이 아니며 최종 저장에서 다시 검사한다.

조건 ID 목록은 GET `/api/products/classifications`(26개 알레르기), GET `/api/products/filters`(채식 6개·영양 6개)와 기존 카탈로그를 따른다. 새 요청은 `lowSugar` 등 정규 key를 CSV 문자열로 보낸다. `low_sugar` 같은 앱 내부 enum을 그대로 사용하지 말고 카탈로그에 맞게 변환한다. diseases/dislikedIngredients 미입력은 null로 유지하며 저당 선택을 질환으로 저장하지 않는다.

## 6. 사진: 별도 multipart API

```http
PUT /api/users/me/photo
Authorization: Bearer <access-token>
Content-Type: multipart/form-data; boundary=<클라이언트 생성>
```

파트 이름은 `file` 하나이며 파일 바이너리를 보낸다. JSON/base64/photoUrl을 body로 보내지 않는다. Postman은 Body → form-data → file을 File로 선택한다. boundary는 클라이언트에 맡긴다.

- 성공 200: `{"message":"프로필 사진 저장 성공","data":{"photoUrl":"/api/users/me/photo","authenticationRequired":true}}`.
- 파일명/확장자만 신뢰하지 않고 실제 JPEG/PNG 형식과 픽셀 크기를 검사한다. MIME 불일치도 거절한다. 픽셀을 재인코딩하여 EXIF/GPS 및 뒤에 붙은 데이터를 제거한다.
- GET은 JSON이 아니라 image/jpeg 또는 image/png 바이트다. Bearer가 필요하고 `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`를 사용한다. 브라우저에 URL만 붙여 넣으면 인증 실패할 수 있다.
- 사진 없음 404 PHOTO_NOT_FOUND, 형식/해상도 오류 400 PHOTO_INVALID, 2MiB 초과 413 PHOTO_TOO_LARGE. 잘못된 교체 요청으로 기존 사진을 삭제하지 않는다.
- DELETE는 body 없이 200 메시지다. 이미 없으면 성공으로 처리하며 다음 GET은 404, 프로필 photoUrl은 null이다.
- 로그아웃·다른 기기 로그인은 사진을 삭제하지 않는다. 다른 계정은 자기 경로로 자기 사진만 조회한다.
- 사진은 DB의 profile_photos에 저장한다. 배포 담당자는 백업 크기·복원·개인정보 보관을 고려해야 한다. 객체 저장소/CDN 업로드는 이번에 수행하지 않았다.

## 7. 가족: 계정 소유와 동시 수정

생성 예:

```http
POST /api/users/me/family-profiles
Authorization: Bearer <access-token>
Content-Type: application/json

{"nickname":"어머니","allergies":"soy","specialDiet":"lowSodium","diseases":null,"dislikedIngredients":null}
```

201 응답:

```json
{"message":"가족 프로필 생성 성공","data":{"id":41,"nickname":"어머니","allergies":"soy","specialDiet":"lowSodium","diseases":null,"dislikedIngredients":null,"version":0}}
```

- 목록 GET은 `data:[...]`, 단건 GET은 `data:{...}`다. 비밀번호/ownerId를 요청하지 않는다. 서버가 Bearer의 소유자로 한정한다.
- 가족은 별도 로그인 계정이 아니다. ‘나’는 GET me 결과를 사용하고 가족 생성으로 복제하지 않는다. 가족 이름의 전역 중복 검사는 하지 않는다.
- PATCH는 부분 수정 규칙 + 마지막 조회 version을 보낸다. 예: `{"version":0,"allergies":null}`. 성공 시 최신 가족과 version을 반환한다.
- DELETE는 `?version=현재버전`이 필수다. 성공 200 메시지다. 삭제 후 재조회/재삭제는 404다.
- 다른 소유자/삭제된 ID는 404 FAMILY_NOT_FOUND, 오래된 version은 409 PROFILE_VERSION_CONFLICT다. 누락/잘못된 version은 400이다.
- 다른 기기에서 변경한 경우 GET으로 다시 읽고 병합을 사용자에게 확인한 뒤 최신 version으로 제출한다. 자동으로 덮어쓰지 않는다.
- 본인 프로필 PATCH는 필드 단위 마지막 저장 우선이며 가족처럼 version을 요구하지 않는다. 같은 필드를 여러 기기에서 동시 수정할 때 본인도 충돌 UI가 필요한지는 추가 합의 대상이다.
- 기존 로컬 가족 데이터는 소유자가 확인되지 않았으므로 자동 업로드·삭제하지 않는다. 분석 대상 선택 상태는 이번에 서버 저장하지 않는다.

## 8. 상품·추천 분석 대상 계약

아래 6개 API에 공통 query를 추가했다.

1. GET `/api/products/{barcode}`
2. GET `/api/products/{barcode}/variants`
3. GET `/api/products/search`
4. GET `/api/products/filter`
5. GET `/api/products/safe-recommendations`
6. GET `/api/recommendations/products/{barcode}`

| query | 값/의미 |
|---|---|
| analysisMode 생략 | 로그인은 self, 공개 비로그인 조회는 none |
| analysisMode=self | 본인 조건, includeSelf/familyProfileIds는 보내지 않음 |
| analysisMode=selected | 선택한 가족 + 선택적으로 본인 |
| includeSelf | selected에서만 사용. 기본 false |
| familyProfileIds | selected에서만 사용. 쉼표 또는 반복 키의 Long 목록, 최대 20명 |
| analysisMode=none | Bearer는 유지하되 누구의 조건도 적용하지 않음 |

```http
GET /api/products/8800000000000?analysisMode=selected&includeSelf=true&familyProfileIds=41,42
GET /api/products/search?keyword=두유&analysisMode=none
GET /api/products/safe-recommendations?limit=10&analysisMode=selected&familyProfileIds=41
```

- selected에 대상이 없으면 400 ANALYSIS_SELECTION_INVALID. 모두 해제는 반드시 none으로 표시한다. self/selected에 인증이 없으면 401이다. 두 추천 API는 none이어도 로그인이 필요하다.
- 타인의 가족은 사용 불가하다. 서버에서 실제 소유자의 가족 조건을 읽으므로 임의 알레르기 JSON을 GET Body로 보내지 않는다.
- 여러 대상의 알레르기/기피 성분은 합집합, 식단/질환 기반 제한은 모두 적용한다. 하나라도 필수 조건과 충돌하면 추천에서 제외한다. 후보 부족 때문에 필수 조건을 완화하지 않는다.
- 일반 조회는 `analysis.status=NOT_EVALUATED`, `analysis.analysisApplied=false`, `analysis.selection.mode=none`이다. `isDangerous=false`만 보고 안심 판정을 표시하지 않는다.
- 상품 응답에는 `analysis.dietConstraints`를 추가했다. 기존 analysis.status는 **알레르기 판정**이다. 알레르기 PASS라도 식단 MISMATCH/UNKNOWN일 수 있다. UI는 두 결과를 분리해서 표시해야 한다.
- 추천 응답의 대상 정보는 `data.analysisSelection`이다. none이면 홈 recommendationMode 및 대체 resultMode는 GENERAL, 항목의 safety/dietConstraints는 NOT_EVALUATED, 대체 항목의 recommendationTier는 GENERAL이다. 이를 맞춤 안심 추천이라고 표시하지 않는다.
- 가족/none에서는 본인 행동 이력으로 개인화하지 않는다. 바코드 단건 조회의 자동 SCAN도 본인 모드에서만 기록한다. 기존 POST histories/events는 계정 본인 이력 계약이므로 가족/none 행동을 본인 선호로 전송하지 말아야 한다. 가족별 행동 이력 저장은 별도 후속 범위다.
- 같은 용량에 여러 행이 있으면 알레르기와 식단 모두 보수적으로 합친다. 충돌 자료가 대표 행 선택 때문에 사라지지 않는다.
- 홈 cursor는 계정·선택 대상·조건·카테고리에 묶는다. 이들 변경 시 이전 cursor를 폐기하고 첫 페이지를 다시 조회한다. 이전 버전 cursor도 사용하지 않는다. 기존 excludeBarcodes 중복 제외 계약은 유지한다.
- 2026-10-28 `/api/chat`에도 같은 분석 대상 query와 공통 상품 판정을 적용했다. [챗봇 공통 분석 판정 계약](chat-analysis-contract-v1.md)을 따른다. AI의 수신·응답 확인 구현과 공동 배포는 필요하며 용량 옵션 집계·가족별 설명·공통 검색 호출 연동은 별도 합의 대상이다.

## 9. 입력·시간·공통 오류

- 새 비밀번호: 8자 이상, UTF-8 72바이트 이하, A–Z/a–z와 0–9 각각 포함, ASCII U+0021~U+007E만 허용한다. 특수문자 포함은 필수가 아니며 trim/소문자 변환하지 않는다. 기존 로그인은 이 신규 생성 규칙을 적용하지 않고 저장된 해시로 검증한다.
- 닉네임: NFKC/trim, 완성형 한글·영문·숫자·밑줄 2~20자, 계정 닉네임 대소문자 미구분 중복. 이메일 NFKC/trim/소문자 및 형식 검사는 기존 정책을 유지한다.
- OTP는 4자리 문자열·5분이다. 가입 인증 완료 증명은 30분, 비밀번호 재설정 증명은 5분으로 서로 다르다.
- 이메일 응답 expiresAt/resendAvailableAt에 offset을 포함한다. 예: `2026-10-23T21:05:00+09:00`. Access/Refresh/Google 연결 시각은 UTC의 Z 형식이다. 프론트는 모두 Instant로 해석한다.
- 이메일 저장 시각은 기존 LocalDateTime 구조를 유지하므로 운영 JVM/DB의 시간대 정책을 배포 간 일관되게 유지해야 한다. 이 변경은 과거 저장 시각을 변환하지 않는다.
- 오류는 status/code/message, 선택 field/retryAfterSeconds/remainingAttempts를 제공한다. 일부 기존 상품 검증 오류는 message만 있으므로 앱의 공통 fallback은 유지한다.

```json
{"status":429,"code":"OTP_RATE_LIMITED","message":"인증번호는 잠시 후 다시 요청할 수 있습니다.","retryAfterSeconds":42,"remainingAttempts":null,"field":null}
```

재전송 대기에는 `Retry-After` 헤더도 제공한다. OTP 오입력에는 remainingAttempts가 제공되며 0이면 재발송이 필요하다. 형식 오류/미요청 등 모든 오류에 횟수가 있는 것은 아니다. 만료 판정은 서버가 최종 기준이다.

DB 일시 장애로 JWT 확인에 실패하면 `503 AUTH_SERVICE_UNAVAILABLE`을 반환한다. 이를 AUTH_TOKEN_INVALID로 간주하여 토큰을 삭제하지 않는다. 입력 검증 실패, 403 ACCESS_DENIED, Google 외부 서버 장애 역시 자동 로그아웃 사유가 아니다.

## 10. 응답 유실·재시도 시 프론트 규칙

| 요청 | 응답을 못 받았을 때 |
|---|---|
| 인증메일 발송/재전송 | 발송 실패로 단정하지 않는다. 도착한 코드와 서버 재전송 제한을 확인하고 성공 응답 전에 타이머를 초기화하지 않는다. |
| OTP 검증 | 이미 코드가 소비되었으면 OTP_NOT_REQUESTED일 수 있다. 증명을 잃었다면 코드 재발급·재검증한다. |
| 회원가입 | 입력을 보존하고 로그인 시도. 중복 이메일을 곧바로 기존 실패라고 해석하지 않는다. |
| 비밀번호 변경/재설정 | 성공으로 단정하지 않는다. 기존 세션이 무효이면 새 비밀번호 로그인/재설정으로 복구한다. 자동 반복 변경하지 않는다. |
| Google 연결 | 같은 linkToken 무한 재사용 금지. Google 로그인을 다시 하면 연결 완료 여부에 따라 정상 로그인 또는 연결 증명을 반환한다. |
| Refresh | 처리 여부 불명 시 같은 Refresh를 반복하지 않는다. 재로그인한다. |
| 프로필 PATCH/완료 | GET me로 최신 상태와 완료 여부를 확인한다. |
| 가족 생성 | 목록을 다시 읽어 중복 생성 여부를 확인한다. 현재 생성 idempotency key는 없다. |
| 가족 수정/삭제 | 단건/목록을 재조회하고 최신 version 사용. 삭제 후 404면 이미 삭제된 상태로 처리한다. |
| 사진 등록/교체/삭제 | GET me/photo로 최종 상태를 확인한다. 잘못된 업로드가 기존 사진을 지우지 않는다. |

가입 증명 30분이 지나 UI를 띄울 때 별도 상태 확인 API는 없다. 서버가 준 expiresAt으로 만료 안내 후 `POST /api/auth/email/send`(purpose=signup) → `/email/verify`로 새 증명을 받는다. 최종 가입에서 `410 VERIFICATION_EXPIRED`가 반환되는 경우도 동일하게 처리한다.

## 11. 테스트와 배포 전 체크

2026-10-23 `gradlew.bat test bootJar --no-daemon --console=plain` 결과: BUILD SUCCESSFUL. 총 144개 중 140개 통과, 실패 0개, 대용량 CSV의 명시적 실행 플래그가 필요한 기존 테스트 4개 제외. 이번 인증 연동 검증 19개를 추가했다. H2/모의 외부 인증 결과이며 MySQL 마이그레이션·실기기 OAuth 결과가 아니다.

- Gradle test 프로필은 H2 및 테스트용 JWT 키를 사용한다. 실제 Google 토큰 검증/메일/객체 저장소 통신은 모의 처리한다.
- 프로필 보존/전체 해제, 명시적 완료, 새 비밀번호 경계값, 기존 비밀번호 로그인, Refresh 회전/재사용/동시 요청/만료, 기기별 로그아웃, 비밀번호 변경·재설정 전체 폐기를 검증한다.
- Google 임시 증명의 접근 불가/비밀번호 검증/취소/횟수/만료, 가족 소유권/동시 수정 version, 사진 형식·크기·격리·실패 보존, 대상 없음과 가족 합집합, cursor 변경, 용량별 식단 충돌을 검증한다.
- V14는 신규 스키마 파일만 추가한다. users에 google_subject/has_profile_photo, auth_sessions/refresh_credentials/google_link_grants/family_profiles/profile_photos를 추가한다. **로컬/운영 MySQL에는 이 작업으로 적용하지 않았다.**
- 배포 전 별도 승인하에 백업 → 스테이징 MySQL에서 V14 적용 및 validate → 실제 메일/Google/두 기기 테스트 → 운영 반영 순서가 필요하다. 애플리케이션을 운영 연결 설정으로 실행해 자동 적용하지 않는다.
- Refresh/연결 증명 및 사진 보관·만료 정리 작업, 실제 서비스 부하, Google Client ID, 앱의 새 enum 처리와 보안 토큰 저장은 배포 전 확인한다. 이 테스트가 실기기·운영 DB 검증을 대신하지 않는다.

## 12. 프론트에 회신할 합의 목록

1. Access 15분 + 최초 로그인부터 Refresh 30일 고정으로 확정할지, 갱신 연장형이 필요한지.
2. Refresh 응답 유실 시 재로그인 방식을 수용할지, 향후 제한된 재시도 복구 계약이 필요한지.
3. 비밀번호 ASCII 특수문자 선택 허용/기타 Unicode 불허, 기존 닉네임 규칙을 확정할지.
4. 가족 최대 20명·이름 규칙·선택 상태 동기화·기존 로컬 자료 이전·본인 프로필 동시 수정 정책.
5. 사진 DB 저장을 초기 방식으로 채택할지, 비공개 객체 저장소와 URL 만료 방식으로 바꿀지.
6. 미완료 Google 계정의 API 이용 범위를 앱 화면 제한만으로 둘지 서버에서도 제한할지.
7. 가족/none 일반 추천의 UI, 가족 이력 저장, 챗봇 분석 대상 전달까지 이번 연동 범위에 넣을지.
8. 정확한 개발/운영 배포 주소와 Google OAuth Client ID를 비밀값 없이 확인하고 실제 연동 시험 일정을 잡을 것.
