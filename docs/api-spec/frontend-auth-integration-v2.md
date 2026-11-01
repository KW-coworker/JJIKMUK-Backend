# 프론트 인증·프로필 연동 변경 계약 v2

> 로그인 전용 릴리스 검증(2026-11-01): `fix/auth-login-hardening`은 팀 main 기준으로 인증 변경만 포함한다. 전체 **289개 중 283개 통과 / 기존 조건부 미실행 6개 / 실패 0개**, `test bootJar` 성공. 아래 단계별 통계는 당시 개발 원본의 기록이며, 상품 변경까지 포함한 291개 결과와는 범위가 다르다. [서버·FE 전달서](../auth-login-release-20261101.md)를 함께 확인한다. 서버 배포는 수행하지 않았다.

기준: 2026-11-01 로컬 구현. 10월 23일 인증 v2에 FE 통합 협의안의 미완료 계정 접근 제한, Refresh 기반 로그아웃, 본인 닉네임 사전 확인을 반영했다. **운영 배포·DB 마이그레이션 완료를 의미하지 않는다.** 기존 `auth-users.md`, `API_REFERENCE.md`의 인증/사진/가족/분석 대상 설명과 충돌하면 이 문서가 우선이다. 그 외 상품 검색·용량·이력 계약은 기존 문서를 따른다.

## 1. 확정 요구와 임시 구현값

| 구분 | 구현 | 프론트와 추가 합의할 내용 |
|---|---|---|
| 부분 수정 | PATCH 추가. 미전송 유지, 선택 필드 null/빈 문자열 해제 | CSV 문자열 유지 여부. 현재 배열은 거절한다. |
| 자동 로그인 | Access 15분, Refresh 최초 로그인부터 30일 고정, 회전 및 재사용 감지 | FE 합의 확정. 갱신 응답 유실 시 재로그인, 기관 서버 실제 설정 확인 필요 |
| Google 연결 | 기존 비밀번호로 소유 확인 후 연결. 5분 증명, 오입력 최대 5회 | 증명 수명/횟수, 연결 확인·취소·재설정 이동 UI |
| Google 완료 | 별도 최종 완료 API만 profileCompleted=true 설정. 미완료 세션은 허용 API 외 403 | 서버 제한은 확정. 아래 허용 범위와 공개 상품 조회 유지 정책 확인 필요 |
| 새 비밀번호 | ASCII 8~72자, 영문/숫자 필수. 특수문자 선택, 한글/공백/기타 Unicode 불가 | FE 합의 확정. 기존 비밀번호 로그인에는 새 생성 규칙을 적용하지 않음 |
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
| POST | `/api/auth/logout/refresh` | Access 없이 현재 기기 서버 세션 폐기 | body의 Refresh |
| GET | `/api/auth/nicknames/availability` | 닉네임 사전 확인, 인증 시 본인 제외 | 선택적 Bearer |
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

10월 23일 추가 경로 13개에 11월 1일 `/api/auth/logout/refresh` 1개를 추가했다. 닉네임 조회는 기존 경로의 동작 변경이다. 상품 ID 관련 별도 추가 경로는 상품 계약을 참고한다. 서버 주소는 배포 담당자가 해당 버전을 배포한 후 확인해야 하며, 서버 주소가 열린다고 이 API가 배포된 것은 아니다.

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
- POST login/google/refresh/google-link/google-link-cancel/logout-refresh 경로는 오래된 Bearer 헤더 때문에 별도 소유 증명 검증이 차단되지 않는다. 일반적으로 이 요청에는 Bearer를 넣지 않는다. 다른 HTTP Method나 하위 경로까지 공개하지 않는다.
- 로그아웃은 body 없이 호출한다. 응답은 `{"message":"...","data":{"userId":17,"serverTokenRevoked":true}}`다. 현재 세션의 Access/Refresh가 모두 폐기되며 사진·가족은 남는다.
- 구형 sid 없는 JWT는 기존 만료까지 호환한다. 해당 토큰으로 로그아웃하면 기기를 식별할 수 없어 보수적으로 모든 세션을 폐기한다.
- 비밀번호 변경·재설정은 tokenVersion 증가와 모든 서버 세션 폐기를 함께 처리한다. 명확한 실패 시에는 유지한다. 탈퇴 시 세션·사진·가족 등 계정별 자료를 함께 삭제한다.
- 앱은 민감 토큰을 Android 보안 저장소에 보관하고 로그·분석 이벤트·공유 문서에 기록하지 않는다. 앱 시작 시 GET me, Access 만료라면 Refresh, 회복 불가능한 인증 실패면 재로그인한다. 네트워크 오류/503은 세션 유지 후 재시도 화면이다.

### 3.1. Access 갱신 없이 로그아웃 — 신규 API

```http
POST /api/auth/logout/refresh
Content-Type: application/json

{"refreshToken":"<저장된 Refresh Token>"}
```

Authorization 불필요. 응답 형식은 기존 로그아웃과 같다.

```json
{
  "message": "서버 세션을 폐기했습니다. 기기에 저장된 토큰을 삭제해주세요.",
  "data": {"userId": 17, "serverTokenRevoked": true}
}
```

