# 회원가입·인증·사용자 프로필 API 명세

2026-10-23 변경 상세는 [프론트 연동 v2](frontend-auth-integration-v2.md)에 있다. 사진·가족·Refresh·Google 연결·PATCH·최종 완료 API는 해당 문서를 함께 확인한다.

[공통 규칙과 전체 목록](README.md). 모든 요청·응답은 별도 표시가 없으면 JSON이다. 로그인 응답은 data로 감싸지 않으며 다른 API의 응답 형태와 구분한다.

## A00. 공통 입력 규칙

| 값 | 계약 |
|---|---|
| email | 필수 string. NFKC 정규화, 앞뒤 공백 제거, 소문자 변환, 이메일 형식·최대 254자 검사 |
| nickname | 필수 string. NFKC·trim 후 2~20자, 완성형 한글·영문·숫자·밑줄 허용. 중복은 대소문자 구분 없이 검사 |
| password / newPassword | 8자 이상, UTF-8 72바이트 이하, 영문과 숫자 각각 포함. ASCII 출력 가능 특수문자 선택 허용, 공백·한글·기타 Unicode 불가. trim하지 않음. 허용 범위는 v2의 추가 합의 항목 참고 |
| allergies | 선택 string/null. 26개 영문 ID를 쉼표로 연결. 예: `egg,wheat` |
| specialDiet | 선택 string/null. 채식 최대 1종 + 영양조건 복수 선택. 예: `lactoOvoVegetarian,lowSugar,highProtein` |
| diseases | 선택 string/null. 실제 입력한 질환 목록. 저당 선호를 임의로 당뇨로 변환하지 않음 |
| dislikedIngredients | 선택 string/null. 예: `고수,오이` |

- allergies·specialDiet는 배열이 아닌 문자열이다. UI 표시 이름·아이콘·상위 메뉴 `Allergy`, `Vegetarian`을 전송하지 않는다.
- 현재 선택지는 [상품 명세 P01/P02](products.md)와 동일하다. 할랄은 허용 필터가 아니다.
- 선택 없음·전체 해제는 `null` 또는 `""`을 사용한다. `"없음"`은 공통 해제 값이 아니다. 알레르기·식단에서 미지원 값이면 400이다.
- 호환용 한글 별칭을 받더라도 새 쓰기는 정규 영문 ID로 저장한다. 구형 저장 데이터 조회에는 원 문자열이 남아 있을 수 있다.
- diseases·dislikedIngredients는 항목 최대 50개, 각 100자, 정규화 저장 문자열 최대 1000자이다. 쉼표·세미콜론·슬래시·파이프·줄바꿈을 구분자로 받으며 새 요청은 쉼표 사용을 권장한다.
- 프로필 사진은 별도 `/api/users/me/photo` API로 저장하며 프로필 조회에 인증용 상대 photoUrl을 반환한다.

## A01. 이메일 인증번호 발송·재전송

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
    "expiresAt": "2026-10-08T15:05:00",
    "expiresInSeconds": 300,
    "resendAvailableAt": "2026-10-08T15:01:00"
  }
}
```

data.email/purpose는 정규화 문자열, 두 At 필드는 시간대 없는 서버 시각 문자열, expiresInSeconds는 정수(초)이다. OTP 자체는 응답에 포함하지 않는다.

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

재전송 대기 429에 retryAfterSeconds와 Retry-After 헤더를 제공한다. OTP 오입력에는 remainingAttempts를 제공한다. 이메일 응답의 expiresAt/resendAvailableAt은 시간대 offset을 포함한다.

## A02. 이메일 인증번호 검증

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
    "expiresAt": "2026-10-08T15:31:00",
    "expiresInSeconds": 1800
  }
}
```

| data 필드 | 타입 | 의미 |
|---|---|---|
| email, purpose | string | 인증한 이메일과 목적 |
| verificationToken | string | 이후 가입 또는 재설정에 쓰는 일회용 증명. 로그인 토큰이 아님 |
| expiresAt | string(LocalDateTime) | 인증 완료 증명의 만료 시각 |
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

가입용 증명을 받은 뒤 expiresInSeconds로 타이머를 관리한다. 30분이 지났다는 안내를 띄우기 위한 별도 API는 없다. 최종 가입 시 서버가 만료를 판단하면 `410 VERIFICATION_EXPIRED`를 반환한다. 사용자가 재인증을 선택하면 A01을 purpose=signup으로 호출하고 A02를 다시 거친다. purpose=password_reset의 증명은 30분이 아니라 5분이다.

## A03. 회원가입

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

### 요청

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

증명은 이메일과 목적에 묶여 있다. 다른 이메일·목적으로 사용하여 해당 완료 내역을 찾지 못하면 VERIFICATION_REQUIRED가 될 수 있다.

