# OCR 중계 API 및 인증 v2 호환

2026-11-02: 기존 운영 연동용 OCR 코드를 main 기반 기능 브랜치로 가져온 변경이다.
PR 생성은 main 병합이나 AWS 배포 완료를 의미하지 않는다. OCR 모델과 Python 서버는 별도 서비스이다.

## 구성과 기본 상태

| 파일 | 역할 |
|---|---|
| `OcrController.kt` | 일반 스캔·실험실 요청 형식과 이미지 개수 검사 |
| `OcrProxy.kt` | 설정된 OCR 서버 호출, 응답 크기·시간·형식 검사 |
| `OcrGuard.kt` | 활성화 상태·실험실 허용 계정·요청 크기·동시 호출 검사 |
| `OcrConfiguration.kt` | 기존 회원 JWT 필터 연결과 설정 등록 |

네 파일은 Codex가 기존 운영 연동 과정에서 작성한 코드이며, 이번 PR은 이를 저장소에 편입한다.
회원가입·로그인·JWT 발급 구현을 복제하거나 교체하지 않는다. DB 마이그레이션·의존성 추가도 없다.
설정이 없으면 OCR은 기본 비활성화되며, 다른 API는 기존 보안 체인을 사용한다.

## 운영 설정

| 환경변수 | 기본값 | 용도 |
|---|---|---|
| `OCR_PROXY_ENABLED` | `false` | 일반·실험실 중계 활성화 |
| `OCR_PROXY_BASE_URL` | 빈 값 | OCR 서비스 origin. 경로·query·사용자정보 금지 |
| `OCR_PROXY_SERVICE_TOKEN` | 빈 값 | OCR 서버와 공유하는 내부 토큰, 최소 32자 |
| `OCR_DEBUG_ENABLED` | `false` | 실험실 추가 허용 |
| `OCR_DEBUG_ALLOWED_EMAILS` | 빈 값 | 쉼표로 구분한 실험실 허용 회원 이메일 |

Spring의 `ocr.proxy.*`, `ocr.debug.*` 속성으로도 설정할 수 있다.
주소는 HTTPS 또는 사설/loopback IPv4의 HTTP만 허용한다. 실제 주소·토큰·회원 목록은 배포 설정에서 공급하고 Git에 커밋하지 않는다.
내부 토큰은 `X-OCR-Service-Token`으로 서버 간에만 전달한다. 앱의 Bearer JWT는 OCR 서버에 전달하지 않는다.

## 인증 및 로그인 호환

두 경로는 기존 `JwtAuthenticationFilter`를 재사용한다. 인증 주체는 로그인된 회원 ID(Long)이다.

- LOCAL·GOOGLE·LOCAL_AND_GOOGLE 계정 모두 동일한 회원 Access 토큰으로 일반 OCR을 사용한다.
- Google의 `idToken` 자체를 OCR에 보내면 안 된다. Google 로그인 API가 발급한 앱 Access 토큰을 사용한다.
- 만료, tokenVersion 불일치, 삭제된 회원, 잘못되거나 만료·취소된 세션은 기존 인증 정책대로 거절한다.
- 프로필 미완료 계정은 `403 PROFILE_INCOMPLETE`이다. 프로필 완료 후 사용한다.
- Refresh와 로그아웃은 main의 세션 서비스를 그대로 사용한다.
- 일반 OCR에는 특정 이메일 제한이 없다. 실험실만 활성화 설정과 DB에서 조회한 회원 이메일 목록을 모두 검사한다.

## 요청

### `POST /api/ocr`

`Authorization: Bearer {앱 Access 토큰}`과 multipart/form-data의 `image` 파일 하나를 보낸다.
JPEG 또는 PNG, 최대 10 MiB이다. 다른 파일·폼 필드·모델 선택은 허용하지 않는다.
HTTP 클라이언트가 multipart boundary를 생성하도록 한다.

중계는 OCR 서버의 `/ocr`로 전달한다. 모델 선택·이미지 인식·상품명 선택은 OCR 서비스의 기존 구현을 사용한다.
DB 검색을 자동 수행하지 않으며, 앱은 결과의 `data.searchKeyword`를 별도 검색 API에 전달한다.

### `POST /api/ocr/debug`

같은 로그인 인증에 실험실 계정 제한이 추가된다. 다음 중 한 형태만 사용한다.

1. `image` 파일 하나 + 선택적 `model`
2. 이전 OCR 서버가 발급한 `snapshot` + 필수 `model` (이미지 없음)

`model` 허용값: `gpt-6-luna`, `gpt-6.1-terra`, `gpt-6.1-sol`.
이 값은 현재 실험실 계약이며 모델 가용성·과금은 OCR 서비스에서 관리한다.
이 중계가 세 모델을 자동으로 모두 호출하지 않는다. 선택값을 한 요청으로 전달한다.
snapshot의 서명·유효성 최종 검증도 OCR 서비스 책임이며, 중계는 최대 330,000자와 요청 조합을 검사한다.

