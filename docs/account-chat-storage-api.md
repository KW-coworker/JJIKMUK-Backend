# 계정별 채팅 저장 및 FE 연동 계약

## 변경 범위

로그인 계정별 채팅방과 질문·답변을 저장한다. JWT 소유자만 조회·전송·삭제할 수 있으며,
채팅에서는 관리자도 다른 계정의 채팅방을 조회할 수 없다.
같은 계정의 다른 기기는 동일한 서버 목록을 사용한다.

기존 `POST /api/chat`의 AI 응답 JSON은 유지한다. **`conversationId`와 `clientMessageId`를
함께 보내는 경우에만 저장형 채팅을 사용한다.** 두 필드를 모두 생략한 구형 요청은 기존의
비저장 방식으로 동작한다. 기존 기기 기록은 소유 계정이 불명확하므로 자동 이관하지 않는다.

이 버전은 V18 마이그레이션을 포함하지만 실제 로컬 jjikmuk·AWS·운영 DB에 적용하지 않았다.
백엔드 배포와 FE 연동이 완료되어야 앱에 반영된다. `chatbot_logs`는 AI 진단용이며 이번
대화 저장 테이블과 별개로 유지한다.

## 인증과 공통 응답

- 모든 API에 `Authorization: Bearer {accessToken}`이 필요하다.
- 미로그인 401, 프로필 미완료 계정은 403 `PROFILE_INCOMPLETE`이다.
- 채팅방 소유권 불일치와 없는 채팅방은 모두 404 `CHAT_CONVERSATION_NOT_FOUND`이다.
- 목록·대화 응답의 `data`는 배열이 아니라 **객체**이다. 실제 배열은 `data.items`이다.
- 조회 응답은 `Cache-Control: no-store`이며, 앱의 별도 로컬 캐시는 반드시 userId별로 분리한다.
- 새 채팅 테이블의 시각은 UTC이며 ISO 문자열에 오프셋이 없는 `LocalDateTime` 형식이다.
  예: `2026-11-09T14:00:00`. FE는 UTC로 해석한 뒤 기기 시간대로 변환한다.

## API 목록

| Method | 경로 | 기능 |
| --- | --- | --- |
| POST | `/api/chat/conversations` | 채팅방 생성 |
| GET | `/api/chat/conversations?page=0&size=20` | 내 채팅방 목록 |
| GET | `/api/chat/conversations/{id}` | 내 채팅방 메타데이터 |
| POST | `/api/chat` | 질문·답변 저장 및 AI 응답 |
| GET | `/api/chat/conversations/{id}/messages?afterId=0&limit=20` | 대화 목록 |
| GET | `/api/chat/conversations/{id}/messages/{turnId}` | 개별 질문 처리 상태 |
| GET | `/api/chat/conversations/{id}/messages/by-client-id/{clientMessageId}` | 응답 유실 시 요청 ID로 복구 |
| DELETE | `/api/chat/conversations/{id}` | 채팅방과 포함된 대화 삭제 |

### 채팅방 생성

요청을 보내기 전에 `clientConversationId`를 UUID로 한 번 생성한다. 네트워크 재전송 때에는
같은 UUID와 제목을 사용한다. 같은 계정·UUID이면 기존 채팅방을 반환하며 다른 제목을 보내면 409이다.

```json
{
  "clientConversationId": "38c84b83-3cc8-4cb4-ae3b-6243bdd4466d",
  "title": "간식 성분 질문"
}
```

제목은 선택이며 생략/null은 `새 대화`, 지정 시 앞뒤 공백을 제거한 1~100자이다.
제어 문자는 거부한다. 계정당 최대 1,000개이다. 성공/동일 생성 요청 재전송은 201이다.

```json
{
  "message": "채팅방 생성 성공",
  "data": {
    "id": 123,
    "clientConversationId": "38c84b83-3cc8-4cb4-ae3b-6243bdd4466d",
    "title": "간식 성분 질문",
    "createdAt": "2026-11-09T14:00:00",
    "updatedAt": "2026-11-09T14:00:00"
  }
}
```

