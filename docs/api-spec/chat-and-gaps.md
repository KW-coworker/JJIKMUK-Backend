# 챗봇 중계 API와 현재 구현의 확인 필요 사항

[전체 목록](README.md). 이 문서는 구현된 동작과 아직 보완되지 않은 부분을 구분하기 위한 부록이다.

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
| Query | 없음 |
| 성공 | 200 OK |
| 배포 의존성 | 현재 코드에서 `http://localhost:8000/chat`에 접근 가능해야 함 |

### Body

| 필드 | 타입 | 필수·설명 |
|---|---|---|
| userId | integer/null | 선택 사용자 ID |
| barcode | string/null | 선택 상품 바코드 |
| message | string | 필수 질문 |
| chatHistory | array | 생략 시 [] |
| chatHistory[].role | string | 필수. 현재 DTO는 enum 제한 없음 |
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

백엔드가 AI 응답을 String으로 받아 그대로 반환한다. `{message,data}` 공통 포맷이나 `answer` 필드를 백엔드에서 보장하지 않으며 AI 서비스 응답 계약에 따라 실제 본문이 결정된다. 현재 코드만으로 고정된 성공 JSON이나 Content-Type을 명세에 만들어 넣지 않는다.

기존 사용자를 못 찾으면 profile=null, 상품을 못 찾으면 product=null로 AI에 전달한다. 해당 이유만으로 반드시 404를 반환하는 API가 아니다. AI 연결 실패 등은 공통 500이고, 미인증은 공통 401이다.

**연동 전 확인:** 현재 ChatController는 토큰 사용자와 Body의 userId가 같은지 검사하지 않고, userId 생략 시 로그인 사용자 ID를 자동 적용하지도 않는다. 일반 상품·추천 API의 사용자 검증 규칙과 동일하다고 기재하면 안 된다. 이 경로의 본인 식별·권한 검증 보완과 AI 응답 스키마 확정은 별도 작업이 필요하다. 현재 상태를 신규 프론트 개인정보 연동의 확정 계약으로 사용하지 않는다.

## 목록에 잘못 추가하지 않아야 할 경로

현재 Spring Backend에는 다음 경로가 구현되어 있지 않다.

- `PATCH /api/users/me`
- Refresh Token 발급·갱신 API
- 이메일 인증 완료 증명의 남은 시간을 별도로 조회하는 API
- 프로필 사진 서버 업로드 API, 가족 프로필 서버 CRUD API
- `GET /api/products/filter`의 알레르기 제외 파라미터, 알레르기 분류 상태 파라미터
- Spring 서버의 `/health`, `/ocr`, `/products/barcode/{barcode}`, `/products/report-number/{report_number}`

마지막 묶음은 별도 AI/OCR 서비스에서 제공할 수 있으므로 담당 서비스의 실제 코드·배포 주소로 명세를 관리한다. Spring의 `/api/products/{barcode}`나 `/api/chat`과 경로를 혼용하지 않는다.

## 프론트 연동 시 확인할 현재 차이

| 항목 | 실제 상태·반영할 설명 |
|---|---|
| 성공 응답 래핑 | 로그인·Google은 최상위 token/userId, 상품·프로필 등은 data 사용, 챗봇은 AI 응답 직접 반환 |
| 본인 ID 키 | 로그인은 userId, 프로필은 id |
| 오류 구조 | 상품 직접 검증 오류에는 code가 없을 수 있음. 일반 업무 오류에는 REQUEST_FAILED 사용 |
| 숫자 Query/Path 타입 오류 | 전용 핸들러 미구현으로 500이 될 수 있음. 정상적인 400 계약으로 확정하지 않음 |
| 프로필 PATCH | 회의 제안일 뿐 아직 미구현. 현재 PUT은 선택 필드 생략 시 해제 |
| 비밀번호 변경 field | 새 비밀번호 검증 오류에도 field=password가 사용됨 |
| 인증시간 | 로그인은 Instant, OTP·행동 이력은 시간대 없는 LocalDateTime |
| 첫 화면 추천 | PASS·건강 조건 유지, specialDiet 선호는 완화 가능, 제한된 후보 탐색 |
| 대체 추천 | UNKNOWN 대안은 fallbackItems로 분리. 사전 후보 자체가 없으면 404 |
| 알레르기 미검출 | 상품 분류 상태이며 사용자 안전성 PASS와 다름 |
| 알레르기 미등록 | 현재 개인 판정 PASS가 될 수 있지만 모든 사용자에 대한 안전 증명이 아님 |
| 결측 영양 비율 | 현재 percent=0일 수 있으므로 원 영양 필드 null 확인 |
| 이력 기록 | 단건 상품 GET도 로그인 시 SCAN 이력을 추가함 |
| 추천 피드백과 행동 이력 | 다른 저장·사용 목적. 피드백이 행동 이력을 자동 생성하지 않음 |
| 실서버 반영 | 이 문서는 코드 기준. 서버 담당자는 배포 커밋·Flyway·DB·메일·Google 설정을 별도로 확인 |

이 표는 명세만으로 이미 해결된 것으로 표시하지 않는다. 이번 작업에서는 API 명세만 작성했다.
