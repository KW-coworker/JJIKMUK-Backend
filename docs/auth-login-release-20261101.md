# 로그인 변경 전달서 — 2026-11-01

대상 저장소: `KW-coworker/JJIKMUK-Backend`

브랜치: `fix/auth-login-hardening`

범위: 로그인·인증 관련 코드, 테스트, API 문서. 상품 ID/속성 이력 보정, DB 유지보수 스크립트, CSV, dump, 로컬 비밀 설정은 제외한다.

## 변경 요약

| 변경 | 효과 |
|---|---|
| GoogleIdTokenVerifier 도입 | Google 공개키로 서명·aud/iss/exp/iat·이메일 검증. 사용자 토큰을 tokeninfo URL로 전송하지 않음 |
| Google 통신/DB 경계 | 외부 검증 완료 후에만 DB 처리. 활성 트랜잭션에서 검증 호출 시 거부 |
| Google 동시 가입 복구 | 신규 사용자 유일값 충돌을 롤백한 후 새 트랜잭션에서 한 번 재조회. 다른 Google 계정으로 로그인하지 않음 |
| 이메일 로그인 시도 제한 | 계정별 최근 5분 5회 / IP별 최근 5분 30회, 성공·실패 포함. 초과 시 429와 대기시간 |
| 미완료 프로필 접근 제한 | 허용 API 외 `403 PROFILE_INCOMPLETE`. 최종 완료 API로 완료 상태 전환 |
| Refresh 기반 로그아웃 | Access 갱신 없이 해당 기기 세션 폐기. 새 토큰은 발급하지 않음 |
| 본인 닉네임 사전 확인 | 유효한 JWT가 있으면 본인 ID를 중복 검사에서 제외 |

## 서버 담당자에게

1. PR 리뷰 후 팀 규칙대로 **Squash and merge**하고 새 JAR/이미지를 빌드·배포한다. push 자체는 배포 완료가 아니다. 이번 작업에서는 AWS 재시작·배포·운영 DB 변경을 하지 않는다.
2. `GOOGLE_CLIENT_ID`는 FE의 `serverClientId`와 같은 **Web OAuth Client ID**로 설정한다. Android Client ID, 계정 이메일, Client Secret은 해당 값이 아니다. 환경변수가 실제 실행 프로세스/컨테이너까지 전달되는지 확인한다. 개인 `application-local.properties`는 Git/JAR에 포함하지 않는다.
3. 새 Google 검증 의존성은 Gradle에 포함했다. Google 공개 인증서 `https://www.googleapis.com/oauth2/v1/certs`에 대한 DNS/HTTPS 아웃바운드 연결, TLS 인증서, 서버 시간 동기화를 확인한다. DB 포트를 개방하거나 Client Secret을 FE에 전달할 필요는 없다.
4. 로그인 제한은 `AUTH_LOGIN_ACCOUNT_LIMIT=5`, `AUTH_LOGIN_IP_LIMIT=30`, `AUTH_LOGIN_WINDOW_SECONDS=300`, `AUTH_LOGIN_MAX_TRACKED_KEYS=10000`이 기본이다. 현재 프로세스 메모리에 저장되므로 재시작 시 초기화되며 여러 서버 간 공유되지 않는다. 다중 인스턴스에는 별도 공유 저장소가 필요하다.
5. **IP 전달 설정을 확인한 후 배포한다.** 기본 `SERVER_FORWARD_HEADERS_STRATEGY=none`에서는 프록시 IP에 한도가 합산될 수 있다. Tailscale Serve/NGINX/ALB 등 실제 경로를 확인하고, 신뢰하는 프록시 주소만 명시한 Tomcat 설정과 `native` 전략을 함께 적용한다. 외부의 위조 전달 헤더는 경계 프록시에서 제거/재작성한다. 모든 프록시를 무조건 신뢰하지 않는다.
6. 이번 로그인 변경에는 새 SQL/Flyway 마이그레이션이 없다. 기존 인증 테이블·유일 인덱스가 있는 현재 main과 호환되는 DB가 전제이다. 별도 상품/DB 변경은 이 PR에 포함하지 않는다.
7. 승인된 테스트 환경에서 신규/기존 Google 로그인, 기존 이메일 계정의 명시적 연결, 429 대기, 미완료 프로필 제한, Refresh 로그아웃을 확인한다. 실제 Google/Android/AWS 연동은 로컬 H2 테스트로 대체되지 않는다.