### 채팅방 목록

`page`는 0~10000, `size`는 1~50이다. 최종 활동 시각 내림차순, 동률이면 ID 내림차순이다.
`data`는 `{ "items": [...], "page": 0, "size": 20, "hasNext": false }`이다.
활동 중 순서가 바뀔 수 있으므로 FE는 ID로 중복 제거하고 새로고침할 때 첫 페이지부터 갱신한다.

### 저장형 질문 전송

`POST /api/chat`에 다음과 같이 보낸다. 아래 상품 바코드는 예시이므로 실제 조회 결과의 값을 사용한다.

```json
{
  "conversationId": 123,
  "clientMessageId": "a544aef6-13d3-40ec-a0c3-9c79515fa5ae",
  "message": "이 상품의 성분을 설명해줘",
  "barcode": "실제_선택한_상품_식별값",
  "externalAiConsent": false
}
```

- `conversationId`: 생성 응답의 양수 ID. 서버 계정 ID가 아니다.
- `clientMessageId`: 질문별 UUID. 응답 유실로 같은 요청을 재전송하면 같은 UUID와 **동일 본문·쿼리**를 사용한다.
- `message`: 1~4000자, 공백만으로는 보낼 수 없다.
- 상품 선택이 없으면 `barcode`를 생략한다.
- 같은 상품에 대한 후속 질문이면 상품 식별값과 분석 대상 선택도 계속 전달한다.
  생략하여 일반 질문으로 전환하면 다른 상품·대상의 과거 문맥은 자동으로 이어받지 않는다.
- `externalAiConsent`는 기존 계약을 유지하며 실제 사용자 동의만 반영한다.
- 저장형에서는 `chatHistory`/`chat_history`를 생략한다. 비어 있지 않으면 400이다.
- `userId`는 보내지 않는 것을 권장한다. 기존 호환 필드로 보내면 JWT 사용자와 같아야 한다.
- 기존 `profile`/`profiles` 일회성 스냅샷과 분석 대상 쿼리는 이전 검증 계약을 그대로 따른다.
  요청 본문에 들어온 가족 ID를 서버 가족 ID로 간주하지 않는다.
- 서버 가족을 선택한 예: `POST /api/chat?analysisMode=selected&includeSelf=true&familyProfileIds=7,8`.
  해당 가족 ID는 로그인 계정의 가족 API에서 조회한 것이어야 한다.

성공 본문은 기존 AI 응답 그대로이며 `{message,data}`로 한 겹 더 감싸지 않는다.
원본 답변·판정 등 전체 응답 JSON을 저장하므로 FE는 기존 응답 모델을 재사용한다.

추가 응답 헤더:

```text
X-Jjikmuk-Conversation-Id: 123
X-Jjikmuk-Chat-Turn-Id: 456
X-Jjikmuk-Chat-Replayed: false
```

완료된 동일 요청을 다시 보내면 저장된 동일 응답과 turn ID를 반환하고 `Chat-Replayed: true`이다.
AI를 다시 호출하거나 질문을 중복 저장하지 않는다. 이는 과거 답변의 재전송이지 현재 조건에 대한
재평가가 아니다. 조건·상품·질문을 변경했다면 새 UUID로 새 질문을 보낸다.

### 대화 조회와 상태 복구

`afterId`는 마지막으로 받은 turn ID(처음에는 0), `limit`은 1~50이다. ID 오름차순으로 반환한다.
한 항목은 사용자 질문과 AI 응답을 묶은 **한 번의 질문 처리(turn)** 이다.

```json
{
  "message": "대화 조회 성공",
  "data": {
    "items": [
      {
        "id": 456,
        "clientMessageId": "a544aef6-13d3-40ec-a0c3-9c79515fa5ae",
        "message": "이 상품의 성분을 설명해줘",
        "barcode": null,
        "status": "SUCCEEDED",
        "response": { "answer": "실제 AI 응답 JSON이 저장되는 위치" },
        "errorCode": null,
        "createdAt": "2026-11-09T14:00:00",
        "completedAt": "2026-11-09T14:00:02",
        "expiresAt": "2026-11-09T14:02:00"
      }
    ],
    "nextAfterId": 456,
    "hasNext": false
  }
}
```

