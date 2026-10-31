# 찍먹 Backend 전체 API 명세서

> 2026-11-01 인증 후속: `403 PROFILE_INCOMPLETE` 서버 제한, `POST /api/auth/logout/refresh`, JWT 본인 제외 닉네임 사전 확인을 추가했다. [인증 v2](frontend-auth-integration-v2.md)의 허용 API/FE 처리 규칙을 따른다. 운영 배포 완료를 의미하지 않는다.

> 최신 계약 우선순위: 아래 기존 상세와 충돌하면 [챗봇 공통 판정 계약](chat-analysis-contract-v1.md), [프론트 인증·프로필 v2](frontend-auth-integration-v2.md), [상품 ID·관측 이력 계약](../catalog-evolution-stage1-3.md)을 따른다. 하단의 과거 챗봇 본인 검증 미구현 설명은 최신 계약으로 대체된다. 실제 서버 배포 여부는 별도로 확인한다.

> 2026-10-28 상품 모델 추가: [내부 상품 ID·관측 이력·카테고리 용도 계약](../catalog-evolution-stage1-3.md)을 함께 확인한다. ID 조회 3개·관리자 3개 경로, 행동 이력 productId 입력, 상품/추천 응답의 용도 근거가 추가되었다. 기존 barcode API와 PK는 유지한다. 원본/운영 DB 적용은 아직 하지 않았다.

> 2026-10-23 프론트 연동 v2 변경: [인증·프로필·사진·가족·분석 대상 최신 계약](frontend-auth-integration-v2.md)을 먼저 확인한다. 아래 기존 상세 중 24시간/Refresh 없음/Google 자동 연결/PUT 시 완료/사진·가족 미구현 설명은 v2로 대체된다. 운영 배포 완료를 뜻하지 않는다.

작성 기준: 2026-10-15 팀 저장소 커밋 `87184c4`(로컬 `072ddac`) 및 2026-10-23 로컬 추천 정책 v5.1 변경이다. 27개 Method·요청주소 조합과 상품 용량 옵션 API를 포함한다. 추천 v5.1의 Git 업로드·운영 배포 완료를 의미하지 않는다. JSON의 사용자·상품·토큰·점수는 설명용 예시이다.

이 문서는 Spring Backend의 현재 구현 계약이다. 같은 커밋이 실제 서버에 배포되어 있어야 동일하게 동작한다. 별도 AI/OCR 서비스의 API는 포함하지 않는다. 별도 표시가 없는 JSON 예시의 사용자·상품·토큰·점수·시각은 설명용이며 실제 데이터가 아니다.

각 요청주소를 독립 섹션으로 구성했다. Notion API 페이지에는 해당 섹션과 참조하는 공통 모델을 함께 사용한다. 기존의 ‘키워드와 OR 조건 검색’과 ‘필터 기반 검색’은 별도 API가 아니라 통합 조건 검색의 사용 예시이다.

## 접속 주소

| 환경 | Base URL | 조건 |
|---|---|---|
| 로컬 | `http://localhost:8080` | 로컬 Backend 실행 |
| 팀 개발 서버 | `https://jjikmuk-backend-dev.tail198441.ts.net` | Tailscale 접속 및 해당 버전 배포 필요 |

요청주소 앞에 Base URL을 붙인다. 예: `GET http://localhost:8080/api/products/filters`. GET 요청에는 Body를 보내지 않는다. 목록 파라미터는 쉼표 연결 또는 동일 키 반복을 사용하고, URL의 한글·공백·cursor 값은 클라이언트가 인코딩한다.

## 요청주소별 목록

‘선택’ 인증은 토큰 없이 일반 조회가 가능하고 유효한 로그인 토큰을 보내면 개인 분석을 포함한다는 뜻이다. 로그인 필수 API에는 `Authorization: Bearer {token}`을 전송한다.