가입 성공 시 증명을 소비한다. 입력 오류로 가입 트랜잭션이 실패하면 유효한 증명을 보존하여 수정 후 재시도할 수 있다. 응답만 유실되었는데 서버에서 가입된 경우 재시도는 EMAIL_ALREADY_REGISTERED이며 로그인으로 진행한다.

조건 미선택 가입은 같은 요청에서 allergies/diseases/specialDiet/dislikedIngredients를 모두 null로 보내거나 생략한다.

## A04. 이메일 로그인

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
  "expiresAt": "2026-10-09T06:00:00Z",
  "expiresInSeconds": 900,
  "isNewUser": false,
  "profileCompleted": true,
  "refreshToken": "example-refresh-token",
  "refreshExpiresAt": "2026-11-08T06:00:00Z",
  "authProvider": "LOCAL",
  "hasPassword": true
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
| isNewUser | boolean | 이메일 로그인에서는 false |
| profileCompleted | boolean | 추가 프로필 입력 완료 여부 |
| refreshToken | string | 회전되는 불투명 갱신 토큰 |
| refreshExpiresAt | string(Instant) | 최초 로그인부터 고정된 갱신 만료 시각 |
| authProvider / hasPassword | string / boolean | LOCAL, GOOGLE, LOCAL_AND_GOOGLE 및 비밀번호 지원 여부 |

400 INVALID_REQUEST_BODY, 401 LOGIN_FAILED(미가입·비밀번호 불일치·잘못된 이메일), 409 AUTH_METHOD_NOT_SUPPORTED(Google 전용 계정) 등이 가능하다. 로그인 password는 과거 계정 호환을 위해 신규 가입 규칙으로 다시 검사하지 않고 저장 해시와 비교한다.

## A05. Google 로그인·자동 가입

```http
POST /api/auth/google
```

인증 불필요, Query 없음, 성공 200이다.

```json
{"idToken":"example-google-id-token"}
```

응답 필드는 A04와 동일하며 message는 `구글 로그인 성공`이다. 새 계정 예시는 다음과 같다.

```json
{
  "message": "구글 로그인 성공",
  "token": "example-service-jwt",
  "tokenType": "Bearer",
  "userId": 43,
  "email": "google-user@example.com",
  "expiresAt": "2026-10-09T06:00:00Z",
  "expiresInSeconds": 900,
  "isNewUser": true,
  "profileCompleted": false,
  "refreshToken": "example-refresh-token",
  "refreshExpiresAt": "2026-11-08T06:00:00Z",
  "authProvider": "GOOGLE",
  "hasPassword": false
}
```

- 서버는 GOOGLE_CLIENT_ID/aud, email_verified, issuer, 만료, subject를 확인한다.
- 신규 사용자는 임시 닉네임으로 자동 가입한다. PATCH/PUT은 profileCompleted를 바꾸지 않고 `/api/users/me/profile/complete` 최종 제출만 true로 만든다.
- 기존 일반 가입 이메일과 같으면 GOOGLE_LINK_REQUIRED와 임시 증명을 반환한다. 비밀번호 소유 확인을 거치는 `/api/auth/google/link` 성공 전에는 계정 연결이나 서비스 로그인 토큰 발급이 없다. 상세는 v2 문서를 따른다.
- 최초 가입 후 다시 로그인한 미완료 사용자는 isNewUser=false이고 profileCompleted=false일 수 있다. 화면 이동은 profileCompleted로 판단한다.
- Google 전용 계정의 일반 비밀번호 로그인·찾기·변경은 지원하지 않는다. 두 방식이 연결된 계정은 기존 비밀번호 로그인이 가능하다.

401 GOOGLE_TOKEN_INVALID(검증 실패), 503 GOOGLE_LOGIN_UNAVAILABLE(Client ID 미설정 또는 Google 인증 서비스 연결 장애), 공통 400/500 등이 가능하다.

## A06. 비밀번호 재설정

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

절차는 A01(password_reset) → A02(password_reset) → 이 API이다. code를 이 API에 직접 보내는 이전 계약은 사용하지 않는다. 임시 비밀번호를 이메일로 발급하지 않는다.

새 비밀번호 정책 검사 후 사용자와 증명을 검증하고 변경한다. 증명은 한 번만 사용하며 검증 완료 후 5분 유효하다. 성공 시 모든 기존 JWT가 무효화되며 새 로그인 토큰은 반환하지 않는다.

오류: 400 EMAIL_INVALID / PASSWORD_INVALID / VERIFICATION_REQUIRED / VERIFICATION_TOKEN_INVALID, 404 USER_NOT_FOUND, 409 AUTH_METHOD_NOT_SUPPORTED, 410 VERIFICATION_EXPIRED 및 공통 오류이다.

## A07. 닉네임 사용 가능 여부 조회

```http
GET /api/auth/nicknames/availability?nickname=찍먹_user1
```