위 `response` 내용은 구조 예시이며 실제 저장 응답에는 기존 AI 필드들이 포함된다.

| 상태 | FE 처리 |
| --- | --- |
| `PENDING` | 질문 표시 + 처리 중 표시. 개별 상태 API를 간격을 두고 재조회 |
| `SUCCEEDED` | 질문과 `response`의 답변·근거를 표시 |
| `FAILED` | 질문과 실패 표시. `response`는 null. 자동 반복 생성하지 않음 |

`afterId` 방식은 이미 내려받은 PENDING 항목의 상태 변경을 다시 보내주지 않는다.
따라서 대기 중 항목은 turn ID로 조회하고, 응답을 받지 못해 turn ID도 없으면
`messages/by-client-id/{clientMessageId}`로 조회한다. 이 API의 `data`는 위 items의 단일 항목이다.

프로세스 중단으로 PENDING이 남아도 예약 시점부터 2분 뒤에는 FAILED / `CHAT_REQUEST_INTERRUPTED`로
조회된다. 새 요청을 받으면 만료된 처리 기록을 실패로 정리한다. 기존 AI 응답을 복구할 수 없는
실패는 사용자의 재시도 동작으로 **새 UUID**를 발급한다. 새 요청이 AI를 다시 호출할 수 있다.

한 방에서는 한 번에 한 질문만 처리하고 방당 최대 1,000회 질문을 저장한다. 성공 응답 저장 한도는
UTF-8 1MiB이다. 문맥은 동일한 분석 대상·조건·상품 정보·정책의 성공 기록 중 최근 최대 10쌍,
20개 메시지·40,000자까지 사용한다. 실패 기록은 문맥에 넣지 않는다. 과거 답변은 판정 근거가 아니다.

### 삭제

`DELETE /api/chat/conversations/{id}` 성공 시 204이며 본문은 없다. 해당 계정의 방·메시지만 삭제한다.
삭제 후 도착한 AI 응답은 다시 저장하지 않는다. 외부 AI 요청 자체를 취소하거나 이미 발생한
외부 처리 비용을 되돌리는 기능은 아니다. 회원 탈퇴 시 해당 계정의 채팅방·메시지도 함께 삭제한다.
별도 AI 감사 로그 및 외부 서비스 보존 정책은 이 채팅방 삭제 API의 범위가 아니다.

## 오류 처리

| HTTP / code | 처리 |
| --- | --- |
| 400 `VALIDATION_FAILED` / `INVALID_REQUEST_BODY` | ID·필드·길이·클라이언트 이력 확인 |
| 404 `CHAT_CONVERSATION_NOT_FOUND` | 없는 방/메시지 또는 타인 소유. 현재 계정 목록 새로고침 |
| 409 `CHAT_IDEMPOTENCY_CONFLICT` | 같은 UUID에 다른 본문/쿼리를 전송함. 의도한 새 질문이면 새 UUID |
| 409 `CHAT_REQUEST_IN_PROGRESS` | 동일 요청 처리 중. `Retry-After: 2` 이후 상태 조회 |
| 409 `CHAT_CONVERSATION_BUSY` | 같은 방의 다른 질문 처리 중. 이전 처리가 끝날 때까지 대기 |
| 409 `CHAT_MESSAGE_FAILED` / `CHAT_REQUEST_INTERRUPTED` | 실패 상태 확인 후 사용자 동작으로 새 UUID 재시도 |
| 409 `CHAT_CONVERSATION_LIMIT` / `CHAT_MESSAGE_LIMIT` | 방 삭제 또는 새 방 생성 등 한도에 맞게 처리 |
| 502/503 기존 AI 오류 | 실패 표시 및 상태 조회. 저장된 errorCode에 원인을 기록하되 예외 전문은 저장하지 않음 |