| Method | 요청주소 | 기능 | 인증 |
|---|---|---|---|
| POST | [`/api/auth/email/send`](#post-apiauthemailsend) | 이메일 인증번호 발송 및 재전송 | 불필요 |
| POST | [`/api/auth/email/verify`](#post-apiauthemailverify) | 이메일 인증번호 검증 및 증명 발급 | 불필요 |
| POST | [`/api/auth/google`](#post-apiauthgoogle) | Google 로그인 및 자동 가입 | 불필요 |
| POST | [`/api/auth/login`](#post-apiauthlogin) | 이메일 로그인 | 불필요 |
| POST | [`/api/auth/logout`](#post-apiauthlogout) | 로그아웃 | 필수 |
| POST | [`/api/auth/logout/refresh`](#post-apiauthlogoutrefresh) | Refresh 기반 서버 로그아웃 | body의 Refresh |
| GET | [`/api/auth/nicknames/availability`](#get-apiauthnicknamesavailability) | 닉네임 사용 가능 여부 조회 | 선택, 본인 제외는 Bearer 필요 |
| POST | [`/api/auth/password/reset`](#post-apiauthpasswordreset) | 비밀번호 재설정 | 불필요 |
| POST | [`/api/auth/signup`](#post-apiauthsignup) | 회원가입 | 불필요 |
| POST | [`/api/chat`](#post-apichat) | AI 챗봇 중계 | 필수 |
| POST | [`/api/histories/events`](#post-apihistoriesevents) | 사용자 행동 기록 | 필수 |
| GET | [`/api/histories/user/{userId}`](#get-apihistoriesuseruserid) | 사용자 행동 및 스캔 이력 조회 | 본인 또는 관리자 |
| GET | [`/api/products/classifications`](#get-apiproductsclassifications) | 카테고리 및 알레르기 분류 조회 | 불필요 |
| GET | [`/api/products/filter`](#get-apiproductsfilter) | 통합 조건 검색 | 선택 |
| GET | [`/api/products/filters`](#get-apiproductsfilters) | 식단 및 영양 필터 종류 조회 | 불필요 |
| GET | [`/api/products/safe-recommendations`](#get-apiproductssafe-recommendations) | 맞춤 안심 상품 추천 및 카테고리별 보기 | 필수 |
| GET | [`/api/products/search`](#get-apiproductssearch) | 키워드 상품 검색 | 선택 |
| GET | [`/api/products/{barcode}`](#get-apiproductsbarcode) | 바코드 상품 조회 | 선택 |
| GET | [`/api/products/{barcode}/variants`](#get-apiproductsbarcodevariants) | 상품 전체 용량 옵션 조회 | 선택 |
| POST | [`/api/recommendations/feedback`](#post-apirecommendationsfeedback) | 추천 피드백 기록 | 필수 |
| GET | [`/api/recommendations/products/{barcode}`](#get-apirecommendationsproductsbarcode) | 특정 상품의 대체 상품 추천 | 필수 |
| GET | [`/api/users`](#get-apiusers) | 전체 사용자 조회 | 관리자 |
| GET | [`/api/users/me`](#get-apiusersme) | 내 프로필 조회 | 필수 |
| PUT | [`/api/users/me`](#put-apiusersme) | 내 프로필 전체 수정 | 필수 |
| GET | [`/api/users/{userId}`](#get-apiusersuserid) | 사용자 ID로 프로필 조회 | 본인 또는 관리자 |
| PUT | [`/api/users/{id}`](#put-apiusersid) | 사용자 ID로 프로필 전체 수정 | 본인 또는 관리자 |
| DELETE | [`/api/users/{id}`](#delete-apiusersid) | 회원 탈퇴 | 본인 또는 관리자 |
| PUT | [`/api/users/{id}/password`](#put-apiusersidpassword) | 로그인 상태에서 비밀번호 변경 | 본인 |

아래는 10월 23일 추가 경로 13개다. 11월 1일 추가 로그아웃은 위 목록에 포함했다. 상품 ID 관련 별도 추가 경로는 상품 계약을 참고한다. 신규 상세 및 기존 계약 변경은 [v2 명세](frontend-auth-integration-v2.md)에 있다.

| Method | 요청주소 | 기능 |
|---|---|---|
| POST | `/api/auth/refresh` | 토큰 갱신 |
| POST | `/api/auth/google/link` | 명시적 Google 연결 |
| POST | `/api/auth/google/link/cancel` | 연결 취소 |
| PATCH | `/api/users/me` | 부분 수정 |
| POST | `/api/users/me/profile/complete` | 최종 입력 완료 |
| GET | `/api/users/me/photo` | 사진 조회 |
| PUT | `/api/users/me/photo` | 사진 등록·교체 |
| DELETE | `/api/users/me/photo` | 사진 삭제 |
| GET | `/api/users/me/family-profiles` | 가족 목록 |
| POST | `/api/users/me/family-profiles` | 가족 생성 |
| GET | `/api/users/me/family-profiles/{id}` | 가족 조회 |
| PATCH | `/api/users/me/family-profiles/{id}` | 가족 수정 |
| DELETE | `/api/users/me/family-profiles/{id}` | 가족 삭제 |

## 공통 모델 바로가기

- [공통 요청 규칙](#공통-요청-규칙)
- [공통 오류와 예외](#공통-오류와-예외)
- [사용자 입력 규칙](#사용자-입력-규칙)
- [공통 상품 응답](#공통-상품-응답): Product, ProductAnalysis, nutrientPercents, 개인 알레르기 analysis
- [추천 공통 판정 객체](#추천-공통-판정-객체): SafetyDecision, DietConstraintDecision
- [미구현 경로와 연동 주의사항](#미구현-경로와-연동-주의사항)

## 공통 요청 규칙

로컬 Base URL은 `http://localhost:8080`이다. 팀 서버 사용 시 Base URL만 해당 배포 주소로 바꾼다. GET 요청에는 JSON Body를 넣지 않는다. 본문이 있는 요청은 `Content-Type: application/json`을 사용한다.

```http
Authorization: Bearer {로그인 응답의 token}
Content-Type: application/json
```

- `token`은 찍먹 서버의 로그인 토큰이다. Google `idToken` 및 이메일 `verificationToken`과 서로 다르다.
- 상품·추천 API의 선택적 `userId`는 일반 앱에서는 생략한다. 서버가 로그인 토큰에서 ID를 확인한다. 일반 사용자는 타인의 ID를 지정할 수 없으며 관리자는 예외이다.
- 인증 불필요 API에도 만료·변조된 Bearer 토큰을 보내면 인증 필터에서 401을 반환한다. 로그인·가입·공개 목록 조회에 불필요한 오래된 토큰을 붙이지 않는다.
- 바코드는 문자열이다. 숫자로 변환하지 않는다. 데이터에 `NO_BARCODE_ROW_...` 같은 내부 대체 식별자가 포함될 수 있다.
- 사용자 ID는 정수(Long)이다. `/{id}` 자리에 이메일을 넣지 않는다.
- 선택값 없음은 프로필에서 `null`, 목록에서는 `[]`로 표현한다. `"없음"`을 공통 해제 값으로 사용하지 않는다.

## 시간과 로그인 상태

- Access 만료는 UTC Instant이고 기본 900초다. Refresh는 최초 로그인부터 기본 30일 고정이다. 서버의 expiresAt/refreshExpiresAt을 사용한다.
- 이메일 OTP·인증 증명 응답에는 offset을 포함한다. 기존 행동 기록 시각은 LocalDateTime이다. 최종 만료 판정은 서버가 담당한다.
- Refresh/PATCH/사진/가족 신규 계약은 v2 문서를 따른다.
- 앱 시작 시 `GET /api/users/me`로 사용자·세션을 확인한다. 네트워크 실패와 401을 구분한다. 403은 권한 부족이므로 무조건 로그아웃시키지 않는다.

## 공통 오류와 예외

CustomException 및 인증 필터 오류는 다음 구조를 사용한다. `field`는 없으면 생략한다.

```json
{
  "status": 409,
  "code": "NICKNAME_ALREADY_EXISTS",
  "message": "이미 사용 중인 닉네임입니다.",
  "field": "nickname"
}
```

| HTTP | code | 의미 |
|---|---|---|
| 400 | `INVALID_REQUEST_BODY` | JSON 형식 오류, 필수 본문 필드 누락·타입 불일치 |
| 400 | `VALIDATION_FAILED` | 허용 값·선택 조합 등 검증 실패 |
| 401 | `AUTHENTICATION_REQUIRED` | 인증이 필요한 경로에 유효한 인증이 없음 |
| 401 | `AUTH_TOKEN_EXPIRED` | 서비스 로그인 토큰 만료 |
| 401 | `AUTH_TOKEN_INVALID` | 변조·이전 형식·무효화된 서비스 토큰, 사용자 조회 실패 등 |
| 403 | `ACCESS_DENIED` | 사용자/인증 API에서 권한 부족 |
| 403 | `PROFILE_INCOMPLETE` | 미완료 계정의 허용 범위 밖 요청. 토큰 유지, 추가 프로필 입력으로 이동 |
| API별 | `REQUEST_FAILED` | 상품·추천·이력 등에서 사용하는 일반 업무 오류 코드 |
| 500 | `INTERNAL_SERVER_ERROR` | 서버 오류 |

**현재 모든 오류가 이 구조로 통일된 것은 아니다.** `/api/products/filter`, `/api/products/search`의 직접 검증 오류는 `{ "message": "..." }` 또는 지원 목록을 포함한 별도 응답이다. 상품·이력·추천의 소유권 오류는 동일한 HTTP 401/403이어도 코드가 `REQUEST_FAILED`일 수 있다. 각 페이지의 오류 설명을 함께 적용한다.

필수 query 누락, 숫자 자리에 문자열 입력 등 Spring 파라미터 바인딩 오류는 현재 전용 처리기가 없어 공통 Exception 처리에서 500이 될 수 있다. 이를 정상적인 입력 오류 계약으로 권장하지 않으며 개선 필요 항목으로 남긴다.

## 사용자 입력 규칙

| 값 | 계약 |
|---|---|
| email | 필수 string. NFKC 정규화, 앞뒤 공백 제거, 소문자 변환, 이메일 형식·최대 254자 검사 |
| nickname | 필수 string. NFKC·trim 후 2~20자, 완성형 한글·영문·숫자·밑줄 허용. 중복은 대소문자 구분 없이 검사 |
| password / newPassword | 8자 이상, UTF-8 72바이트 이하, 문자와 숫자 각각 포함, 공백 불가. 비밀번호는 trim하지 않음 |
| allergies | 선택 string/null. 26개 영문 ID를 쉼표로 연결. 예: `egg,wheat` |
| specialDiet | 선택 string/null. 채식 최대 1종 + 영양조건 복수 선택. 예: `lactoOvoVegetarian,lowSugar,highProtein` |
| diseases | 선택 string/null. 실제 입력한 질환 목록. 저당 선호를 임의로 당뇨로 변환하지 않음 |
| dislikedIngredients | 선택 string/null. 예: `고수,오이` |

- allergies·specialDiet는 배열이 아닌 문자열이다. UI 표시 이름·아이콘·상위 메뉴 `Allergy`, `Vegetarian`을 전송하지 않는다.
- 현재 선택지는 [식단·영양 필터](#get-apiproductsfilters) 및 [카테고리·알레르기 분류](#get-apiproductsclassifications)와 동일하다. 할랄은 허용 필터가 아니다.
- 선택 없음·전체 해제는 `null` 또는 `""`을 사용한다. `"없음"`은 공통 해제 값이 아니다. 알레르기·식단에서 미지원 값이면 400이다.
- 호환용 한글 별칭을 받더라도 새 쓰기는 정규 영문 ID로 저장한다. 구형 저장 데이터 조회에는 원 문자열이 남아 있을 수 있다.
- diseases·dislikedIngredients는 항목 최대 50개, 각 100자, 정규화 저장 문자열 최대 1000자이다. 쉼표·세미콜론·슬래시·파이프·줄바꿈을 구분자로 받으며 새 요청은 쉼표 사용을 권장한다.
- 프로필 사진은 이번 서버 요청·응답에 포함하지 않는다.

## POST /api/auth/email/send

이메일 인증번호 발송 및 재전송.

```http
POST /api/auth/email/send
```

| 항목 | 내용 |
|---|---|
| 인증 | 불필요 |
| Query | 없음 |
| Body | email: string 필수, purpose: string 필수 |
| purpose | `signup` 또는 `password_reset` |
| 성공 | 200 OK |

### 요청

```json
{"email":"user@example.com","purpose":"signup"}
```

비밀번호 찾기는 같은 URL에 `purpose=password_reset`을 사용한다. 재전송도 같은 요청을 다시 보낸다.

### 성공 응답

```json
{
  "message": "인증번호가 이메일로 발송되었습니다.",
  "data": {
    "email": "user@example.com",
    "purpose": "signup",
    "expiresAt": "2026-10-15T15:05:00",
    "expiresInSeconds": 300,
    "resendAvailableAt": "2026-10-15T15:01:00"
  }
}
```

data.email/purpose는 정규화 문자열, 두 At 필드는 offset을 포함하는 시각 문자열, expiresInSeconds는 정수(초)이다. OTP 자체는 응답에 포함하지 않는다. 아래 과거 시각 예시 대신 최신 v2의 offset 예시를 따른다.

### 정책·오류

- 인증번호는 앞자리 0이 가능한 4자리 문자열이며 5분 유효하다.
- 최소 재전송 대기 60초, 활성 코드가 유지되는 연속 발송 구간에서 최초 발송 포함 최대 5회이다. 재전송 성공마다 만료가 새로 5분 설정되므로 ‘고정 5분당 5회’ 제한으로 설명하지 않는다.
- 재전송 성공 시 같은 이메일·purpose의 이전 코드와 이전 인증 완료 증명은 무효화된다. 메일 발송 예외로 트랜잭션이 실패하면 DB의 기존 상태는 롤백된다.
- 실제 메일 수신 시각은 이 응답과 별개이다. 네트워크 타임아웃만으로 서버의 발송 실패를 단정하지 않는다.

| HTTP | code | 상황 |
|---|---|---|
| 400 | EMAIL_INVALID | 이메일 형식 오류 |
| 400 | VALIDATION_FAILED | purpose 미지원(field=purpose) |
| 409 | EMAIL_ALREADY_REGISTERED | 가입용 발송인데 이미 가입된 이메일 |
| 404 | USER_NOT_FOUND | 재설정용 발송인데 미가입 이메일 |
| 409 | AUTH_METHOD_NOT_SUPPORTED | Google 전용 계정에 재설정용 발송 요청 |
| 429 | OTP_RATE_LIMITED | 재전송 대기·발송 횟수 제한 |
| 500 | INTERNAL_SERVER_ERROR | 메일 발송 등 서버 오류 |

재전송 대기 429에 retryAfterSeconds와 Retry-After 헤더를 제공하며 OTP 오입력에는 remainingAttempts를 제공한다.

## POST /api/auth/email/verify

이메일 인증번호 검증 및 증명 발급.

```http
POST /api/auth/email/verify
```

인증 불필요, Query 없음, 성공 200이다. email·purpose·code는 모두 필수 string이다.

```json
{"email":"user@example.com","purpose":"signup","code":"0427"}
```

```json
{
  "message": "이메일 인증이 완료되었습니다.",
  "data": {
    "email": "user@example.com",
    "purpose": "signup",
    "verificationToken": "example-verification-token",
    "expiresAt": "2026-10-15T15:31:00",
    "expiresInSeconds": 1800
  }
}
```

| data 필드 | 타입 | 의미 |
|---|---|---|
| email, purpose | string | 인증한 이메일과 목적 |
| verificationToken | string | 이후 가입 또는 재설정에 쓰는 일회용 증명. 로그인 토큰이 아님 |
| expiresAt | string(OffsetDateTime) | 인증 완료 증명의 만료 시각, offset 포함 |
| expiresInSeconds | integer | signup=1800초, password_reset=300초 |

성공하면 OTP를 삭제하고 별도 증명을 만든다. 같은 OTP로 검증을 다시 호출하는 동작을 재사용 가능한 것으로 가정하지 않는다. 올바른 형식의 오답은 최대 5회 시도 후 코드를 삭제한다. 마지막 실패는 429이고 이후 같은 코드는 미요청으로 처리될 수 있다.

| HTTP | code | 상황 |
|---|---|---|
| 400 | EMAIL_INVALID / VALIDATION_FAILED | 이메일·purpose 오류 |
| 400 | OTP_INVALID | 4자리 형식 오류 또는 번호 불일치 |
| 400 | OTP_NOT_REQUESTED | 요청 내역 없음·이미 소비 또는 삭제됨 |
| 410 | OTP_EXPIRED | OTP 5분 만료 |
| 429 | OTP_RATE_LIMITED | 실패 횟수 초과 |

### 인증 완료 후 30분 만료 화면

가입용 증명을 받은 뒤 expiresInSeconds로 타이머를 관리한다. 30분이 지났다는 안내를 띄우기 위한 별도 API는 없다. 최종 가입 시 서버가 만료를 판단하면 `410 VERIFICATION_EXPIRED`를 반환한다. 사용자가 재인증을 선택하면 [이메일 인증번호 발송 및 재전송](#post-apiauthemailsend)을 purpose=signup으로 호출하고 [이메일 인증번호 검증 및 증명 발급](#post-apiauthemailverify)를 다시 거친다. purpose=password_reset의 증명은 30분이 아니라 5분이다.

4자리 형식 자체가 잘못된 요청은 `OTP_INVALID`이지만 검증 실패 횟수에는 포함하지 않는다. 형식이 올바른 오답이 실패 횟수에 반영된다.

## POST /api/auth/google

Google 로그인 및 자동 가입.

```http
POST /api/auth/google
```

인증 불필요, Query 없음, 성공 200이다. Body의 idToken은 필수 string이며 Google에서 발급한 ID 토큰을 사용한다.

```json
{"idToken":"example-google-id-token"}
```

응답 필드는 [이메일 로그인](#post-apiauthlogin)와 동일하며 message는 `구글 로그인 성공`이다. 새 계정 예시는 다음과 같다.

```json
{
  "message": "구글 로그인 성공",
  "token": "example-service-jwt",
  "tokenType": "Bearer",
  "userId": 43,
  "email": "google-user@example.com",
  "expiresAt": "2026-10-16T06:00:00Z",
  "expiresInSeconds": 900,
  "isNewUser": true,
  "profileCompleted": false
}
```

- 서버는 GoogleIdTokenVerifier와 캐시된 Google 공개키로 RS256 서명을 검증한다. GOOGLE_CLIENT_ID와 aud의 일치, issuer, exp/iat, email_verified=true, subject 및 이메일을 확인한다. tokeninfo에 사용자 토큰을 보내지 않는다.
- Google 통신·검증은 DB 트랜잭션 밖에서 완료하고, 성공한 식별 정보만 별도 계정/세션 트랜잭션에 전달한다. 이미 트랜잭션이 열린 내부 호출은 검증 전에 거부한다. 요청·응답·401/503 계약은 변경하지 않는다.
- 신규 사용자는 임시 닉네임으로 가입하며 `/api/users/me/profile/complete` 최종 제출만 profileCompleted=true로 변경한다. 미완료 계정의 중간 저장은 PATCH를 사용하고 완료로 처리하지 않는다. 구형 PUT 프로필은 완료 전 403 PROFILE_INCOMPLETE이다.
- 기존 일반 계정 이메일이면 GOOGLE_LINK_REQUIRED와 임시 linkToken만 반환하고 기존 비밀번호로 명시적 연결해야 로그인한다. v2의 요청/분기 모델을 사용한다.
- 최초 가입 후 다시 로그인한 미완료 사용자는 isNewUser=false이고 profileCompleted=false일 수 있다. 화면 이동은 profileCompleted로 판단한다.
- 최초 Google 가입 요청이 동시에 도착해 신규 사용자 유일값 충돌이 발생하면 롤백 후 새 트랜잭션에서 한 번 재조회한다. 같은 Google subject면 동일 userId/isNewUser=false로 복구하고, LOCAL 계정은 명시적 연결을 요구한다. 다른 Google subject에는 로그인 권한을 부여하지 않는다.
- Google 전용 계정의 일반 비밀번호 로그인·찾기·변경은 지원하지 않는다. 두 방식이 연결된 계정은 기존 비밀번호 로그인이 가능하다.

401 GOOGLE_TOKEN_INVALID(형식·서명·클레임 검증 실패), 503 GOOGLE_LOGIN_UNAVAILABLE(서버 Client ID 미설정 또는 Google 공개키 조회/인증서 장애), 공통 400/500 등이 가능하다. 요청·성공 응답 계약은 그대로다.

## POST /api/auth/login

이메일 로그인.

```http
POST /api/auth/login
```

인증 불필요, Query 없음, 성공 200이다. Body는 email·password 필수 string이다.

```json
{"email":"user@example.com","password":"Samplepass1!"}
```

```json
{
  "message": "로그인 성공",
  "token": "example-service-jwt",
  "tokenType": "Bearer",
  "userId": 42,
  "email": "user@example.com",
  "expiresAt": "2026-10-16T06:00:00Z",
  "expiresInSeconds": 900,
  "isNewUser": false,
  "profileCompleted": true
}
```

| 필드 | 타입 | 의미 |
|---|---|---|
| message | string | 처리 메시지 |
| token | string | 서비스 JWT |
| tokenType | string | Bearer |
| userId | integer(Long) | 본인 ID |
| email | string | 저장 이메일 |
| expiresAt | string(Instant) | 로그인 토큰 만료 시각, UTC |
| expiresInSeconds | integer | Access 유효시간(기본 900초) |
| refreshToken / refreshExpiresAt | string / Instant | 회전되는 갱신 토큰과 고정 만료 시각(v2) |
| authProvider / hasPassword | string / boolean | 로그인 방법과 비밀번호 지원 여부(v2) |
| isNewUser | boolean | 이메일 로그인에서는 false |
| profileCompleted | boolean | 추가 프로필 입력 완료 여부 |

400 INVALID_REQUEST_BODY, 401 LOGIN_FAILED(미가입·비밀번호 불일치·잘못된 이메일), 409 AUTH_METHOD_NOT_SUPPORTED(Google 전용 계정) 등이 가능하다. 로그인 password는 과거 계정 호환을 위해 신규 가입 규칙으로 다시 검사하지 않고 저장 해시와 비교한다.

2026-11-01 추가: `429 LOGIN_RATE_LIMITED` — 계정별 최근 5분 5회 / IP별 최근 5분 30회(기본값), 성공·실패 포함. `Retry-After` 헤더와 최상위 `retryAfterSeconds`에 정수 초를 반환한다. 429에서는 자동 로그인 재시도·Refresh 재시도를 하지 않고 로그인 화면에 대기시간을 표시한다. [상세 정책·FE 전달 사항](frontend-auth-integration-v2.md#33-이메일비밀번호-로그인-시도-제한--2026-11-01)을 참고한다.

## POST /api/auth/logout

로그아웃.

```http
POST /api/auth/logout
Authorization: Bearer {token}
```

로그인 필수, Query/Body 없음, 성공 200이다.

```json
{
  "message": "로그아웃 처리되었습니다. 기기에 저장된 토큰을 삭제해주세요.",
  "data": {"userId":42,"serverTokenRevoked":true}
}
```

현재 기기의 서버 세션과 Access/Refresh를 폐기한다. 앱도 로컬 토큰을 삭제한다. 구형 sid 없는 JWT는 모든 기기 세션을 폐기한다. 실패 시 서버 폐기 완료로 단정하지 않는다.

## POST /api/auth/logout/refresh

Access가 만료되어도 갱신 없이 서버 세션을 폐기한다. Authorization 불필요, JSON Body는 `{"refreshToken":"<저장된 Refresh Token>"}`다. 성공 200은 기존 로그아웃과 같은 data.userId/serverTokenRevoked=true를 반환하며 새 토큰을 발급하지 않는다. 해당 세션만 폐기하고 다른 기기·계정과 사진·가족은 유지한다.

증명 해시/세션이 남아 있으면 소비·만료·이미 폐기된 Refresh의 반복 폐기는 200이다. 누락/null은 400 INVALID_REQUEST_BODY, 잘못된 형식·미등록·삭제된 증명은 401 REFRESH_TOKEN_INVALID이다. **폐기 요청의 재시도와 Refresh 갱신의 재시도는 다르다.** [인증 v2 3.1절](frontend-auth-integration-v2.md)을 참고한다.

## GET /api/auth/nicknames/availability

닉네임 사용 가능 여부 조회.

```http
GET /api/auth/nicknames/availability?nickname=찍먹_user1
```

인증 선택(본인 닉네임을 제외하려면 Bearer 필요), nickname 필수 string, Body 없음, 성공 200이다.

```json
{
  "message": "닉네임 사용 가능 여부 조회 성공",
  "data": {"nickname":"찍먹_user1","available":true}
}
```

data.nickname은 정규화된 이름이고 available은 boolean이다. 이미 사용 중이면 409가 아니라 200과 available=false이다. 형식이 잘못되면 400 NICKNAME_INVALID이다. 닉네임을 예약하지 않으므로 최종 가입/수정에서도 중복을 다시 검사한다. 유효한 Bearer를 전달하면 JWT 본인을 제외하여 현재 닉네임은 available=true이다. 비로그인 요청은 전체 사용자와 비교한다. userId 쿼리로 본인을 지정할 수 없으며 잘못된/만료 Bearer는 401이다. 미완료 계정도 이 API는 사용할 수 있다.

## POST /api/auth/password/reset

비밀번호 재설정.

```http
POST /api/auth/password/reset
```

인증 불필요, Query 없음, 성공 200이다. email, verificationToken, newPassword는 모두 필수 string이다.

```json
{
  "email": "user@example.com",
  "verificationToken": "example-reset-verification-token",
  "newPassword": "Newpassword2!"
}
```

```json
{"message":"비밀번호가 성공적으로 재설정되었습니다."}
```

절차는 [이메일 인증번호 발송 및 재전송](#post-apiauthemailsend)(password_reset) → [이메일 인증번호 검증 및 증명 발급](#post-apiauthemailverify)(password_reset) → 이 API이다. code를 이 API에 직접 보내는 이전 계약은 사용하지 않는다. 임시 비밀번호를 이메일로 발급하지 않는다.

새 비밀번호 정책 검사 후 사용자와 증명을 검증하고 변경한다. 증명은 한 번만 사용하며 검증 완료 후 5분 유효하다. 성공 시 모든 기존 JWT가 무효화되며 새 로그인 토큰은 반환하지 않는다.

오류: 400 EMAIL_INVALID / PASSWORD_INVALID / VERIFICATION_REQUIRED / VERIFICATION_TOKEN_INVALID, 404 USER_NOT_FOUND, 409 AUTH_METHOD_NOT_SUPPORTED, 410 VERIFICATION_EXPIRED 및 공통 오류이다.

## POST /api/auth/signup

회원가입.

```http
POST /api/auth/signup
```

| 항목 | 내용 |
|---|---|
| 인증 | 불필요 |
| Query | 없음 |
| 성공 | **201 Created** |
| 필수 Body | email, password, nickname, verificationToken |
| 선택 Body | allergies, diseases, specialDiet, dislikedIngredients |

### 요청 본문 필드

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| email | string | 예 | 인증한 이메일 |
| password | string | 예 | 공통 비밀번호 정책 적용 |
| nickname | string | 예 | 공통 닉네임 정책 적용 |
| verificationToken | string | 예 | signup 인증 완료 증명 |
| allergies | string/null | 아니오 | 쉼표 연결 알레르기 ID |
| diseases | string/null | 아니오 | 직접 입력한 질환 |
| specialDiet | string/null | 아니오 | 쉼표 연결 채식·영양조건 ID |
| dislikedIngredients | string/null | 아니오 | 기피 식재료 |

### 요청 예시

```json
{
  "email": "user@example.com",
  "password": "Samplepass1!",
  "nickname": "찍먹_user1",
  "verificationToken": "example-signup-verification-token",
  "allergies": "egg,wheat",
  "diseases": null,
  "specialDiet": "lactoOvoVegetarian,lowSugar,highProtein",
  "dislikedIngredients": null
}
```

### 성공 응답

```json
{"message":"회원가입 성공","data":{"userId":42}}
```

data.userId는 생성된 정수 ID이다. 가입 성공 응답에는 로그인 토큰이 없다. 이후 이메일 로그인 API를 호출한다. 일반 가입은 조건 미선택이어도 profileCompleted=true이다.

| HTTP | code | 상황 |
|---|---|---|
| 400 | EMAIL_INVALID / NICKNAME_INVALID / PASSWORD_INVALID | 입력 정책 위반. password 누락 기본값도 PASSWORD_INVALID로 검사 |
| 400 | VALIDATION_FAILED | 알레르기·식단 미지원, 채식 복수 선택 등 |
| 400 | VERIFICATION_REQUIRED | 빈 증명 또는 완료 내역 없음 |
| 400 | VERIFICATION_TOKEN_INVALID | 저장된 증명과 토큰 불일치 |
| 410 | VERIFICATION_EXPIRED | 가입 인증 완료 증명 30분 만료 |
| 409 | EMAIL_ALREADY_REGISTERED | 기존 이메일 |
| 409 | NICKNAME_ALREADY_EXISTS | 중복 닉네임 |

필수 verificationToken 필드 자체가 누락되면 INVALID_REQUEST_BODY이다. 실패 종류는 검증 순서에 따라 결정되므로 동일 요청에 여러 문제가 있으면 한 오류만 먼저 반환된다.

가입 성공 시 증명을 소비한다. 입력 오류로 가입 트랜잭션이 실패하면 유효한 증명을 보존하여 수정 후 재시도할 수 있다. 응답만 유실되었는데 서버에서 가입된 경우 재시도는 EMAIL_ALREADY_REGISTERED이며 로그인으로 진행한다.

조건 미선택 가입은 같은 요청에서 allergies/diseases/specialDiet/dislikedIngredients를 모두 null로 보내거나 생략한다.

증명은 이메일과 목적에 묶여 있다. 이메일을 바꾸거나 다른 용도의 증명을 사용하면 해당 이메일·목적의 완료 내역이 없어 `VERIFICATION_REQUIRED`가 될 수 있다. 모든 잘못된 증명 사용이 같은 오류 코드인 것은 아니다.

## POST /api/chat

AI 챗봇 중계.

```http
POST /api/chat
Authorization: Bearer {token}
Content-Type: application/json
```

| 항목 | 내용 |
|---|---|
| 기능 | 사용자·상품 데이터를 구성해 AI 서버 /chat로 전달 |
| 인증 | 서비스 JWT 필요 |
| Query | analysisMode, includeSelf, familyProfileIds. 상품 API와 같은 선택 규칙 |
| 성공 | 200 OK, 계약 확인된 AI JSON object |
| 배포 의존성 | chat.ai.url 및 chat-analysis-v1을 수용하는 AI 서버. [최신 계약](chat-analysis-contract-v1.md) 참조 |

### Body

| 필드 | 타입 | 필수·설명 |
|---|---|---|
| userId | integer/null | 호환용. 생략 권장, JWT 본인과 같아야 하며 관리자도 타인 지정 불가 |
| barcode | string/null | 선택 상품 바코드 |
| message | string | 필수 질문 |
| chatHistory | array | 생략 시 [] |
| chatHistory[].role | string | user 또는 assistant만 허용 |
| chatHistory[].content | string | 필수 대화 문자열 |

```json
{
  "userId": 42,
  "barcode": "8800000000001",
  "message": "이 상품의 표시 정보를 설명해줘",
  "chatHistory": []
}
```

### 현재 응답·제한

백엔드는 AI 응답의 계약 버전/contextId 확인 헤더와 JSON object 형식을 검증한 뒤 application/json으로 본문을 반환한다. answer 등 구체적인 성공 필드명은 AI 담당자와 합의한다. [요청 제한·전달 데이터·응답 확인·오류 명세](chat-analysis-contract-v1.md)가 이 요약보다 우선한다.

상품 바코드를 생략한 경우만 상품 없는 질문으로 전달한다. 지정 상품 없음은 404 PRODUCT_NOT_FOUND, 타인·삭제된 가족은 404 FAMILY_NOT_FOUND다. AI 연결 실패는 503, 계약 확인·응답 오류는 502이며 미인증은 401이다.

**연동 전 확인:** 본인·가족 검증과 공통 판정 전달은 로컬 구현했다. AI가 새 analysisContext와 확인 헤더를 지원하지 않으면 요청은 실패한다. 서버 간 공동 테스트 전에 운영에 단독 배포하지 않는다. LLM 문장 수준의 판정 일치 검증과 용량 옵션 집계 범위는 별도 계약이 필요하다.

## POST /api/histories/events

사용자 행동 기록.

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
    "createdAt": "2026-10-15T15:02:00"
  }
}
```

eventId는 Long, barcode/actionType은 string, createdAt은 LocalDateTime 문자열이다. OTHER는 구형 데이터 해석용이며 신규 요청에서 허용하지 않는다. 400 REQUEST_FAILED(바코드·행동 유형), 404 REQUEST_FAILED(사용자·상품 없음), 공통 401/500이 가능하다.

반복 전송은 별도 이력을 생성한다. 이 API는 행동 기록용이며 즐겨찾기 목록 상태를 생성·해제하는 CRUD API와 동일하지 않다. 별도 idempotency key나 즐겨찾기 취소 API는 현재 없다.

## GET /api/histories/user/{userId}

사용자 행동 및 스캔 이력 조회.

```http
GET /api/histories/user/{userId}
Authorization: Bearer {token}
```

로그인 본인 또는 관리자, userId 필수 Long, Query/Body 없음, 성공 200이다. 전체 이력을 최신순으로 반환하고 page·size는 없다. SCAN만 필터링하는 API가 아니며 기록된 여러 행동 유형을 함께 반환한다.

아래 product는 일부 필드 발췌이다. 전체 구조는 Product이다.

```json
{
  "message": "사용자 히스토리 조회 성공",
  "data": [{
    "id": 100,
    "actionType": "SCAN",
    "scannedAt": "2026-10-15T15:00:00",
    "product": {"barcode":"8800000000001","productName":"예시 과자"}
  }]
}
```

data[].id는 이력 ID(Long), actionType은 string, scannedAt은 LocalDateTime 문자열, product는 Product/null이다. 상품이 DB에서 없어졌으면 null일 수 있다. 이력이 없으면 data=[]이며 현재 서비스는 대상 사용자 존재를 별도로 검증하지 않는다. 공통 401, 403 REQUEST_FAILED(타인 이력 요청), 서버 500을 처리한다.

## GET /api/products/classifications

카테고리 및 알레르기 분류 조회.

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

## GET /api/products/filter

통합 조건 검색.

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
| filters | string 목록 | 선택 | [식단 및 영양 필터 종류 조회](#get-apiproductsfilters)의 key, 쉼표 또는 같은 파라미터 반복 |
| match | string | `all` | filters 내부 `all`=모두, `any`=하나 이상 |
| categories | string 목록 | 선택 | [카테고리 및 알레르기 분류 조회](#get-apiproductsclassifications) 카테고리 id |
| categoryMatch | string | `any` | categories 내부 all/any |
| containsAllergens | string 목록 | 선택 | [카테고리 및 알레르기 분류 조회](#get-apiproductsclassifications) 알레르기 id. **포함된 상품 검색** |
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

결과 없음 예시이다. 결과가 있으면 message는 `필터 검색 성공`이고 items의 원소는 [공통 상품 응답](#공통-상품-응답)의 `ProductAnalysis` 구조이다.

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

## GET /api/products/filters

식단 및 영양 필터 종류 조회.

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

## GET /api/products/safe-recommendations

맞춤 안심 상품 추천 및 카테고리별 보기.

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

아래는 상품 1개를 반환한 예시이다. **product 내부만 일부 필드를 발췌**했으며 실제 Product 전체 필드는 상품 명세 [공통 상품 응답](#공통-상품-응답)을 따른다. 나머지 응답 필드는 모두 표시한다.

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

SafeItem은 product(Product), safety(SafetyDecision), healthConstraints(DietConstraintDecision), preferences(DietConstraintDecision), dietConstraints(DietConstraintDecision), preferenceRelaxed(boolean, 항상 false), categoryIds(string[])를 가진다. dietConstraints는 전체 필수 조건이고 healthConstraints/preferences는 부분집합 판정이다. 판정 객체는 [추천 공통 판정 객체](#추천-공통-판정-객체)을 참고한다.

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

## GET /api/products/search

키워드 상품 검색.

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

키워드 길이 오류는 400과 message만 반환한다. 로그인/userId 관련 오류는 [통합 조건 검색](#get-apiproductsfilter)과 같다. 필수 keyword 자체 누락 시 동작은 공통 문서의 파라미터 바인딩 제한사항을 참고한다.

## GET /api/products/{barcode}

바코드 상품 조회.

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

## GET /api/products/{barcode}/variants

상품 전체 용량 옵션 조회.

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

설명용 축약 예시이다. `options[].data.product`와 `nutrientPercents`, `analysis`의 전체 필드는 [공통 상품 응답](#공통-상품-응답)과 동일하다. 용량별로 서로 다른 원본 행의 영양값을 혼합하거나 총중량 비율로 재계산하지 않는다.

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
| options[].data | ProductAnalysis | [공통 상품 응답](#공통-상품-응답)과 같은 구조. product/영양값은 대표 한 행, analysis는 용량별 합산 판정 |

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

## POST /api/recommendations/feedback

추천 피드백 기록.

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
    "createdAt": "2026-10-15T15:00:00"
  }
}
```

필드 타입은 요청과 같으며 createdAt은 LocalDateTime 문자열이다. 400 REQUEST_FAILED(형식·유형·순위), 404 REQUEST_FAILED(사용자·상품 없음), 409 REQUEST_FAILED(동일 추천 피드백 중복), 공통 401/500이 가능하다.

rankPosition 상한이 20이므로 최대 50개를 주는 첫 화면 추천의 21번째 이후 위치를 그대로 전송하면 400이다. 생략 또는 null은 허용한다. 이 피드백은 추천 평가 테이블에 저장되며 현재 취향 이력 학습용 `/api/histories/events`를 자동 생성하지 않는다.

현재 서버는 requestId의 UUID 형식, 사용자·상품 존재와 동일 피드백 중복을 검사한다. **requestId가 실제 발급된 추천 요청인지, 본인에게 발급된 것인지, 해당 상품이 그 응답에 있었는지는 검증하지 않는다.** 프론트는 실제 추천 응답의 ID·상품만 전송해야 하며 서버 측 소유권 검증은 별도 보완 항목이다. feedbackType은 앞뒤 공백 제거 후 대소문자를 구분하지 않고 허용 값을 판별한다.

## GET /api/recommendations/products/{barcode}

특정 상품의 대체 상품 추천.

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

로그인 필수, Body 없음, 성공 200이다. 이 API에는 categories·cursor·page 파라미터가 없다. 기준 상품에 사전 계산 추천 후보가 필요하다. Product 첫 화면 추천은 [맞춤 안심 상품 추천 및 카테고리별 보기](#get-apiproductssafe-recommendations)을 사용한다.

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

items가 1개라도 있으면 limit보다 적더라도 fallback으로 부족분을 채우지 않는다. UNKNOWN 대안은 items와 분리하고 DANGER·명시적인 식단 MISMATCH·기피 식재료 확인 상품은 대안에도 넣지 않는다. [맞춤 안심 상품 추천 및 카테고리별 보기](#get-apiproductssafe-recommendations)와 동일하게 specialDiet와 건강 조건을 필수로 적용한다. 홈은 UNKNOWN을 반환하지 않으며 대체 추천만 별도 경고 대안을 제공한다.

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

## GET /api/users

전체 사용자 조회.

```http
GET /api/users
Authorization: Bearer {관리자 token}
```

관리자만 가능, Query/Body 없음, 성공 200이다. 응답은 `{message: "전체 유저 목록 조회 성공", data: UserProfile[]}`이며 각 원소는 [내 프로필 조회](#get-apiusersme) 필드이다. 사용자 없음 예시는 다음과 같다.

```json
{"message":"전체 유저 목록 조회 성공","data":[]}
```

페이지네이션은 현재 없고 비밀번호는 포함하지 않는다. 일반 사용자는 403 ACCESS_DENIED이다.

## GET /api/users/me

내 프로필 조회.

```http
GET /api/users/me
Authorization: Bearer {token}
```

| 항목 | 내용 |
|---|---|
| 인증 | 필수 |
| 권한 | 로그인한 본인 |
| Query / Body | 없음 |
| 성공 | 200 OK |

```json
{
  "message": "내 프로필 조회 성공",
  "data": {
    "id": 42,
    "email": "user@example.com",
    "nickname": "찍먹_user1",
    "allergies": "egg,wheat",
    "diseases": null,
    "specialDiet": "lactoOvoVegetarian,lowSugar,highProtein",
    "dislikedIngredients": null,
    "role": "USER",
    "authProvider": "LOCAL",
    "profileCompleted": true
  }
}
```

로그인 응답의 userId와 달리 프로필 응답 키는 **id**이다.

| data 필드 | 타입 | 의미 |
|---|---|---|
| id | integer(Long) | 사용자 ID |
| email, nickname | string | 이메일·닉네임 |
| allergies, diseases, specialDiet, dislikedIngredients | string/null | 저장 조건. 배열이 아님 |
| role | string | USER / ADMIN |
| authProvider | string | LOCAL / GOOGLE / LOCAL_AND_GOOGLE |
| profileCompleted | boolean | 프로필 입력 완료 여부 |

비밀번호 해시·tokenVersion은 반환하지 않는다. 오류는 공통 401, 403 ACCESS_DENIED, 404 USER_NOT_FOUND이다. 삭제된 사용자의 오래된 토큰은 컨트롤러 이전 인증 단계에서 401 AUTH_TOKEN_INVALID가 될 수 있다.

## PUT /api/users/me

내 프로필 전체 수정.

```http
PUT /api/users/me
Authorization: Bearer {token}
```

로그인 필수, 로그인한 본인만 수정한다. Path/Query 없음, 성공 200이다.



### 요청 본문 필드

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| nickname | string | 예 | 공통 닉네임 정책 적용 |
| allergies | string/null | 아니오 | 26개 영문 ID의 쉼표 연결 문자열 |
| diseases | string/null | 아니오 | 사용자가 직접 입력한 질환 |
| specialDiet | string/null | 아니오 | 채식 1종 이하와 영양조건 복수 ID |
| dislikedIngredients | string/null | 아니오 | 기피 식재료 |

선택 필드는 누락해도 기존 값을 유지하지 않으며 해제된다.

### 요청 예시

```json
{
  "nickname": "찍먹_user2",
  "allergies": "egg,wheat",
  "diseases": null,
  "specialDiet": "lactoOvoVegetarian,lowSugar,highProtein",
  "dislikedIngredients": "고수"
}
```

nickname만 필수이고 선택 4개 필드는 생략 가능하지만, **생략·null·빈 문자열은 기존 값을 해제**한다. 변경하지 않은 선택값을 유지하려면 조회한 값을 함께 전송한다. email·role·authProvider·사진은 수정 필드가 아니다.

### 성공 응답

```json
{
  "message": "프로필 수정 성공",
  "data": {
    "id": 42,
    "email": "user@example.com",
    "nickname": "찍먹_user2",
    "allergies": "egg,wheat",
    "diseases": null,
    "specialDiet": "lactoOvoVegetarian,lowSugar,highProtein",
    "dislikedIngredients": "고수",
    "role": "USER",
    "authProvider": "LOCAL",
    "profileCompleted": true
  }
}
```

응답은 최신 프로필이다. PUT/PATCH는 profileCompleted를 바꾸지 않으며 최종 완료 API를 별도로 호출한다. 모든 조건 해제 요청은 다음과 같다.

```json
{"nickname":"찍먹_user2","allergies":null,"diseases":null,"specialDiet":null,"dislikedIngredients":null}
```

오류: 400 NICKNAME_INVALID / VALIDATION_FAILED / INVALID_REQUEST_BODY, 401 인증 오류, 403 ACCESS_DENIED, 404 USER_NOT_FOUND, 409 NICKNAME_ALREADY_EXISTS이다. diseases/dislikedIngredients의 일부 검증 오류에는 field가 없을 수 있다. PATCH 부분 수정은 v2 명세를 따른다.

## GET /api/users/{userId}

사용자 ID로 프로필 조회.

```http
GET /api/users/{userId}
Authorization: Bearer {token}
```

| 항목 | 내용 |
|---|---|
| 인증 | 필수 |
| 권한 | 본인 또는 관리자 |
| Path | userId: integer(Long), 필수 |
| Query / Body | 없음 |
| 성공 | 200 OK |

```json
{
  "message": "조회 성공",
  "data": {
    "id": 42,
    "email": "user@example.com",
    "nickname": "찍먹_user1",
    "allergies": "egg,wheat",
    "diseases": null,
    "specialDiet": "lactoOvoVegetarian,lowSugar,highProtein",
    "dislikedIngredients": null,
    "role": "USER",
    "authProvider": "LOCAL",
    "profileCompleted": true
  }
}
```

로그인 응답의 userId와 달리 프로필 응답 키는 **id**이다.

| data 필드 | 타입 | 의미 |
|---|---|---|
| id | integer(Long) | 사용자 ID |
| email, nickname | string | 이메일·닉네임 |
| allergies, diseases, specialDiet, dislikedIngredients | string/null | 저장 조건. 배열이 아님 |
| role | string | USER / ADMIN |
| authProvider | string | LOCAL / GOOGLE / LOCAL_AND_GOOGLE |
| profileCompleted | boolean | 프로필 입력 완료 여부 |

비밀번호 해시·tokenVersion은 반환하지 않는다. 오류는 공통 401, 403 ACCESS_DENIED, 404 USER_NOT_FOUND이다. 삭제된 사용자의 오래된 토큰은 컨트롤러 이전 인증 단계에서 401 AUTH_TOKEN_INVALID가 될 수 있다.

## PUT /api/users/{id}

사용자 ID로 프로필 전체 수정.

```http
PUT /api/users/{id}
Authorization: Bearer {token}
```

로그인 본인 또는 관리자만 수정한다. Path의 id는 필수 integer(Long)이다. Query 없음, 성공 200이다.



### 요청 본문 필드

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| nickname | string | 예 | 공통 닉네임 정책 적용 |
| allergies | string/null | 아니오 | 26개 영문 ID의 쉼표 연결 문자열 |
| diseases | string/null | 아니오 | 사용자가 직접 입력한 질환 |
| specialDiet | string/null | 아니오 | 채식 1종 이하와 영양조건 복수 ID |
| dislikedIngredients | string/null | 아니오 | 기피 식재료 |

선택 필드는 누락해도 기존 값을 유지하지 않으며 해제된다.

### 요청 예시

```json
{
  "nickname": "찍먹_user2",
  "allergies": "egg,wheat",
  "diseases": null,
  "specialDiet": "lactoOvoVegetarian,lowSugar,highProtein",
  "dislikedIngredients": "고수"
}
```

nickname만 필수이고 선택 4개 필드는 생략 가능하지만, **생략·null·빈 문자열은 기존 값을 해제**한다. 변경하지 않은 선택값을 유지하려면 조회한 값을 함께 전송한다. email·role·authProvider·사진은 수정 필드가 아니다.

### 성공 응답

```json
{
  "message": "프로필 수정 성공",
  "data": {
    "id": 42,
    "email": "user@example.com",
    "nickname": "찍먹_user2",
    "allergies": "egg,wheat",
    "diseases": null,
    "specialDiet": "lactoOvoVegetarian,lowSugar,highProtein",
    "dislikedIngredients": "고수",
    "role": "USER",
    "authProvider": "LOCAL",
    "profileCompleted": true
  }
}
```

응답은 최신 프로필이다. PUT/PATCH는 profileCompleted를 바꾸지 않으며 최종 완료 API를 별도로 호출한다. 모든 조건 해제 요청은 다음과 같다.

```json
{"nickname":"찍먹_user2","allergies":null,"diseases":null,"specialDiet":null,"dislikedIngredients":null}
```

오류: 400 NICKNAME_INVALID / VALIDATION_FAILED / INVALID_REQUEST_BODY, 401 인증 오류, 403 ACCESS_DENIED, 404 USER_NOT_FOUND, 409 NICKNAME_ALREADY_EXISTS이다. diseases/dislikedIngredients의 일부 검증 오류에는 field가 없을 수 있다. PATCH 부분 수정은 v2 명세를 따른다.

## DELETE /api/users/{id}

회원 탈퇴.

```http
DELETE /api/users/{id}
Authorization: Bearer {token}
```

로그인 본인 또는 관리자, id 필수 Long, Query/Body 없음, 성공 200이다.

```json
{"message":"회원 탈퇴 성공","data":null}
```

계정·행동 이력·추천 피드백을 삭제하고 추천 로그의 사용자 연결을 제거한다. 로컬 사진·가족 데이터를 서버가 삭제하지 않으므로 앱이 계정별 로컬 데이터를 별도로 처리한다. 403 ACCESS_DENIED, 404 USER_NOT_FOUND 및 공통 401/500을 처리한다.

## PUT /api/users/{id}/password

로그인 상태에서 비밀번호 변경.

```http
PUT /api/users/{id}/password
Authorization: Bearer {token}
```

id는 필수 Long, Query 없음, 로그인 본인만 가능하며 관리자도 타인의 비밀번호를 이 API로 변경할 수 없다. currentPassword·newPassword는 필수 string이다.

```json
{"currentPassword":"Samplepass1!","newPassword":"Newpassword2!"}
```

```json
{"message":"비밀번호가 성공적으로 변경되었습니다.","data":null}
```

성공 200. 현재 비밀번호 불일치는 400 LOGIN_FAILED(field=currentPassword), 새 비밀번호 정책 위반은 400 PASSWORD_INVALID(field=password)이다. field가 newPassword로 내려오지 않는 현재 구현을 프론트 매핑에 반영한다. 409 AUTH_METHOD_NOT_SUPPORTED, 403 ACCESS_DENIED, 404 USER_NOT_FOUND 및 공통 오류도 가능하다.

성공하면 현재 기기를 포함한 모든 기존 JWT가 무효화된다. 프론트는 토큰 삭제 후 로그인으로 이동한다.

## 공통 상품 응답

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

### nutrientPercents

| 필드 | 타입 | 의미 |
|---|---|---|
| energyPercent, carbsPercent, proteinPercent, fatPercent, sugarPercent, sodiumPercent, cholesterolPercent | integer | 현재 코드의 기준량 대비 반올림한 비율 |
| carbsMacroPercent, proteinMacroPercent, fatMacroPercent | number | 저장된 탄단지 비율. 결측이면 0 |


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

### 이미지 응답 범위

이 버전의 Product에는 `imageUrl`만 있다. 실제 상품 대표 사진과 카테고리 참고 사진을 구분하는 `imageRole`·`imageDisplayNotice` 등의 응답 필드는 아직 없다. Firebase 이미지 업로드 결과나 운영 DB 반영이 이 API 버전에 자동 포함되는 것은 아니다.

## 추천 공통 판정 객체

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

## 미구현 경로와 연동 주의사항

현재 Spring Backend에는 다음 경로가 구현되어 있지 않다.

- 이메일 인증 완료 증명의 남은 시간을 별도로 조회하는 API
- `GET /api/products/filter`의 알레르기 제외 파라미터, 알레르기 분류 상태 파라미터
- Spring 서버의 `/health`, `/ocr`, `/products/barcode/{barcode}`, `/products/report-number/{report_number}`

마지막 묶음은 별도 AI/OCR 서비스에서 제공할 수 있으므로 담당 서비스의 실제 코드·배포 주소로 명세를 관리한다. Spring의 `/api/products/{barcode}`나 `/api/chat`과 경로를 혼용하지 않는다.

### 프론트 연동 시 확인할 현재 차이

| 항목 | 실제 상태·반영할 설명 |
|---|---|
| 성공 응답 래핑 | 로그인·Google은 최상위 token/userId, 상품·프로필 등은 data 사용, 챗봇은 AI 응답 직접 반환 |
| 본인 ID 키 | 로그인은 userId, 프로필은 id |
| 오류 구조 | 상품 직접 검증 오류에는 code가 없을 수 있음. 일반 업무 오류에는 REQUEST_FAILED 사용 |
| 숫자 Query/Path 타입 오류 | 전용 핸들러 미구현으로 500이 될 수 있음. 정상적인 400 계약으로 확정하지 않음 |
| 프로필 PATCH | v2에서 추가. 생략 유지, 선택 필드 null/빈 문자열 해제. PUT은 전체 교체 |
| 비밀번호 변경 field | 새 비밀번호 검증 오류에도 field=password가 사용됨 |
| 인증시간 | Access/Refresh는 Instant, OTP 응답은 offset 포함, 행동 이력은 기존 LocalDateTime |
| 첫 화면 추천 | PASS·건강·specialDiet 필수 조건 유지, 완화 없음, 제한된 후보 탐색 |
| 대체 추천 | UNKNOWN 대안은 fallbackItems로 분리. 사전 후보 자체가 없으면 404 |
| 알레르기 미검출 | 상품 분류 상태이며 사용자 안전성 PASS와 다름 |
| 알레르기 미등록 | 현재 개인 판정 PASS가 될 수 있지만 모든 사용자에 대한 안전 증명이 아님 |
| 결측 영양 비율 | 현재 percent=0일 수 있으므로 원 영양 필드 null 확인 |
| 이력 기록 | 단건 상품 GET도 로그인 시 SCAN 이력을 추가함 |
| 추천 피드백과 행동 이력 | 다른 저장·사용 목적. 피드백이 행동 이력을 자동 생성하지 않음 |
| 추천 피드백 검증 | UUID 형식과 상품 존재는 확인하지만 추천 요청의 소유권·실제 노출 여부는 검증하지 않음 |
| 이미지 종류 표시 | 이 버전에는 imageUrl만 있으며 상품 대표 사진·카테고리 참고 사진 구분 필드가 없음 |
| 실서버 반영 | 이 문서는 코드 기준. 서버 담당자는 배포 커밋·Flyway·DB·메일·Google 설정을 별도로 확인 |

챗봇 본인 식별, 추천 피드백 소유권 검증, 파라미터 오류 응답 통일은 구현 보완이 필요하다. 문서에 기재한 것으로 해당 동작이 수정되는 것은 아니다.

## 구현 기준

아래 소스의 Controller, DTO, Service, 인증 필터와 예외 처리에 맞춘 명세이다. 운영 서버 설정이나 별도 AI 서비스 응답을 확정하는 문서는 아니다.

| 영역 | 기준 소스 |
|---|---|
| 인증 | [AuthController.kt](https://github.com/KW-coworker/JJIKMUK-Backend/blob/87184c4dae5b541e32c86bd04a8561a4dbd5810a/src/main/kotlin/org/jjikmuk/backend/domain/auth/AuthController.kt) |
| 사용자 | [UserController.kt](https://github.com/KW-coworker/JJIKMUK-Backend/blob/87184c4dae5b541e32c86bd04a8561a4dbd5810a/src/main/kotlin/org/jjikmuk/backend/domain/user/UserController.kt) |
| 상품 및 용량 옵션 | [ProductController.kt](https://github.com/KW-coworker/JJIKMUK-Backend/blob/87184c4dae5b541e32c86bd04a8561a4dbd5810a/src/main/kotlin/org/jjikmuk/backend/domain/product/ProductController.kt) |
| 첫 화면 추천 | [SafeProductRecommendationController.kt](https://github.com/KW-coworker/JJIKMUK-Backend/blob/87184c4dae5b541e32c86bd04a8561a4dbd5810a/src/main/kotlin/org/jjikmuk/backend/domain/recommendation/SafeProductRecommendationController.kt) |
| 대체 추천 및 피드백 | [RecommendationController.kt](https://github.com/KW-coworker/JJIKMUK-Backend/blob/87184c4dae5b541e32c86bd04a8561a4dbd5810a/src/main/kotlin/org/jjikmuk/backend/domain/recommendation/RecommendationController.kt) |
| 사용자 행동 | [HistoryController.kt](https://github.com/KW-coworker/JJIKMUK-Backend/blob/87184c4dae5b541e32c86bd04a8561a4dbd5810a/src/main/kotlin/org/jjikmuk/backend/domain/history/HistoryController.kt) |
| 챗봇 | [ChatController.kt](https://github.com/KW-coworker/JJIKMUK-Backend/blob/87184c4dae5b541e32c86bd04a8561a4dbd5810a/src/main/kotlin/org/jjikmuk/backend/domain/chat/ChatController.kt) |
