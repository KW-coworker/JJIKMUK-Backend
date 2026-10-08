# 이메일 OTP·회원가입·비밀번호 재설정 API

## 확정 정책

- OTP는 회원가입과 비밀번호 재설정 모두 **4자리 숫자**다.
- OTP 유효시간은 발급 시점부터 **5분**이다.
- `purpose`로 `signup`과 `password_reset`을 분리한다.
- 검증 성공 시 OTP는 폐기하고 1회용 `verificationToken`을 반환한다.
- 회원가입 토큰은 **30분**, 비밀번호 재설정 토큰은 **5분** 동안 유효하다.
- OTP 5분은 메일에 적힌 코드를 검증할 수 있는 시간이고, 회원가입 토큰 30분은 검증 후 온보딩을 완료할 수 있는 시간이다. 두 만료시간은 서로 독립적이다.
- 회원가입과 비밀번호 재설정은 각각 해당 용도의 토큰을 제출해야 한다.
- 토큰 원문은 DB에 저장하지 않고 SHA-256 해시만 저장한다.

## 1. 인증번호 발송·재전송

```http
POST /api/auth/email/send
Content-Type: application/json
```

회원가입:

```json
{
  "email": "user@example.com",
  "purpose": "signup"
}
```

비밀번호 재설정:

```json
{
  "email": "user@example.com",
  "purpose": "password_reset"
}
```

성공 응답:

```json
{
  "message": "인증번호가 이메일로 발송되었습니다.",
  "data": {
    "email": "user@example.com",
    "purpose": "signup",
    "expiresAt": "2026-10-01T20:05:00",
    "expiresInSeconds": 300,
    "resendAvailableAt": "2026-10-01T20:01:00"
  }
}
```

재전송도 같은 endpoint를 호출한다.

- 발송 후 60초 동안 재전송할 수 없다.
- 하나의 5분 발급 구간에서 최초 발송을 포함해 최대 5회까지 허용한다.
- 재전송 성공 시 이전 OTP와 이전에 발급된 같은 용도의 인증 토큰은 무효화된다.
- 이메일 발송 자체가 실패하면 트랜잭션이 롤백되어 기존 OTP는 유지된다.
- `signup`은 이미 가입된 이메일이면 `409`, `password_reset`은 미가입 이메일이면 `404`를 반환한다.
- 제한 중 재호출하면 `429`를 반환한다.

## 2. 인증번호 검증

```http
POST /api/auth/email/verify
Content-Type: application/json
```

```json
{
  "email": "user@example.com",
  "code": "0427",
  "purpose": "password_reset"
}
```

성공 응답:

```json
{
  "message": "이메일 인증이 완료되었습니다.",
  "data": {
    "email": "user@example.com",
    "purpose": "signup",
    "verificationToken": "one-time-opaque-token",
    "expiresAt": "2026-10-01T20:35:00",
    "expiresInSeconds": 1800
  }
}
```

- 코드 불일치는 `400`이며 남은 횟수를 메시지에 포함한다.
- 최대 5회 실패하면 해당 코드를 폐기하고 `429`를 반환한다.
- 코드가 만료되면 폐기하고 `410`을 반환한다.
- 검증 성공 시 OTP 화면은 `verificationToken`을 다음 단계 ViewModel 상태에 보관한다.
- `signup`이면 토큰 유효시간은 30분, `password_reset`이면 5분이다. 항상 응답의 `expiresAt`과 `expiresInSeconds`를 사용한다.

## 3. 최종 회원가입

```http
POST /api/auth/signup
Content-Type: application/json
```

```json
{
  "email": "user@example.com",
  "password": "new-password",
  "nickname": "찍먹사용자",
  "allergies": "milk,wheat",
  "specialDiet": "lactoOvoVegetarian,lowSugar,highProtein",
  "diseases": null,
  "dislikedIngredients": null,
  "verificationToken": "email-verify 응답의 토큰"
}
```

`signup` 용도의 유효한 토큰만 허용한다. 회원가입이 성공하면 토큰을 소비하며 재사용할 수 없다. 회원가입 트랜잭션이 실패하면 토큰 소비도 함께 롤백되므로 30분 유효시간 안에는 재시도할 수 있다.