질문·선택값 검증이 실패하면 AI 호출과 turn 저장 전에 거부한다. AI 호출 이후 실패는 FAILED turn으로
남긴다. DB 장애로 실패 상태 기록까지 불가능해도 2분 처리 기한이 적용된다. 조회 실패를 빈 목록으로
간주하여 서버 데이터를 지우거나 기기 데이터를 자동 업로드하지 않는다.

## 기존 계정 데이터 연동

| 데이터 | 기존 API | FE 규칙 |
| --- | --- | --- |
| 본인 알레르기·식단 | `GET/PATCH /api/users/me` | 조회한 version 필수. 문자열 ID 계약 유지. 생략=유지, null/빈 값=해제 |
| 가족 | `/api/users/me/family-profiles` | 서버 ID 사용. 수정·삭제는 조회한 version 전달 |
| 분석 대상 토글 | `GET/PUT /api/users/me/analysis-selection` | V20. 별도의 선택 version 사용. 전원 OFF도 저장 |
| 최근 본 상품 | `GET /api/histories/user/{userId}?view=recent&page=0&size=20` | 로그인 응답/내 프로필의 userId 사용. 배열은 data.items |
| 즐겨찾기 | `GET /api/users/me/favorites`, `GET/PUT/DELETE .../{productId}` | 상품 내부 productId 사용, 목록은 data.items |

상품 상세 조회는 로그인 계정에 SCAN을 자동 기록한다. 가족·전원 OFF 분석도 열람 주체의 이력으로
남기므로 앱에서 중복 기록하지 않는다. 즐겨찾기 API가 FAVORITE/UNFAVORITE 행동을 기록하므로
하트 처리 때 이력 이벤트를 중복 전송하지 않는다. 구형 ID 기반 사용자·이력 API의 명시적 관리자
조회 정책은 유지한다. 채팅의 소유권에는 관리자 우회를 허용하지 않는다.

## FE 담당자 작업 순서

2026-11-10 추가: 본인 프로필도 [V19 버전 계약](self-profile-version-contract.md)을 따른다.
조회한 version을 PATCH·PUT·완료 요청에 넣고, 409 충돌 시 다시 조회한 뒤 사용자 확인을 받는다.
V18 채팅 테이블과 V19 프로필 버전은 서로 다른 마이그레이션이다. 2026-11-10 V18~V20을 로컬 MySQL에
검증·적용했다. 운영은 미적용이다. V20은 [가족 토글·가져오기 계약](family-selection-sync-contract.md)을 따른다.
서버 선택을 쓰는 챗봇 요청은 Body profile/profiles를 생략한다. 빈 profiles 배열은 해당 요청 전원 OFF이다.

1. 로그인 성공 후 해당 토큰으로 본인·가족·분석 대상 토글·최근 본 상품·즐겨찾기·채팅방을 조회한다.
2. 계정별 로컬 캐시 키와 Room 데이터에 userId를 포함한다. 채팅방 ID만으로 계정 소유권을 추정하지 않는다.
3. 계정 전환/로그아웃 때 이전 요청·구독을 취소하고 ViewModel 및 선택 상태를 즉시 초기화한다.
4. 응답을 시작한 userId와 현재 userId가 다르면 늦은 응답을 버린다. 이전 계정의 알레르기를 대체값으로 사용하지 않는다.
5. 서버 알레르기 조회 실패와 실제 미선택(null)을 구분한다. 실패 시 재시도 화면을 사용한다.
6. 저장형 채팅방을 만든 뒤 POST /api/chat에 두 ID를 추가한다. 저장형에는 로컬 chatHistory를 보내지 않는다.
7. turn ID/clientMessageId로 낙관적 말풍선과 서버 항목을 병합한다. 동일 응답을 말풍선으로 중복 추가하지 않는다.
8. 기존 기기 기록은 특정 계정으로 자동 귀속하지 않는다. 가족은 사용자가 확인한 항목만 명시적으로 추가한다.
   그 외 기기 채팅/이력 등의 이관은 이번 범위가 아니며 별도 계약이 필요하다.

