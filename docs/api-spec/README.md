# 찍먹 Backend API 명세서

작성 기준: 2026-10-08. 로컬 백엔드 커밋 `aae4ece`(팀 저장소 업로드 커밋 `d5b04c5`) 및 이후 로컬에 추가한 상품 용량 옵션 API의 구현을 기준으로 한다. 운영 서버에 같은 버전이 배포되었다는 의미는 아니다. 아래 JSON의 이메일·토큰·상품·ID는 설명용 예시이며 실제 조회 결과가 아니다.

## 문서 구성

- [상품·필터·분류 검색](products.md)
- [회원가입·인증·사용자 프로필](auth-users.md)
- [맞춤 추천·대체 추천·사용자 이력](recommendations-history.md)
- [챗봇 중계 API와 확인 필요 사항](chat-and-gaps.md)

각 문서의 API 단위 섹션을 Notion의 해당 API 페이지에 복사한다. 최초 명세 작성 후 상품 용량 옵션 API 구현에 맞춰 P07과 전체 목록을 추가 갱신했다.

## 기존 목록에서 수정할 내용

| 기존 페이지 | 조치 |
|---|---|
| 식단·영양 필터 종류 조회 | 제목과 첫 요청 줄을 `GET /api/products/filters`로 통일한다. 단수 `/filter`는 상품 검색이다. |
| 카테고리·알레르기 분류 조회 | 14개 카테고리, 26개 알레르기, 3개 분류 상태를 명시한다. |
| 키워드와 OR 조건 검색 / 필터 기반 검색 | 독립 API가 아니다. 통합 조건 검색 페이지의 요청 예시로 통합하거나 해당 페이지를 참조한다. |
| 통합 조건 검색 | `categories`, `categoryMatch`, `containsAllergens`, `allergenMatch`, 개인 분석·페이지 구조를 추가한다. |
| 유저 프로필 생성 | 정확한 기능명은 회원가입이다. `verificationToken` 필수, 성공은 201이다. |
| 유저 로그인 / Google 로그인 | 토큰 외에 `userId`, 만료 정보, `isNewUser`, `profileCompleted`를 추가한다. |
| 유저 프로필 조회·수정 | `/me` 권장 경로를 추가하고 기존 `/{id}`는 호환 경로로 유지한다. PUT 전체 교체 규칙을 명시한다. |
| 이메일 인증번호 전송·확인 | `purpose` 필수, 4자리·5분 OTP, 검증 후 증명 토큰 반환으로 갱신한다. |
| 비밀번호 찾기 | 페이지명을 비밀번호 재설정으로 바꾼다. OTP `code` 대신 검증 완료 후 `verificationToken`을 전송한다. |
| 비밀번호 변경 | 현재 비밀번호를 검증한다. 성공 후 기존 모든 로그인 토큰이 무효화된다. |
| 바코드 조회 / 키워드 검색 | `product`, `analysis`, `nutrientPercents` 구조와 UNKNOWN 표시를 추가한다. |
| 사용자 스캔 히스토리 조회 | 현재는 SCAN 외 행동도 함께 반환한다. 페이지명을 사용자 행동·스캔 이력 조회로 보완한다. |

## 전체 API 목록

인증의 ‘선택’은 토큰 없이 일반 조회가 가능하고, 토큰을 전달하면 본인 조건을 적용한다는 뜻이다. 관리자 권한이 필요한 API를 일반 앱 화면에 노출하지 않는다.