## 응답과 오류

성공 시 OCR 서버의 `{ "message": "...", "data": { ... } }` 구조를 검증해 반환한다.
일반 응답의 `data.status`는 `OK`, `NO_TEXT`, `NO_SEARCH_KEYWORD`이다.
`OK`에는 2~100자의 `searchKeyword`가 필요하다. 중계는 용량을 새로 추출하거나 `totalWeight`를 생성하지 않는다.
실험실 응답은 `schemaVersion=ocr-debug-v1`, `ocr`·`selector` 객체와 `OK`·`NO_TEXT`·`FAILED` 상태를 포함한다.
실험실 HTTP 200이라도 `data.status=FAILED`이면 OCR/selector 처리 성공이 아니다.

OCR 자체 오류는 아래 구조이며, JWT 필터에서 거절한 오류는 기존 인증 API의 `{status,code,message}` 구조이다.

```json
{"error":{"requestId":"...","code":"OCR_DISABLED","message":"OCR request could not be completed; do not automatically retry."}}
```

| HTTP | 주요 OCR 코드 | 처리 |
|---|---|---|
| 401 | `AUTHENTICATION_REQUIRED` | 로그인·토큰 확인 |
| 403 | `OCR_DEBUG_FORBIDDEN` | 실험실 활성화·허용 계정 확인 |
| 405 | `METHOD_NOT_ALLOWED` | POST 사용 |
| 413/415/422 | `IMAGE_TOO_LARGE`, `INVALID_CONTENT_TYPE`, `INVALID_IMAGE_TYPE`, `INVALID_IMAGE`, `INVALID_REQUEST`, `INVALID_DEBUG_MODEL` | 요청 수정 |
| 429 | `OCR_BUSY`, `RATE_LIMITED` | `Retry-After: 3`; 사용자에게 대기 안내 |
| 502 | `OCR_UPSTREAM_FAILED`, `INVALID_OCR_RESPONSE` | 내부 연결·응답 점검 |
| 503 | `OCR_DISABLED`, `OCR_NOT_CONFIGURED`, `OCR_INTERRUPTED` | 설정·서비스 상태 확인 |
| 504 | `OCR_TIMEOUT_OUTCOME_UNKNOWN` | 처리·과금 완료 여부 불명, 자동 재시도 금지 |

OCR 서비스의 일부 비정상 HTTP 상태는 해당 상태와 `OCR_UPSTREAM_REJECTED`로 반환한다.
연결 10초, 요청 130초, 전체 응답 대기 135초, 응답 본문 1 MiB 상한이다. 리다이렉트·자동 재시도는 하지 않는다.
로그는 요청 ID·상태·소요시간이며 토큰·이미지·OCR 문구를 출력하지 않는다.

## 기존 기능에 미치는 영향과 검토할 제한

- **multipart 파서 전역 한도**: 기존 설정 파일의 2 MB/3 MB 대신 Bean이 파일 10 MiB, 요청 10 MiB+64 KiB를 적용한다.
  프로필 사진의 `ProfilePhotoService`는 별도로 2 MiB를 검사하므로 사진 저장 한도는 유지된다.
  다만 큰 사진 요청이 애플리케이션 검사에 도달할 수 있다는 차이는 있다. 프록시/웹서버 업로드 한도는 별도이다.
- **호출 제한**: 백엔드 프로세스 전체에서 일반·실험실을 합쳐 동시 1건, 시작 간격 3초이다.
  회원별 또는 여러 서버에 걸친 분산 제한은 아니다. 기존 시험 운영 동작을 유지한 것이며 대규모 운영 정책은 별도 검토한다.
- 이미지 헤더·MIME 검사는 실제 이미지 디코딩 성공 보장이 아니다. OCR 서버의 이미지 검증도 필요하다.
- 이 PR은 챗봇 v2·동의 서명·OCR 모델 교체·서버 배포를 포함하지 않는다. 전체 main 배포 가능 여부는 별도로 확인해야 한다.

## 검증 방법과 범위

`./gradlew test bootJar`로 전체 회귀 검사를 수행한다. OCR 테스트는 H2와 loopback 모의 OCR 서버를 사용한다.
일반/Google/연결 계정, 프로필 미완료→완료, 만료 토큰, 로그아웃, Refresh,
tokenVersion 변경, 회원 삭제, 세션 소유권·만료, 익명 차단, 실험실 허용 목록,
정상 multipart 요청과 내부 토큰, 프로필 사진 2 MiB 제한을 검사한다.
실제 Google OAuth 로그인, 실제 OCR/LLM 호출, 운영 DB·AWS 배포, 앱 화면은 이 로컬 검사에 포함되지 않는다.