- 사용자/세션은 body의 Refresh 해시로 찾는다. userId 입력은 사용하지 않는다. 선택적 Access 헤더가 만료됐거나 다른 계정 것이어도 폐기 대상은 body 증명이 가리키는 세션이다.
- 해당 세션의 Access/Refresh만 무효화하고 다른 기기·계정 세션, 사진, 가족은 유지한다. 새 토큰 발급·회전은 하지 않는다.
- DB에 증명 해시와 세션이 남아 있으면 이미 소비/만료/폐기된 Refresh도 **자기 세션 폐기에만** 사용 가능하다. 인증/갱신 권한을 복구하지 않는다. 반복 호출은 같은 200 응답이며 최초 폐기 시각을 유지한다.
- 누락/null 본문: `400 INVALID_REQUEST_BODY`. 잘못된 형식·미등록 해시·삭제된 계정/세션: `401 REFRESH_TOKEN_INVALID`. 유효한 Access 헤더만 있다고 잘못된 Refresh를 대신 승인하지 않는다.
- 성공 후 앱의 두 토큰을 삭제한다. 응답 유실 시 이 폐기 API는 같은 증명으로 재시도할 수 있으나, 실제 서버 폐기 완료로 단정하지 않는다. 자료 정리/탈퇴로 증명이 삭제되면 반복 요청은 401일 수 있다.
- 이는 Refresh **갱신 API의 재시도 허용이 아니다**. 갱신 응답 유실·처리 여부 불명의 5xx/통신 오류는 기존 합의대로 재로그인한다.
- Refresh가 없는 구형 클라이언트는 유효한 Access로 기존 로그아웃을 사용한다. 둘 다 사용할 수 없으면 로컬 로그아웃은 가능하지만 서버 폐기 성공으로 표시하지 않는다.

### 3.2. 닉네임 사전 확인 — 기존 API 변경

`GET /api/auth/nicknames/availability?nickname=찍먹_user1`의 응답 형식은 유지한다.

- Bearer 없음: 전체 사용자와 비교. 이미 존재하면 `available=false`.
- 유효한 Bearer 있음: JWT의 본인 ID를 제외하고 비교. 본인 닉네임 유지/영문 대소문자 변경은 `available=true`.
- 타인의 닉네임은 false. userId 쿼리로 검사 대상을 변경할 수 없다.
- 미완료 계정도 이용 가능. 잘못되거나 만료된 Bearer는 익명으로 낮추지 않고 기존 401을 반환한다.
- NFKC/trim 정규화·기존 이름 정책과 최종 저장 중복 검사를 유지한다. 사전 확인은 예약이 아니다.

### 3.3. 이메일·비밀번호 로그인 시도 제한 — 2026-11-01

대상은 `POST /api/auth/login`이다. 요청 `email`, `password`와 성공 응답(Access/Refresh 등)은 그대로다. AWS/운영 DB에는 적용하지 않았다.

| 기준 | 기본 허용량 | 적용 방식 |
|---|---|---|
| 계정 | 최근 300초 동안 5회 | 이메일 NFKC·trim·소문자 정규화. IP가 달라도 같은 계정이면 공유 |
| IP | 최근 300초 동안 30회 | 이메일이 달라도 같은 접속 IP이면 공유 |

- 두 제한을 **독립적으로** 검사하고 모두 통과해야 인증 처리를 실행한다. `계정+IP` 조합 하나만 제한하는 방식이 아니다.
- 실패 횟수만이 아니라 **인증 처리를 허용한 시도 전체**를 센다. 성공, 미가입, 비밀번호 오류, 이메일 형식 오류, Google 전용 계정에 대한 비밀번호 로그인 모두 포함한다. 서버 오류로 종료되어도 이미 허용한 시도는 반환하지 않는다.
- 따라서 계정의 첫 5번은 기존 인증 결과(200/401/409 등)이고 최근 300초 안의 6번째 요청부터 429이다. 성공해도 계정/IP 카운터를 초기화하지 않는다. 이 수치는 초기 운영값이며 합의·트래픽 측정에 따라 조정할 수 있다.
- 매 정각 초기화가 아닌 **이동 시간창(sliding window)**이다. 각 시도는 그 시점부터 300초 뒤에 만료된다. 429 자체는 시도 횟수에 더하지 않고 차단 만료를 연장하지 않는다.
- 동시 요청도 한 번에 검사·등록하여 제한을 초과해 비밀번호 검사/DB 세션 발급을 시작하지 않는다. 기록은 인증 트랜잭션 바깥에 있어 로그인 실패 롤백으로 사라지지 않는다.
- JSON 파싱 실패·필수 필드 누락은 컨트롤러 진입 전 기존 `400 INVALID_REQUEST_BODY`로 처리되며 이 제한의 집계 대상이 아니다. 대량 HTTP/잘못된 본문 공격은 프록시/WAF의 별도 요청 제한이 필요하다.
- Google 로그인, Refresh, OTP, 비밀번호 재설정, 로그아웃에는 이 카운터를 적용하지 않는다. 해당 API의 기존 검증·별도 횟수 제한은 유지한다.