| Method | URL | 페이지 이름 | 인증 | 기존 사진 대비 |
|---|---|---|---|---|
| GET | `/api/products/filters` | 식단·영양 필터 종류 조회 | 불필요 | 갱신 |
| GET | `/api/products/classifications` | 카테고리·알레르기 분류 조회 | 불필요 | 갱신 |
| GET | `/api/products/filter` | 통합 조건 검색 | 선택 | 예시 페이지 통합 |
| GET | `/api/products/search` | 키워드 상품 검색 | 선택 | 갱신 |
| GET | `/api/products/{barcode}` | 바코드 상품 조회 | 선택 | 갱신 |
| GET | `/api/products/{barcode}/variants` | 상품 전체 용량 옵션 조회 | 선택 | 추가 |
| GET | `/api/products/safe-recommendations` | 맞춤 안심 상품 추천·카테고리별 보기 | 필수 | 추가 |
| POST | `/api/auth/email/send` | 이메일 인증번호 발송·재전송 | 불필요 | 갱신 |
| POST | `/api/auth/email/verify` | 이메일 인증번호 검증 | 불필요 | 갱신 |
| POST | `/api/auth/signup` | 회원가입 | 불필요 | 갱신 |
| POST | `/api/auth/login` | 이메일 로그인 | 불필요 | 갱신 |
| POST | `/api/auth/google` | Google 로그인·자동 가입 | 불필요 | 갱신 |
| POST | `/api/auth/password/reset` | 비밀번호 재설정 | 불필요 | 갱신 |
| GET | `/api/auth/nicknames/availability` | 닉네임 사용 가능 여부 조회 | 불필요 | 추가 |
| POST | `/api/auth/logout` | 로그아웃 안내 | 필수 | 추가 |
| GET | `/api/users/me` | 내 프로필 조회 | 필수 | 추가·권장 |
| PUT | `/api/users/me` | 내 프로필 전체 수정 | 필수 | 추가·권장 |
| GET | `/api/users/{userId}` | ID로 프로필 조회 | 본인/관리자 | 기존 호환 |
| PUT | `/api/users/{id}` | ID로 프로필 전체 수정 | 본인/관리자 | 기존 호환 |
| PUT | `/api/users/{id}/password` | 로그인 상태에서 비밀번호 변경 | 본인 | 갱신 |
| DELETE | `/api/users/{id}` | 회원 탈퇴 | 본인/관리자 | 추가 |
| GET | `/api/users` | 전체 사용자 조회 | 관리자 | 추가 |
| GET | `/api/histories/user/{userId}` | 사용자 행동·스캔 이력 조회 | 본인/관리자 | 갱신 |
| POST | `/api/histories/events` | 사용자 행동 기록 | 필수 | 추가 |
| GET | `/api/recommendations/products/{barcode}` | 특정 상품의 대체 상품 추천 | 필수 | 추가 |
| POST | `/api/recommendations/feedback` | 추천 피드백 기록 | 필수 | 추가 |
| POST | `/api/chat` | 백엔드를 통한 AI 챗봇 중계 | 필수 | 추가·연동 주의 |

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

- 로그인 만료 `expiresAt`은 UTC 오프셋을 포함하는 Instant 문자열이다. `expiresInSeconds` 기본값은 86400이다.
- 이메일 OTP·인증 증명·행동 기록 시각은 현재 LocalDateTime이므로 응답 문자열에 시간대가 없다. 이를 무조건 UTC로 해석하지 않는다. OTP/인증 타이머는 응답의 `expiresInSeconds`를 사용하고 최종 만료 판정은 서버 응답을 따른다.
- Refresh Token과 갱신 API는 현재 없다. 프로필 PATCH도 없다. 회의에서 나온 제안을 이미 구현된 API로 기재하지 않는다.
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
| API별 | `REQUEST_FAILED` | 상품·추천·이력 등에서 사용하는 일반 업무 오류 코드 |
| 500 | `INTERNAL_SERVER_ERROR` | 서버 오류 |

**현재 모든 오류가 이 구조로 통일된 것은 아니다.** `/api/products/filter`, `/api/products/search`의 직접 검증 오류는 `{ "message": "..." }` 또는 지원 목록을 포함한 별도 응답이다. 상품·이력·추천의 소유권 오류는 동일한 HTTP 401/403이어도 코드가 `REQUEST_FAILED`일 수 있다. 각 페이지의 오류 설명을 함께 적용한다.

필수 query 누락, 숫자 자리에 문자열 입력 등 Spring 파라미터 바인딩 오류는 현재 전용 처리기가 없어 공통 Exception 처리에서 500이 될 수 있다. 이를 정상적인 입력 오류 계약으로 권장하지 않으며 개선 필요 항목으로 남긴다.

## 문서 확인 근거

- `ProductController`, `ProductService`, `ProductFilter`, `ProductClassificationCatalog`, `Product`
- `AuthController`, `AuthDto`, `AuthService`, `EmailService`, `EmailVerificationSecurity`
- `UserController`, `UserService`, `UserPreferenceCatalog`
- `SafeProductRecommendationController/Service/Dto`, `RecommendationController/Service/Dto`
- `RecommendationFeedbackService`, `HistoryController/Service/Repository`, `ChatController/Service`
- `SecurityConfig`, `JwtAuthenticationFilter`, `GlobalExceptionHandler`

예시의 정적 목록·필드·기본값은 코드를 대조했으며, 이번 문서 작업에서 운영 API나 실제 이메일/Google 인증을 호출하지 않았다.
