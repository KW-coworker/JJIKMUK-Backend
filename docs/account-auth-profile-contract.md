# 계정·인증·프로필 계약(A06~A13)

## A06. 닉네임·이메일·비밀번호 검증

### 닉네임

- 닉네임은 고유하며 대소문자를 구분하지 않는다.
- NFKC 정규화와 앞뒤 공백 제거 후 2~20자로 검사한다.
- 한글, 영문, 숫자, 밑줄만 허용한다. 내부 공백과 이모지는 허용하지 않는다.
- 사전 확인은 안내 기능일 뿐 닉네임을 예약하지 않는다. 최종 `/signup`과 프로필 수정에서 다시 검사한다.

```http
GET /api/auth/nicknames/availability?nickname=찍먹_user1
```

```json
{
  "message": "닉네임 사용 가능 여부 조회 성공",
  "data": {
    "nickname": "찍먹_user1",
    "available": true
  }
}
```

사용자가 닉네임을 수정하면 프론트의 사전 확인 완료 상태를 즉시 초기화한다.

### 이메일

- NFKC 정규화, 앞뒤 공백 제거, 소문자 변환 후 저장·비교한다.
- 최대 254자이며 일반적인 `local@domain.tld` 형태를 검사한다.
- 동일 이메일은 대소문자와 앞뒤 공백이 달라도 중복이다.

### 비밀번호

- 8자 이상이어야 한다.
- BCrypt 안전 한계에 맞춰 UTF-8 기준 최대 72바이트다.
- 문자 1개와 숫자 1개 이상을 포함해야 한다.
- 공백은 허용하지 않는다.
- 비밀번호 확인값은 프론트에서만 비교하며 서버 요청에는 보내지 않는다.

회원가입 성공은 `201 Created`, 닉네임·이메일 최종 중복은 `409 Conflict`다.

## A07. 프로필 사진

이번 백엔드 범위에 포함하지 않는다. 합의대로 기기 로컬 DB에서 관리한다. 계정별 로컬 사진을 구분하려면 A08의 `userId`를 소유자 키로 저장한다.

## A08. 로그인 후 본인 ID

이메일 로그인과 Google 로그인은 같은 응답 구조를 사용한다.

```json
{
  "message": "로그인 성공",
  "token": "service-access-jwt",
  "tokenType": "Bearer",
  "userId": 17,
  "email": "user@example.com",
  "expiresAt": "2026-10-02T12:00:00Z",
  "expiresInSeconds": 86400,
  "isNewUser": false,
  "profileCompleted": true
}
```

JWT의 `sub`에도 사용자 ID가 있지만 앱은 로그인 응답의 `userId`를 사용한다. JWT 디코딩 결과는 서버 권한 검증을 대체하지 않는다.

토큰으로 본인 프로필을 조회할 수도 있다.

```http
GET /api/users/me
Authorization: Bearer {token}
```

상품 조회·검색 API에서는 로그인했다면 `userId`를 생략한다. 서버가 JWT의 사용자 ID를 사용해 개인화한다. 다른 사용자 ID 지정은 관리자만 허용한다.

## A09. 로그인 유지·만료·로그아웃

- 액세스 JWT 유효시간은 24시간이다.
- 이번 범위에는 Refresh Token과 갱신 API를 추가하지 않는다.
- 만료 후에는 다시 로그인한다.
- 앱 시작 시 저장된 토큰으로 `GET /api/users/me`를 호출한다.
- 성공하면 홈으로 이동하고, `AUTH_TOKEN_EXPIRED` 또는 `AUTH_TOKEN_INVALID`이면 토큰을 삭제하고 로그인 화면으로 이동한다.
- 네트워크 실패는 세션 만료로 처리하지 않고 입력·토큰을 유지한 채 재시도한다.

```http
POST /api/auth/logout
Authorization: Bearer {token}
```

로그아웃은 기기의 토큰 삭제 방식이다. 응답의 `serverTokenRevoked`는 `false`이며, 서버 JWT는 원래 만료시각까지 암호학적으로는 유효하다.

비밀번호 변경과 비밀번호 재설정은 사용자의 `tokenVersion`을 증가시켜 해당 계정의 기존 JWT를 모두 즉시 무효화한다. 다음 요청부터 `401 AUTH_TOKEN_INVALID`가 반환된다.

| 상황 | HTTP | 오류 코드 |
|---|---:|---|
| 토큰 없음 | 401 | `AUTHENTICATION_REQUIRED` |
| 토큰 만료 | 401 | `AUTH_TOKEN_EXPIRED` |
| 변조·구형·무효화 토큰 | 401 | `AUTH_TOKEN_INVALID` |
| 로그인했지만 권한 부족 | 403 | `ACCESS_DENIED` |

## A10. Google 로그인

- 이번 백엔드 범위에 Google 로그인을 포함한다.
- Android가 전달한 Google `idToken`을 Google tokeninfo endpoint로 검증한다.
- 서버의 `GOOGLE_CLIENT_ID`와 토큰의 `aud`가 일치하고 `email_verified=true`여야 한다.
- 서버가 반환하는 `token`은 Google 토큰이 아니라 찍먹 서비스 JWT다.

