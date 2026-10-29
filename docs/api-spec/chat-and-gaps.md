# 챗봇 중계 API와 현재 구현의 확인 필요 사항

[전체 목록](README.md). 2026-10-28 챗봇 변경의 상세 계약은 [챗봇 공통 분석 판정 계약](chat-analysis-contract-v1.md)이 우선한다. 아래는 구현된 동작과 아직 보완되지 않은 부분의 요약이다.

## C01. AI 챗봇 중계

```http
POST /api/chat
Authorization: Bearer {token}
Content-Type: application/json
```

| 항목 | 내용 |
|---|---|
| 기능 | 사용자·상품 데이터를 구성해 AI 서버 /chat로 전달 |
| 인증 | 서비스 JWT 필요 |
| Query | analysisMode / includeSelf / familyProfileIds. 상품 API와 동일한 선택 규칙 |
| 성공 | 200 OK |
| 배포 의존성 | chat.ai.url의 AI 서비스가 chat-analysis-v1 및 응답 확인 헤더를 지원해야 함 |

### Body

| 필드 | 타입 | 필수·설명 |
|---|---|---|
| userId | integer/null | 호환용. 생략 권장, JWT 본인과 같은 ID만 허용 |
| barcode | string/null | 선택 상품 바코드 |
| message | string | 필수 질문 |
| chatHistory | array | 생략 시 [] |
| chatHistory[].role | string | user/assistant만 허용 |
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

백엔드는 AI 응답의 계약 버전·contextId 확인 헤더와 JSON object 여부를 검증하고 application/json으로 본문을 전달한다. answer 등의 성공 필드명은 아직 강제하지 않는다.

상품 생략 시에만 상품 없는 일반 질문을 전달한다. 입력한 상품이 없거나 선택한 가족에 접근할 수 없으면 404이며 AI 호출을 하지 않는다. AI 연결 실패는 503, 응답·계약 문제는 502다.

**연동 전 확인:** JWT 본인 검증, 가족 합산 조건, 상품 단건과 동일한 판정·근거 전달을 구현했다. 관리자도 타인 userId 지정은 불가하다. AI 서비스의 새 계약 수용과 공동 배포가 필요하며, 구형 AI가 확인 헤더를 주지 않으면 502다. 설명 문장 검증, 개별 가족 판정, 용량 옵션 집계, 검색·추천 API 호출 연동은 별도 합의 대상이다.

## 목록에 잘못 추가하지 않아야 할 경로

현재 Spring Backend에는 다음 경로가 구현되어 있지 않다.

- 이메일 인증 완료 증명의 남은 시간을 별도로 조회하는 API
- `GET /api/products/filter`의 알레르기 제외 파라미터, 알레르기 분류 상태 파라미터
- Spring 서버의 `/health`, `/ocr`, `/products/barcode/{barcode}`, `/products/report-number/{report_number}`

마지막 묶음은 별도 AI/OCR 서비스에서 제공할 수 있으므로 담당 서비스의 실제 코드·배포 주소로 명세를 관리한다. Spring의 `/api/products/{barcode}`나 `/api/chat`과 경로를 혼용하지 않는다.

## 프론트 연동 시 확인할 현재 차이

| 항목 | 실제 상태·반영할 설명 |
|---|---|
| 성공 응답 래핑 | 로그인·Google은 최상위 token/userId, 상품·프로필 등은 data 사용, 챗봇은 계약 확인된 AI JSON object 반환 |
| 본인 ID 키 | 로그인은 userId, 프로필은 id |
| 오류 구조 | 상품 직접 검증 오류에는 code가 없을 수 있음. 일반 업무 오류에는 REQUEST_FAILED 사용 |
| 숫자 Query/Path 타입 오류 | 400 VALIDATION_FAILED와 해당 field 반환 |
| 프로필 PATCH | v2에서 구현. 생략 유지/null·빈 문자열 해제. PUT은 전체 교체 유지 |
| 비밀번호 변경 field | 새 비밀번호 검증 오류에도 field=password가 사용됨 |
| 인증시간 | Access/Refresh는 Instant, OTP 응답은 offset 포함. 행동 이력은 기존 LocalDateTime |
| 첫 화면 추천 | PASS·건강·specialDiet 필수 조건 유지, 완화 없음, 제한된 후보 탐색 |
| 대체 추천 | UNKNOWN 대안은 fallbackItems로 분리. 사전 후보 자체가 없으면 404 |
| 알레르기 미검출 | 상품 분류 상태이며 사용자 안전성 PASS와 다름 |
| 알레르기 미등록 | 현재 개인 판정 PASS가 될 수 있지만 모든 사용자에 대한 안전 증명이 아님 |
| 결측 영양 비율 | 현재 percent=0일 수 있으므로 원 영양 필드 null 확인 |
| 이력 기록 | 단건 상품 GET의 SCAN은 본인 분석일 때만 추가. 가족/none을 본인 취향으로 기록하지 않음 |
| 추천 피드백과 행동 이력 | 다른 저장·사용 목적. 피드백이 행동 이력을 자동 생성하지 않음 |
| 실서버 반영 | 이 문서는 코드 기준. 서버 담당자는 배포 커밋·Flyway·DB·메일·Google 설정을 별도로 확인 |

사진·가족·갱신·명시적 Google 연결·분석 대상 API는 [프론트 연동 v2](frontend-auth-integration-v2.md), 챗봇은 [공통 분석 판정 계약](chat-analysis-contract-v1.md)을 따른다. 실제 서버 배포는 별도 확인 사항이다.