인증 불필요, nickname 필수 string, Body 없음, 성공 200이다.

```json
{
  "message": "닉네임 사용 가능 여부 조회 성공",
  "data": {"nickname":"찍먹_user1","available":true}
}
```

data.nickname은 정규화된 이름이고 available은 boolean이다. 이미 사용 중이면 409가 아니라 200과 available=false이다. 형식이 잘못되면 400 NICKNAME_INVALID이다. 닉네임을 예약하지 않으므로 최종 가입/수정에서도 중복을 다시 검사한다. 현재 본인이 사용 중인 닉네임을 이 공개 API로 확인하면 available=false가 될 수 있지만, 본인 프로필을 동일 닉네임으로 저장하는 것은 가능하다.

## A08. 로그아웃

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

현재 기기 서버 세션과 Access/Refresh를 폐기한다. 앱도 저장 토큰을 삭제한다. 구형 sid 없는 JWT는 모든 세션을 폐기한다. 실패해도 로컬 로그아웃은 가능하지만 서버 폐기 완료로 단정하지 않는다. 만료 Access는 갱신 후 로그아웃해야 한다.

## U01. 내 프로필 조회 / 기존 ID 조회

```http
GET /api/users/me
GET /api/users/{userId}
Authorization: Bearer {token}
```

| 항목 | 내용 |
|---|---|
| 인증 | 필수 |
| 권한 | /me는 본인, /{userId}는 본인 또는 관리자 |
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

기존 ID 조회의 message는 `조회 성공`이다. 로그인 응답의 userId와 달리 프로필 응답 키는 **id**이다.

| data 필드 | 타입 | 의미 |
|---|---|---|
| id | integer(Long) | 사용자 ID |
| email, nickname | string | 이메일·닉네임 |
| allergies, diseases, specialDiet, dislikedIngredients | string/null | 저장 조건. 배열이 아님 |
| role | string | USER / ADMIN |
| authProvider | string | LOCAL / GOOGLE / LOCAL_AND_GOOGLE |
| profileCompleted | boolean | 프로필 입력 완료 여부 |

비밀번호 해시·tokenVersion은 반환하지 않는다. 오류는 공통 401, 403 ACCESS_DENIED, 404 USER_NOT_FOUND이다. 삭제된 사용자의 오래된 토큰은 컨트롤러 이전 인증 단계에서 401 AUTH_TOKEN_INVALID가 될 수 있다.

## U02. 내 프로필 전체 수정 / 기존 ID 수정

```http
PUT /api/users/me
PUT /api/users/{id}
Authorization: Bearer {token}
```

로그인 필수, /me는 본인, /{id}는 본인·관리자, Query 없음, 성공 200이다.

### 요청

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

응답 data는 U01 전체 프로필에 hasPassword와 photoUrl을 추가한 모델이다. PUT/PATCH는 profileCompleted를 바꾸지 않는다. 모든 조건 해제 요청은 다음과 같다.

```json
{"nickname":"찍먹_user2","allergies":null,"diseases":null,"specialDiet":null,"dislikedIngredients":null}
```

오류: 400 NICKNAME_INVALID / VALIDATION_FAILED / INVALID_REQUEST_BODY, 401 인증 오류, 403 ACCESS_DENIED, 404 USER_NOT_FOUND, 409 NICKNAME_ALREADY_EXISTS이다. diseases/dislikedIngredients의 일부 검증 오류에는 field가 없을 수 있다. PATCH는 v2에서 추가했으며 생략 필드를 보존한다.

## U03. 로그인 상태에서 비밀번호 변경

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

## U04. 회원 탈퇴

```http
DELETE /api/users/{id}
Authorization: Bearer {token}
```

로그인 본인 또는 관리자, id 필수 Long, Query/Body 없음, 성공 200이다.

```json
{"message":"회원 탈퇴 성공","data":null}
```

계정·행동 이력·추천 피드백·서버 세션·Refresh·연결 증명·서버 사진·서버 가족을 삭제하고 추천 로그의 사용자 연결을 제거한다. 남아 있는 구형 로컬 캐시는 앱이 계정별로 처리한다. 403 ACCESS_DENIED, 404 USER_NOT_FOUND 및 공통 401/500을 처리한다.

## U05. 전체 사용자 조회(관리자)

```http
GET /api/users
Authorization: Bearer {관리자 token}
```

관리자만 가능, Query/Body 없음, 성공 200이다. 응답은 `{message: "전체 유저 목록 조회 성공", data: UserProfile[]}`이며 각 원소는 U01 필드이다. 사용자 없음 예시는 다음과 같다.

```json
{"message":"전체 유저 목록 조회 성공","data":[]}
```

페이지네이션은 현재 없고 비밀번호는 포함하지 않는다. 일반 사용자는 403 ACCESS_DENIED이다.