#### 제한 초과 응답

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 173
```

```json
{
  "status": 429,
  "code": "LOGIN_RATE_LIMITED",
  "message": "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해주세요.",
  "retryAfterSeconds": 173
}
```

`retryAfterSeconds`는 최상위 정수(초)이고 `Retry-After` 헤더와 동일하다. 잔여 밀리초는 올림하여 최소 1초를 반환한다. 계정과 IP가 모두 제한되면 둘 중 더 긴 대기시간을 제공한다. `data`, 토큰, 계정 존재 여부, 어느 제한에 걸렸는지, `remainingAttempts`는 제공하지 않는다. 다른 사용자의 동시 요청이 있으므로 타이머가 끝나도 서버의 다음 응답이 최종 기준이다.

#### FE 전달 사항

1. 로그인 버튼 중복 클릭을 막고 로그인 요청은 한 번만 진행한다.
2. `429`와 `code=LOGIN_RATE_LIMITED`이면 비밀번호 오류(401)와 구분한다. 로그인 화면에서 남은 시간을 표시하고 해당 시간 동안 재요청을 막는다.
3. `retryAfterSeconds`를 우선 사용하고 필요하면 `Retry-After` 정수 초 헤더를 보조로 사용한다. 300초를 앱에 고정하지 않는다. 타이머는 화면 재생성/백그라운드 복귀 때에도 경과시간을 반영한다.
4. 자동 재시도·Refresh 호출·토큰 삭제·강제 로그아웃을 하지 않는다. 카운트다운 종료 후 사용자가 다시 누를 수 있게 한다. 이메일을 수정했다고 서버 IP 제한이 없어지는 것으로 간주하지 않는다.
5. 안내 예: `로그인 시도가 많아 잠시 제한되었습니다. 2분 53초 후 다시 시도해주세요.` 만료 후에도 429이면 새 서버 대기시간을 적용한다.
6. 네트워크 실패로 로그인 요청을 무조건 반복하지 않는다. 서버에서는 시도가 집계됐거나 로그인 세션이 발급됐을 수 있다.

#### 서버 담당자 전달 사항

| 환경변수 | 기본값 | 의미 |
|---|---:|---|
| `AUTH_LOGIN_ACCOUNT_LIMIT` | 5 | 계정 허용 시도 수(1~1,000) |
| `AUTH_LOGIN_IP_LIMIT` | 30 | IP 허용 시도 수(1~10,000) |
| `AUTH_LOGIN_WINDOW_SECONDS` | 300 | 공통 이동 시간창, 초(1~86,400) |
| `AUTH_LOGIN_MAX_TRACKED_KEYS` | 10000 | 계정/IP 합산 메모리 키 상한(2~100,000) |

- 실행 중인 JAR/이미지 교체와 재시작이 필요하다. Git push만으로 실행 서버가 변경되지는 않는다. 이번 제한 자체에는 DB 마이그레이션이 없다.
- **현재 제한은 프로세스별 메모리 구현**이다. 서버 재시작 시 초기화되며 서버가 여러 대면 서로 공유되지 않는다. 다중 인스턴스/무중단 롤링 배포에서도 공통 한도가 필요하면 Redis 등 공유 저장소의 원자적 카운터로 교체해야 한다. 현재 구현을 분산 제한으로 설명하지 않는다.
- 계정과 IP는 SHA-256 해시 키로만 보관하고 비밀번호는 보관하지 않는다. 만료 키는 후속 요청에서 정리한다. 상한에 도달하면 활성 기록을 버려 제한을 우회시키지 않고, 새 키가 필요한 요청에 429와 공간 확보까지의 대기시간을 반환한다.
- 원시 `X-Forwarded-For`, `Forwarded`, `X-Real-IP`를 직접 믿지 않고 `HttpServletRequest.remoteAddr`를 사용한다. IPv6 표기 차이와 IPv4-mapped IPv6는 같은 주소로 정규화한다. IP를 판별할 수 없는 요청은 공통 unknown 버킷을 사용한다.
- 기본 `SERVER_FORWARD_HEADERS_STRATEGY=none`이다. 이 상태에서 프록시를 경유하면 프록시 IP에 한도가 합산될 수 있다. Tailscale Serve/NGINX/ALB 등 실제 배포 경로를 먼저 확인한다.
- 프록시 환경에서 원래 사용자 IP를 쓰려면 서버 담당자가 **신뢰할 프록시만** 허용하도록 `server.tomcat.remoteip.internal-proxies` 등을 설정하고 `SERVER_FORWARD_HEADERS_STRATEGY=native`를 적용한다. 허용 범위를 비워 모든 프록시를 신뢰하거나 실제 프록시를 확인하지 않은 채 전체 사설망을 허용하지 않는다. 경계 프록시에서 외부의 위조 전달 헤더를 제거/재작성하고 앱 포트 직접 접근도 제한한다.
- `framework` 모드의 전달 헤더 무조건 해석은 이번 구현에서 검증하지 않았다. 사용자 임의 헤더를 실제 IP로 인정하면 제한이 우회되므로 적용하지 않는다. 운영에서 서로 다른 클라이언트가 다른 IP로 집계되고 위조 헤더로 우회되지 않는지 별도 승인 후 확인한다.
- 학교 Wi-Fi/공용 NAT 사용자는 IP 한도를 공유한다. 5회/30회는 표준이 요구하는 정답 수치가 아닌 초기 정책값이다. 실제 오탐·실패율과 사용량을 보고 조정한다. 악의적인 타인의 시도로 계정이 잠시 제한될 수 있는 위험도 고려한다.

설계 참고: [OWASP 로그인 시도 제한](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html#login-throttling), [Spring Boot 프록시 설정](https://docs.spring.io/spring-boot/4.0/how-to/webserver.html#howto.webserver.use-behind-a-proxy-server).

검증: 신규 단위 테스트 15개, H2 기반 HTTP 통합 테스트 10개 통과. 계정/IP 독립 제한, 정규화, 만료 경계, 재시도 시간, 동시 요청, 메모리 상한, 헤더 위조, 실패 롤백, 성공 후 제한 유지, Refresh/Google/로그아웃 비영향을 확인했다. 전체 `test bootJar` 결과는 **282개 중 276개 통과, 기존 조건부 미실행 6개, 실패/오류 0개**, JAR 빌드 성공이다. 실제 AWS 프록시 경로와 운영 데이터는 테스트하지 않았다.

## 4. Google 명시적 연결과 최종 완료

`POST /api/auth/google`의 body는 `{"idToken":"<Google ID token>"}`다. 서버는 issuer, audience, 만료, 이메일 검증 여부, Google subject를 검사한다. 앱/서버의 OAuth Client ID를 배포 전에 맞춰야 한다.

### Google 검증 구현 및 배포 전달 사항 (2026-11-01)

- 공식 `com.google.api-client:google-api-client:2.9.1`의 `GoogleIdTokenVerifier`로 RS256 서명과 클레임을 검사한다. 이전 tokeninfo 호출은 제거했다.
- 공개키 매니저/검증기는 singleton이다. Google 공개 인증서를 HTTPS로 받아 캐시하며, ID Token 자체는 외부 검증 URL이나 로그로 보내지 않는다. 최초 조회/캐시 갱신에는 외부 통신이 필요하다.
- 기본 공개키 주소는 `https://www.googleapis.com/oauth2/v1/certs`다. 서버에서 해당 주소로의 DNS 및 HTTPS 아웃바운드 통신, 신뢰할 수 있는 TLS 인증서 체인, 정확한 시스템 시간이 필요하다. 수신 포트나 MySQL 포트를 새로 개방하는 작업은 아니다.
- 허용 audience는 `GOOGLE_CLIENT_ID`의 Web OAuth Client ID 하나다. Android client ID/Client Secret/서비스 계정 키는 이 값이 아니다. FE의 serverClientId와 같아야 한다.
- RS256 이외 알고리즘, 잘못된 서명/aud/iss, 누락되거나 만료된 exp, 누락되거나 미래인 iat, 미검증 이메일, 잘못된 이메일/subject는 거부한다. 기존 만료 거부 정책을 유지하기 위해 시계 오차 허용은 0초다. 서버 NTP 동기화를 확인한다.
- 형식·서명·클레임 오류는 `401 GOOGLE_TOKEN_INVALID`, 설정 누락·공개키 조회/인증서 장애는 `503 GOOGLE_LOGIN_UNAVAILABLE`다. 503을 사용자 계정 오류로 표시하지 말고 재시도를 안내한다.
- 실제 Client ID는 Git 제외 로컬 `application-local.properties`에만 설정했다. `GOOGLE_CLIENT_ID` 환경변수가 있으면 해당 값이 우선한다. 이 파일은 JAR에 포함되지 않고 AWS로 자동 전파되지 않는다.
- 서버 담당자는 새 의존성이 포함된 JAR/이미지를 빌드·배포하고 실행 프로세스/컨테이너의 `GOOGLE_CLIENT_ID`를 설정한 뒤 재시작한다. Compose의 `.env`는 보간용이므로 해당 변수가 서비스의 `environment` 또는 `env_file`을 통해 전달되는지도 확인한다.
- 이 검증 방식 변경에는 SQL/Flyway 변경이 없다. 단, 배포하려는 전체 코드의 기존 인증 스키마 요구사항은 별도 확인한다. 이번 작업은 AWS/운영 DB 적용이 아니다.
- FE는 기존 `POST /api/auth/google` 요청/응답을 유지한다. 같은 프로젝트의 Android OAuth client에 실제 APK의 package/SHA-1을 등록하고, 앱의 Google 로그인 제한 플래그 및 대상/게시 상태도 확인한다.
- 합동 테스트는 신규 Google 사용자(추가 입력), 기존 Google 사용자, 같은 이메일 일반 계정(명시적 연결), 로그인 취소를 승인된 테스트 환경에서 진행한다. 실제 로그인은 계정/세션을 생성할 수 있으므로 운영 테스트는 담당자와 별도로 승인한다.