## FE 담당자에게

| 요청/상황 | FE 처리 |
|---|---|
| `POST /api/auth/google` | 기존 `{"idToken":"..."}`와 성공 응답 유지. `profileCompleted`로 추가 입력 여부 판단 |
| `GOOGLE_LINK_REQUIRED` | 명시적 기존 비밀번호 확인 흐름 유지. 자동 연결/로그인으로 처리하지 않음 |
| `401 GOOGLE_TOKEN_INVALID` | Google 인증 실패 안내. 서비스 JWT와 Google ID Token을 혼동하지 않음 |
| `503 GOOGLE_LOGIN_UNAVAILABLE` | 연결/설정 문제로 안내. 무조건 계정·서비스 토큰 삭제하지 않음 |
| `POST /api/auth/login` → `429 LOGIN_RATE_LIMITED` | `retryAfterSeconds` 정수 초로 카운트다운, 로그인 버튼 중복 클릭·자동 재시도 방지. 헤더 `Retry-After`도 동일한 초 단위 |
| `403 PROFILE_INCOMPLETE` | 토큰 유지, 추가 프로필 입력 화면으로 이동. `PATCH /api/users/me` 중간 저장 후 `POST /api/users/me/profile/complete` 최종 완료 |
| `POST /api/auth/logout/refresh` | Bearer 없이 `{"refreshToken":"..."}` 전송. 성공 후 로컬 토큰 삭제. Refresh 갱신 API를 먼저 호출할 필요 없음 |
| `GET /api/auth/nicknames/availability?nickname=...` | 본인 닉네임 유지 여부 확인 시 Bearer 전송. 변경 시 확인 상태 초기화, 최종 저장 중복 오류도 처리 |

로그인 429는 토큰 만료가 아니므로 Refresh를 호출하거나 강제 로그아웃하지 않는다. 성공한 로그인도 제한 횟수에 포함된다. 이메일·네트워크 변경으로 제한 해제를 가정하지 않으며 타이머 만료 후 재요청의 서버 응답을 따른다.

Refresh 기반 **폐기**의 재시도와 Refresh **갱신**의 재사용은 다르다. 폐기는 저장 증명이 남아 있으면 반복 200이 가능하지만, 갱신 응답 유실 후 같은 토큰을 반복하면 재사용 탐지로 세션이 폐기될 수 있다. 상세 규칙은 아래 명세를 따른다.

## 문서 및 검증 범위

- 로그인 변경만 분리한 이 브랜치에서 `test bootJar` 성공: **전체 289개 중 283개 통과, 기존 조건부 미실행 6개, 실패/오류 0개**. 개발 원본의 291개 결과와는 제외한 상품 테스트 2개만큼 차이가 있다.
- 공개키 지연/장애, 서명 위조, 동시 Google 가입, 트랜잭션 경계, 로그인 횟수·429, 미완료 프로필 제한, Refresh 로그아웃, 본인 닉네임 검사를 포함한다. JAR에 CSV와 로컬 비밀 설정이 포함되지 않는 것도 확인했다.
- 상세 API 계약: [프론트 인증·프로필 연동 v2](api-spec/frontend-auth-integration-v2.md)
- 요청주소별 명세: [전체 API 명세](api-spec/API_REFERENCE.md), [인증·사용자 API](api-spec/auth-users.md)
- 서버/DB와 분리한 H2 테스트와 실제 RSA 서명 검증기를 사용한다. Google 공개키 공급만 테스트 대역으로 대체한다.
- 실제 모바일 화면, Google 계정 선택 UI, AWS의 HTTPS/프록시 경로는 확인하지 않았다.
- 배포 전 합의할 항목: 공용 NAT 환경의 IP 한도, 다중 서버 여부와 공유 제한 저장소, 실제 Android 빌드의 OAuth package/SHA-1 및 공개/테스터 설정.