선택 정보의 허용 ID와 해제 규칙은 `docs/user-preference-contract.md`를 따른다.

## 3-1. 회원가입 인증 상태 처리 규칙

1. `/email/verify` 성공 시 사용한 OTP 행은 삭제하고, 서버에는 토큰 원문이 아닌 `signup` 인증 권한의 해시와 만료시각을 보관한다.
2. 앱은 응답의 `verificationToken`을 메모리/ViewModel 상태로만 다음 화면에 전달한다. `isOtpVerified=true`만으로는 가입할 수 없다.
3. 이메일을 변경하면 기존 토큰은 새 이메일과 일치하지 않으므로 사용할 수 없다. 앱은 토큰을 지우고 새 이메일 인증부터 다시 진행한다.
4. 같은 이메일로 OTP를 재전송하면 기존 OTP와 이미 발급된 `signup` 토큰을 모두 무효화한다.
5. 가입 성공 시 토큰을 소비한다. 같은 토큰의 재사용은 거부한다.
6. 입력값 검증 오류나 서버 오류 등으로 가입 트랜잭션이 실패하면 토큰 소비도 롤백한다. 토큰이 만료되지 않았다면 다시 인증할 필요 없이 가입을 재시도할 수 있다.
7. 서버에서는 가입됐지만 앱이 성공 응답을 받지 못한 경우, 동일 이메일 재시도는 `409 Conflict`와 로그인 시도 안내를 반환한다. 앱은 “이미 가입된 계정일 수 있습니다. 로그인해 주세요.”를 표시하고 로그인 화면으로 이동할 수 있어야 한다.

## 4. 비밀번호 재설정(B안)

```http
POST /api/auth/password/reset
Content-Type: application/json
```

```json
{
  "email": "user@example.com",
  "verificationToken": "email-verify 응답의 토큰",
  "newPassword": "changed-password"
}
```

`password_reset` 용도의 유효한 토큰만 허용한다. 기존처럼 OTP 코드를 최종 재설정 요청에 다시 보내지 않는다. 성공하면 비밀번호를 변경하고 토큰을 소비한다.

## 프론트 처리 순서

### 회원가입

```text
email/send(purpose=signup)
→ email/verify(purpose=signup)
→ verificationToken 보관
→ signup(verificationToken 포함)
```

### 비밀번호 재설정

```text
email/send(purpose=password_reset)
→ email/verify(purpose=password_reset)
→ verificationToken 보관
→ 새 비밀번호 화면
→ password/reset(verificationToken 포함)
```

앱 타이머는 응답의 `expiresInSeconds`로 표시하되 서버의 만료 판정을 최종 기준으로 한다. OTP 검증 성공 후에는 OTP 타이머를 멈춘다. 회원가입 온보딩에서는 별도의 30분 가입 가능 시간을 적용하고, 시간이 만료되면 입력값을 가능한 범위에서 유지한 채 이메일 인증 화면으로 돌아간다. 새 비밀번호 화면에서는 5분 토큰이 만료되면 OTP 발송 화면으로 되돌려 재인증한다.

## 회원가입 인증 30분 만료 UI

30분이 지났는지 확인하기 위한 별도 API는 호출하지 않는다. `/email/verify` 응답의 `expiresAt`을 기준으로 앱에서 타이머를 표시한다.

```text
expiresAt 도달
→ 회원가입 제출 비활성화
→ "이메일 인증 시간이 만료되었습니다" 안내
→ "다시 인증하기" 버튼 표시
```

사용자가 `다시 인증하기`를 누르면 다음 API부터 다시 호출한다.

```http
POST /api/auth/email/send
Content-Type: application/json
```

```json
{
  "email": "user@example.com",
  "purpose": "signup"
}
```

그다음 `/api/auth/email/verify`를 다시 호출해 새로운 `verificationToken`과 30분 만료시각을 받는다. 기기 시간 오차, 백그라운드 복귀 등으로 앱 타이머가 남아 있더라도 `/signup`에서 `410 Gone`을 받으면 동일한 만료 UI를 표시한다. 서버 만료 판정이 최종 기준이다.
