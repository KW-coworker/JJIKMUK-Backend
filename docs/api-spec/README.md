# 찍먹 Backend API 명세서

작성 기준: 2026-10-15 팀 저장소 커밋 `87184c4`(로컬 `072ddac`), 2026-10-23 로컬 추천 정책 v5.1 및 프론트 인증 연동 v2이다. 기존 27개에 13개를 추가해 40개 Method·요청주소 조합이다. Git 업로드·운영 배포 완료를 의미하지 않는다. JSON 값은 설명용 예시이다.

## 문서 구성

- [상품 ID·속성 이력·카테고리 정책 단계 전환](../catalog-evolution-stage1-3.md) — 2026-10-28 로컬 추가 6개 경로(ID 조회 3개·관리자 3개), 행동 이력 productId 입력, 용도 판정. 위의 기존 40개 집계에 포함되지 않은 추가 계약이다. 운영 DB 적용 전이다.
- [챗봇 공통 분석 판정 계약](chat-analysis-contract-v1.md) — 2026-10-28 로컬 변경. JWT 본인 검증·가족 합산 조건·공통 상품 판정·AI 계약 확인. 챗봇 관련 이전 설명보다 우선하며 AI 서버 동시 연동이 필요하다.
- [프론트 인증·프로필 연동 v2](frontend-auth-integration-v2.md) — 신규 13개 API, Refresh/명시적 Google 연결/가족/사진/분석 대상 변경 계약과 미합의 항목. 인증 및 해당 변경사항은 이 문서가 우선이다.
- [요청주소별 전체 API 명세서](API_REFERENCE.md) — 기존 27개 API의 상세와 신규 경로 목록. 변경된 인증·분석 계약은 v2 문서를 함께 확인한다.
- [상품·필터·분류 검색](products.md)
- [회원가입·인증·사용자 프로필](auth-users.md)
- [맞춤 추천·대체 추천·사용자 이력](recommendations-history.md)
- [챗봇 중계 API와 확인 필요 사항](chat-and-gaps.md)

Notion에는 통합본의 요청주소별 섹션과 해당 공통 응답 모델을 복사한다. `/me`와 기존 ID 경로도 각각 분리했다. 아래 주제별 문서는 같은 API를 영역별로 읽기 위한 보조 문서이다.

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
| POST | `/api/auth/refresh` | Access·Refresh 갱신 | Refresh 증명 | v2 추가 |
| POST | `/api/auth/google/link` | Google 명시적 연결 | 임시 증명·기존 비밀번호 | v2 추가 |
| POST | `/api/auth/google/link/cancel` | 연결 요청 취소 | 임시 증명 | v2 추가 |
| PATCH | `/api/users/me` | 내 프로필 부분 수정 | 필수 | v2 추가 |
| POST | `/api/users/me/profile/complete` | 추가 프로필 최종 완료 | 필수 | v2 추가 |
| GET | `/api/users/me/photo` | 비공개 프로필 사진 조회 | 필수 | v2 추가 |
| PUT | `/api/users/me/photo` | 프로필 사진 등록·교체 | 필수 | v2 추가 |
| DELETE | `/api/users/me/photo` | 프로필 사진 삭제 | 필수 | v2 추가 |
| GET | `/api/users/me/family-profiles` | 가족 목록 | 필수 | v2 추가 |
| POST | `/api/users/me/family-profiles` | 가족 생성 | 필수 | v2 추가 |
| GET | `/api/users/me/family-profiles/{id}` | 가족 조회 | 필수 | v2 추가 |
| PATCH | `/api/users/me/family-profiles/{id}` | 가족 부분 수정 | 필수 | v2 추가 |
| DELETE | `/api/users/me/family-profiles/{id}` | 가족 삭제 | 필수 | v2 추가 |
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
- login/google/refresh/google-link는 별도 증명으로 인증하므로 오래된 Bearer 때문에 차단하지 않는다. 나머지 공개 경로에는 불필요한 오래된 토큰을 붙이지 않는다.
- 바코드는 문자열이다. 숫자로 변환하지 않는다. 데이터에 `NO_BARCODE_ROW_...` 같은 내부 대체 식별자가 포함될 수 있다.
- 사용자 ID는 정수(Long)이다. `/{id}` 자리에 이메일을 넣지 않는다.
- 선택값 없음은 프로필에서 `null`, 목록에서는 `[]`로 표현한다. `"없음"`을 공통 해제 값으로 사용하지 않는다.

## 시간과 로그인 상태

- Access 만료 `expiresAt`은 UTC Instant 문자열이고 기본 유효시간은 900초다. Refresh는 최초 로그인부터 30일 고정이며 정확한 만료는 refreshExpiresAt을 사용한다.
- 이메일 OTP·인증 증명 응답은 offset을 포함한다. 기존 행동 기록 시각은 LocalDateTime이다. 최종 만료 판정은 서버가 담당한다.
- Refresh/PATCH/사진/가족 API의 상세와 임시 정책은 v2 명세에 있다. 로컬 구현과 운영 배포를 구분한다.
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