검증 결과 (2026-11-01): 신규 테스트 43개(검증기 38 + 로그인 통합 5)가 통과했다. 임시 RSA 키로 실제 서명 검증기를 실행하고 H2에서 신규 가입/재로그인/명시적 연결, 잘못된 토큰·공개키 장애 시 계정 미생성을 검사했다. 전체 `test bootJar`는 243개 중 237개 통과, 환경·파일 조건부 6개 미실행, 실패/오류 0개다. 로컬 설정 파일과 CSV의 JAR 미포함도 확인했다. Google 공개키 공급은 테스트 대역이므로 실제 Google 계정·Android 선택 UI·실서버 HTTPS 연결까지 검증한 것은 아니다. AWS와 로컬/운영 MySQL은 수정하지 않았다.

공식 근거: [Google 서버 인증 가이드](https://developers.google.com/identity/sign-in/android/backend-auth).

### Google 통신·DB 트랜잭션 경계 강화 (2026-11-01)

앞선 동시 가입 복구에서 `Google 검증 → 계정/세션 DB 처리`는 이미 분리했다. 이번 변경은 **상위 트랜잭션의 자원을 유지한 채 외부 통신하는 호출도 방지**하는 보강이다.

- `AuthService.googleLogin`은 트랜잭션 없는 진입점으로 유지한다.
- `GoogleLoginService.login`은 기존 `NOT_SUPPORTED`(상위 트랜잭션 일시 중단) 대신 `NEVER`를 사용한다. 상위에서 이미 트랜잭션을 시작했다면 Google 검증 전에 즉시 거부한다. 트랜잭션을 중단해도 기존 연결·잠금까지 종료되는 것은 아니기 때문이다.
- 실제 공개키 조회/서명 검증을 담당하는 `GoogleIdentityVerifier.verify`에도 `NEVER`를 적용했다. 다른 서비스가 검증기를 직접 호출하는 경우에도 활성 트랜잭션 안에서는 실행하지 않는다. Spring Bean을 통한 호출 경계를 유지하며 직접 객체 생성·자가 호출로 프록시를 우회하지 않는다.
- 토큰 파싱·필수 클레임·공개키 조회/캐시·서명 검증이 성공한 뒤에만 `GoogleIdentity(subject, email)`를 DB 담당 Bean에 전달한다. 원본 Google ID Token을 DB 서비스에 전달하지 않는다.
- `GoogleLoginTransactions.loginOrCreate`와 충돌 복구 `recoverExisting`의 `REQUIRES_NEW`는 유지한다. 사용자 저장과 Access/Refresh 세션 저장은 함께 커밋하거나 함께 롤백한다. DB 커밋이 끝난 후에만 성공 응답을 반환한다.
- 내부 코드가 규칙을 어겨 활성 트랜잭션에서 호출하면 `IllegalTransactionStateException`으로 실패한다. 이는 사용자가 해결할 오류가 아닌 백엔드 호출 구조 오류이며, 정상 HTTP 경로는 해당 상황을 만들지 않는다. 실패를 잡아 트랜잭션 안에서 Google 호출을 재시도하지 않는다.
- 이 경계는 이 애플리케이션의 Spring 트랜잭션 호출에 적용한다. 이미 다른 코드에서 트랜잭션을 수동으로 중단하거나 JDBC 연결을 직접 점유한 경우까지 자동으로 감지·해제하는 기능은 아니다.

FE 계약은 변경하지 않는다. `POST /api/auth/google`의 `idToken`, 성공 응답, `GOOGLE_LINK_REQUIRED`, `profileCompleted` 분기를 그대로 사용한다. 공개키 장애는 기존 `503 GOOGLE_LOGIN_UNAVAILABLE`, 유효하지 않은 토큰은 `401 GOOGLE_TOKEN_INVALID`다. Google 검증 실패에서는 계정/연결 증명/세션/Refresh 레코드를 만들지 않는다. 503은 서비스 연결 오류로 안내하며 가입 실패나 계정 삭제로 해석하지 않는다.

서버에는 새 JAR/이미지를 배포해야 반영된다. 이번 보강에는 환경변수·Client ID 변경, SQL/Flyway 마이그레이션, Google Console 변경이 없다. Google 통신의 전체 시간 제한·분산 회로 차단기를 추가한 작업은 아니므로 응답시간 보장을 별도로 주장하지 않는다. AWS와 로컬/운영 MySQL은 변경하지 않았다.

검증은 Google 공개키 공급 지점의 지연/장애만 테스트 대역으로 제어하고, 실제 `GoogleIdTokenVerifier`의 RSA 검증과 Spring 트랜잭션 프록시·HTTP 컨트롤러·H2를 사용한다. DB 풀을 **연결 1개**로 제한하여 Google 검증 대기 중 점유 연결이 0개이며 같은 동안 이메일 로그인이 성공하는지 확인한다. 신규/기존 로그인, 검증 실패 전 DB 처리 차단, read-only 포함 활성 트랜잭션의 검증기 직접 호출 차단, 세션 저장 후 장애 시 전체 롤백, LOCAL 계정 명시적 연결 유지도 검사한다. 실제 Google 네트워크 지연이나 AWS/MySQL 운영 부하 측정은 아니다.

이 단계 개발 원본 결과: 신규 경계 통합 테스트 **9개 통과**, 기존 동시 가입 통합 테스트 **9개 통과**. 전체 `test bootJar`는 **291개 중 285개 통과, 기존 조건부 미실행 6개, 실패/오류 0개**, JAR 빌드 성공이다. 이 개별 개발 단계에서는 Git 커밋/push와 서버 배포를 수행하지 않았다. 이후 로그인 전용 릴리스의 검증 범위는 문서 상단을 따른다.

근거: [Spring 트랜잭션 전파 규칙](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/transaction/annotation/Propagation.html), [독립 트랜잭션과 외부 자원 점유 주의사항](https://docs.spring.io/spring-framework/reference/data-access/transaction/declarative/tx-propagation.html).

### Google 최초 가입 동시 요청 복구 (2026-11-01)

- `POST /api/auth/google` 요청/응답 형식은 변경하지 않는다. 동일 Google 사용자의 최초 로그인 요청이 동시에 도착하면 계정은 하나만 생성하고, 생성 경쟁에서 뒤진 요청은 새로 생성된 계정으로 로그인한다. 실제 생성 요청은 `isNewUser=true`, 복구된 요청은 `false`이며 둘의 `userId`는 같다. FE는 여전히 `profileCompleted`로 추가 입력 화면을 판단한다.
- Google 검증은 DB 트랜잭션 밖에서 한 번만 수행한다. 계정 생성과 세션 발급은 별도 Bean의 `REQUIRES_NEW` 트랜잭션으로 묶는다. 신규 users 저장 중 유일값 충돌이 발생하면 해당 트랜잭션을 완전히 롤백한 뒤, 프록시 밖에서 예외를 받아 새로운 `REQUIRES_NEW` 트랜잭션으로 한 번만 재조회한다. rollback-only 트랜잭션 안에서 조회하거나 성공 응답을 반환하지 않는다.
- SQLState `23505`(H2/PostgreSQL), MySQL `23000` + 오류번호 `1062`, Spring `DuplicateKeyException`만 유일값 충돌로 인식한다. 로컬 언어에 따라 바뀌는 DB 오류 메시지로 판정하지 않는다.
- 재조회는 검증된 Google subject를 우선한다. 같은 이메일의 LOCAL 계정이 먼저 생성됐다면 `GOOGLE_LINK_REQUIRED`를 반환하며 자동 연결/로그인하지 않는다. 다른 Google subject에 연결된 계정이면 `401 GOOGLE_TOKEN_INVALID`로 거부한다.
- 재조회에서 계정을 찾지 못하면 원래 실패를 전달한다. 닉네임만 충돌한 경우를 다른 사용자의 로그인 성공으로 바꾸지 않으며, FK/NOT NULL 오류·세션 저장 실패 등 다른 DB 오류도 생성 경쟁으로 취급하지 않는다. 무한 재시도는 없다.
- 복구된 정상 로그인 요청마다 별도 세션을 발급한다. 계정 생성 중복 방지이며, 모든 로그인 요청을 단일 세션으로 합치는 멱등성 기능은 아니다.
- 새 SQL/Flyway 변경 및 FE 요청 필드 추가는 없다. MySQL의 기존 이메일/Google subject 유일 인덱스는 유지해야 한다. AWS/운영 DB 적용은 별도 배포 작업이다.

이 단계 최초 검증: 신규 14개 테스트(분기/오류 분류 5 + 동시성 통합 9)를 추가했다. H2 MySQL 모드와 REPEATABLE_READ에서 두 요청이 모두 계정 부재를 확인한 뒤 INSERT하도록 동기화하여 실제 유일값 충돌과 롤백을 검사했다. 동일 사용자 경쟁을 3회 반복하고 MVC API 요청에서도 두 요청 모두 200/동일 userId인지 확인했다. 동일 subject·상이 이메일, LOCAL 계정 선점, 다른 Google subject 충돌, 세션 저장 실패 시 계정 롤백을 확인했다. 당시 전체 `test bootJar` 결과는 257개 중 251개 통과, 조건부 미실행 6개, 실패/오류 0개였다. 이후 위의 통신·DB 경계 강화에서 상위 트랜잭션 테스트는 ‘일시 중단’ 대신 ‘검증 전 거부’ 기준으로 갱신했다. 실제 MySQL 엔진이나 AWS 동시성 검증을 대체하지 않으며 해당 환경은 변경하지 않았다.

신규 Google 계정은 Access/Refresh를 발급하되 profileCompleted=false다. 재로그인해도 완료 전에는 false를 유지한다. 앱은 추가 입력 화면으로 이동한다. 11월 1일부터 서버도 유효한 미완료 계정의 요청을 아래 허용 범위로 제한한다. Google 여부와 관계없이 DB의 profileCompleted=false가 기준이며 관리자 역할도 이 검사를 우회하지 않는다.

| Method | 허용 경로 | 목적 |
|---|---|---|
| GET/HEAD | `/api/users/me` | 본인/완료 상태 확인 |
| PATCH | `/api/users/me` | 중간 저장, 완료 상태는 바꾸지 않음 |
| POST | `/api/users/me/profile/complete` | 최종 입력 검증 후 완료 |
| GET/HEAD, PUT, DELETE | `/api/users/me/photo` | 사진 조회·저장·삭제 |
| GET/HEAD | `/api/auth/nicknames/availability` | 닉네임 확인 |
| GET/HEAD | `/api/products/filters`, `/api/products/classifications` | 가입 조건 선택용 메타데이터 |
| POST | `/api/auth/logout`, `/api/auth/logout/refresh`, `/api/auth/refresh` | 세션 폐기/갱신 |
| DELETE | `/api/users/{JWT 본인 ID}` | 본인 탈퇴, 타인 삭제 불가 |
| POST | `/api/auth/login`, `/api/auth/google`, `/api/auth/google/link`, `/api/auth/google/link/cancel`, `/api/auth/signup`, `/api/auth/email/send`, `/api/auth/email/verify`, `/api/auth/password/reset` | 기존 인증·복구 절차, 각 API 고유 증명 검증은 유지 |

나머지 경로/Method(상품 상세·검색·추천, 이력, 챗봇, 가족 관리, 관리자 기능, 구형 PUT 프로필 등)는 컨트롤러 실행 전 다음을 반환한다.

```json
{"status":403,"code":"PROFILE_INCOMPLETE","message":"추가 프로필 입력을 완료해주세요."}
```

FE는 토큰을 유지하고 추가 입력 화면으로 이동한다. `analysisMode=none`도 미완료 세션에서는 우회 수단이 아니다. 필수 닉네임 검증을 통과하면 알레르기/식단 미선택 상태로 완료할 수 있다. 완료 후 DB 상태를 읽으므로 같은 Access로 정상 접근 가능하며 재로그인할 필요 없다. 만료·폐기된 토큰은 먼저 401이며 PROFILE_INCOMPLETE가 아니다.

**범위 한계/추가 합의:** 기존 비로그인 일반 상품 조회는 유지한다. 토큰을 보내지 않은 요청의 계정 완료 상태는 알 수 없으므로 익명 상품 조회를 막는 정책이 아니다. 상품 조회 전체를 로그인 필수로 바꾸려면 별도 보안/공개 API 범위 합의가 필요하다. 별도 AI/OCR 서버로 직접 들어가는 경로까지 이 Spring 필터가 보호하지 않으므로 게이트웨이/담당 서비스 정책도 확인한다.

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

2026-11-02 추가: 생성·수정·목록·단건 응답에 nullable `relation`과 `emoji`를 지원한다. 최초 초안의 `relationship`이 아니라 `relation`을 사용한다. 상세 필드 규칙과 즐겨찾기 연동은 [가족·즐겨찾기 추가 계약](family-favorites-recent-v1.md)을 따른다. V16 및 서버 배포가 필요하다.

생성 예:

```http
POST /api/users/me/family-profiles
Authorization: Bearer <access-token>
Content-Type: application/json

{"nickname":"어머니","allergies":"soy","specialDiet":"lowSodium","diseases":null,"dislikedIngredients":null,"relation":"어머니","emoji":"👩"}
```

201 응답:

```json
{"message":"가족 프로필 생성 성공","data":{"id":41,"nickname":"어머니","allergies":"soy","specialDiet":"lowSodium","diseases":null,"dislikedIngredients":null,"version":0,"relation":"어머니","emoji":"👩"}}
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
- 2026-11-02 변경: 가족/none에서도 로그인 계정에 상세 조회 SCAN을 기록하되 personalizationAllowed=false로 본인 취향 학습에서 제외한다. FE는 상세 GET 이후 이력을 중복 POST하지 않는다. 관계/이모지 및 좋아요·최근 목록은 [추가 계약](family-favorites-recent-v1.md)을 따른다.
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

DB 일시 장애로 JWT 확인에 실패하면 `503 AUTH_SERVICE_UNAVAILABLE`을 반환한다. 이를 AUTH_TOKEN_INVALID로 간주하여 토큰을 삭제하지 않는다. 입력 검증 실패, 403 ACCESS_DENIED, 403 PROFILE_INCOMPLETE, Google 외부 서버 장애 역시 자동 로그아웃 사유가 아니다.

## 10. 응답 유실·재시도 시 프론트 규칙

| 요청 | 응답을 못 받았을 때 |
|---|---|
| 인증메일 발송/재전송 | 발송 실패로 단정하지 않는다. 도착한 코드와 서버 재전송 제한을 확인하고 성공 응답 전에 타이머를 초기화하지 않는다. |
| OTP 검증 | 이미 코드가 소비되었으면 OTP_NOT_REQUESTED일 수 있다. 증명을 잃었다면 코드 재발급·재검증한다. |
| 회원가입 | 입력을 보존하고 로그인 시도. 중복 이메일을 곧바로 기존 실패라고 해석하지 않는다. |
| 비밀번호 변경/재설정 | 성공으로 단정하지 않는다. 기존 세션이 무효이면 새 비밀번호 로그인/재설정으로 복구한다. 자동 반복 변경하지 않는다. |
| Google 연결 | 같은 linkToken 무한 재사용 금지. Google 로그인을 다시 하면 연결 완료 여부에 따라 정상 로그인 또는 연결 증명을 반환한다. |
| Refresh | 처리 여부 불명 시 같은 Refresh를 반복하지 않는다. 재로그인한다. |
| Refresh 기반 로그아웃 | 회전 없는 폐기 요청만 재시도 가능. 통신 실패를 서버 폐기 성공으로 표시하지 않는다. |
| 프로필 PATCH/완료 | GET me로 최신 상태와 완료 여부를 확인한다. |
| 가족 생성 | 목록을 다시 읽어 중복 생성 여부를 확인한다. 현재 생성 idempotency key는 없다. |
| 가족 수정/삭제 | 단건/목록을 재조회하고 최신 version 사용. 삭제 후 404면 이미 삭제된 상태로 처리한다. |
| 사진 등록/교체/삭제 | GET me/photo로 최종 상태를 확인한다. 잘못된 업로드가 기존 사진을 지우지 않는다. |

가입 증명 30분이 지나 UI를 띄울 때 별도 상태 확인 API는 없다. 서버가 준 expiresAt으로 만료 안내 후 `POST /api/auth/email/send`(purpose=signup) → `/email/verify`로 새 증명을 받는다. 최종 가입에서 `410 VERIFICATION_EXPIRED`가 반환되는 경우도 동일하게 처리한다.

## 11. 테스트와 배포 전 체크

2026-11-01 최종 `gradlew.bat test bootJar --no-daemon --console=plain`: **BUILD SUCCESSFUL**, 200개 중 194개 통과, 실패/오류 0개, 명시적 실행이 필요한 대용량 CSV 4개·실제 로컬 MySQL 벤치마크 2개 제외. 이번 후속 변경 테스트 14개를 추가했다(접근 정책 단위 3개, 인증 통합 10개, 실제 루프백 HTTP 1개).

- 로컬 application-local.properties import를 비활성화하고 H2 메모리 DB/테스트 프로필/Flyway 비활성화로 실행했다. 실제 메일·Google·기관 서버·운영 MySQL에는 접속하지 않았다.
- 미완료 상태의 상품/추천/이력/챗봇/구형 PUT 차단, 사진/메타데이터/탈퇴 허용, 완료 후 동일 Access 이용, 401/403 구분을 검증했다.
- 만료 Access와 Refresh 로그아웃, 반복 폐기, 소비/만료 증명의 폐기 전용 사용, 잘못된 증명 거절, 다른 기기·계정/사진/가족 보존, 갱신과 폐기의 동시 실행을 검증했다.
- JWT 본인 닉네임 제외, 익명/타인/잘못된 토큰/임의 userId 쿼리, 최종 저장 중복 검사 및 Refresh/Google 연결 공개 경로도 검증했다.
- 결과: `build/reports/tests/test/index.html`. 실행 JAR: `build/libs/backend-0.0.1-SNAPSHOT.jar`. 커밋/push/기관 배포는 이번 작업에 포함하지 않았다.

아래는 이전 기준 검증 기록이다.

2026-10-23 `gradlew.bat test bootJar --no-daemon --console=plain` 결과: BUILD SUCCESSFUL. 총 144개 중 140개 통과, 실패 0개, 대용량 CSV의 명시적 실행 플래그가 필요한 기존 테스트 4개 제외. 이번 인증 연동 검증 19개를 추가했다. H2/모의 외부 인증 결과이며 MySQL 마이그레이션·실기기 OAuth 결과가 아니다.

- Gradle test 프로필은 H2 및 테스트용 JWT 키를 사용한다. 실제 Google 토큰 검증/메일/객체 저장소 통신은 모의 처리한다.
- 프로필 보존/전체 해제, 명시적 완료, 새 비밀번호 경계값, 기존 비밀번호 로그인, Refresh 회전/재사용/동시 요청/만료, 기기별 로그아웃, 비밀번호 변경·재설정 전체 폐기를 검증한다.
- Google 임시 증명의 접근 불가/비밀번호 검증/취소/횟수/만료, 가족 소유권/동시 수정 version, 사진 형식·크기·격리·실패 보존, 대상 없음과 가족 합집합, cursor 변경, 용량별 식단 충돌을 검증한다.
- V14는 신규 스키마 파일만 추가한다. users에 google_subject/has_profile_photo, auth_sessions/refresh_credentials/google_link_grants/family_profiles/profile_photos를 추가한다. **로컬/운영 MySQL에는 이 작업으로 적용하지 않았다.**
- 배포 전 별도 승인하에 백업 → 스테이징 MySQL에서 V14 적용 및 validate → 실제 메일/Google/두 기기 테스트 → 운영 반영 순서가 필요하다. 애플리케이션을 운영 연결 설정으로 실행해 자동 적용하지 않는다.
- Refresh/연결 증명 및 사진 보관·만료 정리 작업, 실제 서비스 부하, Google Client ID, 앱의 새 enum 처리와 보안 토큰 저장은 배포 전 확인한다. 이 테스트가 실기기·운영 DB 검증을 대신하지 않는다.

## 12. 프론트에 회신할 합의 목록

1. 확정: Access 15분 + 최초 로그인부터 Refresh 30일 고정. 배포 서버 설정을 대조한다.
2. 확정: Refresh 갱신 응답 유실 시 재로그인. 새 로그아웃 API는 폐기 전용이므로 갱신 재시도와 구분한다.
3. 확정: 비밀번호 ASCII 8~72자 영문/숫자 필수·특수문자 선택, 기존 닉네임 규칙. 본인 사전 확인 예외는 JWT를 전달한다.
4. 가족 최대 20명·이름 규칙·선택 상태 동기화·기존 로컬 자료 이전·본인 프로필 동시 수정 정책.
5. 사진 DB 저장을 초기 방식으로 채택할지, 비공개 객체 저장소와 URL 만료 방식으로 바꿀지.
6. 서버 제한은 확정·구현. 메타데이터/사진/탈퇴를 포함한 허용 목록과 익명 상품 조회 유지 여부, 별도 AI/OCR 접근 제한을 추가 확인한다.
7. 가족/none 일반 추천의 UI, 가족 이력 저장, 챗봇 분석 대상 전달까지 이번 연동 범위에 넣을지.
8. 정확한 개발/운영 배포 주소와 Google OAuth Client ID를 비밀값 없이 확인하고 실제 연동 시험 일정을 잡을 것.

11월 1일 변경은 기존 users.profile_completed 및 V14의 세션/Refresh 테이블을 사용한다. 새 SQL 마이그레이션은 없고 로컬/운영 MySQL 변경도 없다. R1 이메일 500, R2 실제 공개 경로 오류, R3 Google 설정 문제는 이 코드 변경으로 해결됐다고 간주하지 않는다. 서버 담당자의 실행 커밋·로그·설정 및 실제 메일/OAuth 검증이 별도로 필요하다.