신규 Google 사용자는:

- `isNewUser=true`
- `profileCompleted=false`
- 임시 고유 닉네임 자동 생성
- 앱에서 추가 프로필 입력 화면으로 이동

추가 입력은 `PUT /api/users/me`를 사용한다. 수정 성공 시 `profileCompleted=true`가 된다. 알레르기·식이조건 미선택은 정상 완료이므로 완료 판단은 이 필드가 아니라 `profileCompleted`를 사용한다.

일반 가입과 같은 검증된 Google 이메일이면 기존 계정에 Google 로그인 방식을 연결하고 별도 계정을 만들지 않는다. Google 전용 계정은 이메일·비밀번호 로그인, 비밀번호 찾기·변경을 사용할 수 없다. 연결된 `LOCAL_AND_GOOGLE` 계정은 두 방식을 모두 사용할 수 있다.

배포 환경에는 다음 값을 별도로 설정한다.

```text
GOOGLE_CLIENT_ID={서버가 허용할 Web OAuth Client ID}
```

Android 패키지명과 서명 SHA 등록은 Google Cloud/Firebase 설정에서 별도로 맞춘다.

## A11. 프로필 조회·수정

본인용 API:

```http
GET /api/users/me
PUT /api/users/me
```

기존 ID API도 유지한다.

```http
GET /api/users/{id}
PUT /api/users/{id}
```

일반 사용자는 본인만, 관리자는 다른 사용자를 조회·수정할 수 있다. 전체 사용자 조회는 관리자만 가능하다.

수정 가능한 필드:

- `nickname`
- `allergies`
- `diseases`
- `specialDiet`
- `dislikedIngredients`

`PUT`은 전체 교체다. `nickname`은 필수이고 선택 필드는 `null`로 보내면 해제된다. `""`도 선택 필드에서는 `null`로 정규화한다. 이메일·역할·인증 방식은 이 API로 변경할 수 없다.

응답은 전용 `UserProfileResponse`를 사용하며 다음 값만 포함한다.

```json
{
  "id": 17,
  "email": "user@example.com",
  "nickname": "찍먹_user1",
  "allergies": "egg,wheat",
  "diseases": null,
  "specialDiet": "lactoOvoVegetarian,lowSugar",
  "dislikedIngredients": null,
  "role": "USER",
  "authProvider": "LOCAL",
  "profileCompleted": true
}
```

비밀번호 해시, `tokenVersion`은 어떤 프로필 응답에도 포함하지 않는다. 임시 비밀번호 발급 기능은 없다.

## A12. 오류 응답

계정·인증·프로필 오류는 다음 형식을 사용한다.

```json
{
  "status": 409,
  "code": "NICKNAME_ALREADY_EXISTS",
  "message": "이미 사용 중인 닉네임입니다.",
  "field": "nickname"
}
```

`code`와 HTTP 상태로 화면 동작을 결정하고 `message`는 표시용으로만 사용한다. `field`는 특정 입력란과 연결할 수 있을 때만 반환한다.

주요 코드:

| 코드 | 화면 처리 |
|---|---|
| `EMAIL_INVALID` | 이메일 입력란 |
| `EMAIL_ALREADY_REGISTERED` | 로그인 안내 |
| `NICKNAME_INVALID` | 닉네임 입력란 |
| `NICKNAME_ALREADY_EXISTS` | 닉네임 재입력 |
| `PASSWORD_INVALID` | 비밀번호 입력란 |
| `LOGIN_FAILED` | 로그인 계정 정보 확인 |
| `OTP_INVALID` | OTP 재입력 |
| `OTP_EXPIRED` | OTP 재전송 |
| `OTP_RATE_LIMITED` | 남은 시간 안내 |
| `VERIFICATION_EXPIRED` | 이메일 재인증 |
| `AUTH_TOKEN_EXPIRED` | 재로그인 |
| `AUTH_TOKEN_INVALID` | 토큰 삭제 후 재로그인 |
| `ACCESS_DENIED` | 권한 부족 안내, 자동 로그아웃 금지 |

서버 또는 네트워크 실패 시 입력을 유지하고 중복 요청을 막은 상태에서 사용자가 재시도할 수 있게 한다.

## A13. 로그인 이후 연결 범위

이번 백엔드 완료 범위:

- 로그인 응답의 `userId`와 서비스 JWT 제공
- `/api/users/me`로 마이페이지 이름·이메일·선택 조건 연결
- 가입한 본인의 알레르기·식이조건을 추천과 상품 안전성 판정에 반영
- 상품 API에서 `userId`를 생략해도 JWT 사용자로 개인화
- 로컬 프로필 사진을 `userId`별로 구분 가능

별도 범위:

- 가족 프로필 전체 서버 API
- 가족 데이터의 서버 동기화
- 프로필 사진 업로드·다운로드

로그아웃 또는 계정 전환 시 프론트는 이전 계정의 로컬 가족·사진 데이터를 무조건 삭제하기보다 `ownerUserId`로 분리해 표시해야 한다.