로그아웃으로 서버 프로필·채팅을 삭제하지 않는다. A → B → A 전환에서 B에는 A의 데이터를 보이지 않고,
A로 돌아왔을 때 서버의 A 데이터를 복원해야 한다. 기기 재설치·다른 기기도 같은 원칙이다.

## AI 담당자와 배포 담당자

- `chat-analysis-v2`, 인증 헤더, 동의 서명 계약은 바꾸지 않는다. 저장용 ID는 AI에 전달하지 않는다.
- 저장형 chat_history는 백엔드의 성공 기록으로 구성된다. 현재 판정·조건은 기존 analysisContext가 기준이다.
- `answer` 문자열을 후속 문맥으로 사용한다. answer가 없거나 문자열이 아니면 그 turn은 문맥에서 제외하지만
  전체 JSON은 조회용으로 보존한다. FE 렌더링 필드와 AI answer 필드는 계속 합의된 계약을 따라야 한다.
- V18은 신규 두 테이블과 FK/인덱스만 생성하며 users·products·chatbot_logs의 기존 행은 수정하지 않는다.
- 실제 배포는 백업 → 복원 스테이징에서 Flyway V18 검증 → 기존 API/새 API 점검 → 승인 후 배포 순서이다.
  운영에 먼저 수동 CREATE를 하고 나중에 Flyway를 실행하여 충돌시키지 않는다.
- 롤백은 구버전 앱/백엔드가 신규 테이블을 사용하지 않는 방식으로 진행하고 저장된 대화 테이블을 즉시 삭제하지 않는다.
- 본 변경에 이미지 구분 메타데이터용 마이그레이션은 포함하지 않았다. 로컬 이미지 작업과 별도이다.
- 방/메시지 한도, 2분 처리 기한, 저장형 opt-in 전환 시점 및 보존기간·기존 기록 이관 UX는 FE·운영과 확인한다.
  현재 자동 보존기간 삭제 작업은 없고, 방 삭제 및 회원 탈퇴를 지원한다.

## 검증 방법

JDK 21에서 `./gradlew test bootJar`를 실행한다. 신규 `AccountChatIntegrationTest`는 실제 JWT·MVC·트랜잭션과
임시 H2 DB·가짜 AI로 계정 격리, 다중 세션, 중복/동시 요청, 실패·중단·삭제 경쟁, 기존 API 계약을 검증한다.
`ChatMigrationTest`는 V18 DDL의 H2 MySQL 호환 모드 실행과 유니크/FK 삭제 동작을 확인한다.
이는 실제 MySQL/Flyway 운영 리허설이나 실제 휴대폰·AWS 통합 시험을 대체하지 않는다.

2026-11-09 로컬 실행 결과: `test bootJar --offline --no-daemon` 성공. 전체 380개 중 373개 통과,
7개 스킵, 실패·오류 0개이다. 새 AccountChatIntegrationTest 16개와 ChatMigrationTest 1개는 모두 통과했다.
스킵은 별도 원본 CSV 또는 외부 평가셋이 필요한 기존 테스트이며, 이번 계정 격리 시험은 스킵하지 않았다.
실제 로컬 MySQL 스키마와 데이터, AWS는 이 시험에서 변경하지 않았다.

후속 2026-11-10: 로컬 전체 백업→복제 MySQL의 V18~V20/API 검증→로컬 적용/데이터 보존/기동 검증을 완료했다.
최신 main 통합 후 전체 428건 중 420건 통과/조건부 8건 제외, 실제 복제 MySQL HTTP 검증 62항목 통과이다.
AWS/운영과 기존 전달 ZIP은 변경하지 않았다. [배포 절차 및 상세 결과](account-state-v18-v20-deployment.md) 참조.
