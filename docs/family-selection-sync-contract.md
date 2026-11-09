# 가족 토글 서버 동기화와 기존 기기 가족 정보 가져오기

기준: 2026-11-10. **백엔드 구현 및 격리 테스트용 계약이다. Android 코드와 실제 MySQL/AWS는 변경하지 않는다.**
V20이 필요하다. 이전 문서의 ‘분석 대상 생략 시 항상 본인’ 및 ‘토글 동기화 미정’ 설명을 이 문서로 대체한다.

## 1. 확정 정책

| 구분 | 확정 내용 |
| --- | --- |
| 가족 정보 | 계정별 서버 저장. 기존 가족 CRUD API 유지 |
| 토글 ON/OFF | 본인 포함 계정별 서버 저장. 같은 계정의 다른 기기도 재조회 시 동일한 선택을 받음 |
| 미설정 계정 | 기존 동작과 호환되도록 본인 ON, 가족 모두 OFF. 기존 가족이 있어도 자동 ON 하지 않음 |
| 신규/가져온 가족 | 가족 생성과 토글 변경은 별개. 기본 OFF이며 사용자가 다시 선택해야 분석 대상이 됨 |
| 전원 OFF | 유효한 저장 상태. 분석은 NOT_EVALUATED이며 PASS/UNKNOWN으로 바꾸지 않음 |
| 기존 기기 가족 정보 | 로그인·앱 업데이트·목록 조회 때 자동 이관하지 않음. 사용자가 확인한 항목만 명시적으로 추가 |
| 계정 전환 | 서버 데이터는 유지하고 기기의 이전 계정 상태·진행 중 요청은 해제. 새 계정 데이터를 재조회 |
| 동시 수정 | 조회 version과 다른 요청은 409. 마지막 저장값을 무조건 덮는 방식이 아님 |

서버 동기화는 GET/PUT 기반이다. 실시간 push/WebSocket은 구현하지 않았다. 로그인, 화면 복귀,
분석 시작 전 필요한 시점에 다시 조회하고, 다른 기기의 변경을 자동 덮어쓰지 않는다.
개인정보 조회 실패를 빈 목록/전원 OFF/본인 ON으로 간주하지 말고 오류와 재시도로 처리한다.

## 2. 새 API

두 API 모두 JWT 인증이 필요하며 소유자는 JWT로 정한다. 미완료 계정은 `403 PROFILE_INCOMPLETE`다.
Body에 userId/ownerId를 받지 않는다. 응답은 `Cache-Control: no-store`다.

### GET /api/users/me/analysis-selection

Body와 Query 없음. 설정을 처음 조회해도 DB 행이나 가족을 만들지 않는다.

```json
{
  "message": "분석 대상 조회 성공",
  "data": {
    "includeSelf": true,
    "familyProfileIds": [],
    "version": 0,
    "configured": false,
    "mode": "self"
  }
}
```

- `includeSelf`: 본인 토글.
- `familyProfileIds`: ON인 **서버 가족 ID**만 담는 정수 배열. OFF인 가족은 배열에 없다.
- `version`: 이 계정의 분석 대상 선택 버전. 본인 프로필 version 및 가족별 version과 **별개**이다.
- `configured`: 사용자가 선택을 저장했는지 여부. false는 서버 설정 행이 없는 최초 기본값이다.
- `mode`: 선택 가족이 있으면 selected, 가족 없이 본인만 켜면 self, 전원 OFF면 none.

### PUT /api/users/me/analysis-selection

선택 전체를 교체하므로 아래 세 필드가 모두 필수다. Query 없음.
먼저 가족 목록을 조회해서 실제 서버 ID를 확인한다. 예시의 41, 42를 그대로 보내지 않는다.

```json
{
  "version": 0,
  "includeSelf": true,
  "familyProfileIds": [41, 42]
}
```

```json
{
  "message": "분석 대상 저장 성공",
  "data": {
    "includeSelf": true,
    "familyProfileIds": [41, 42],
    "version": 1,
    "configured": true,
    "mode": "selected"
  }
}
```

전원 OFF 예시: `{"version":1,"includeSelf":false,"familyProfileIds":[]}`.
정수 ID 최대 20개, 중복은 제거하고 정렬한다. null·숫자 문자열·소수·0/음수 ID는 거부한다.
이름·알레르기·로컬 ID·isActive 값을 이 API로 저장하지 않는다. 가족 상세는 기존 CRUD로 수정한다.
계정에 속하지 않거나 삭제된 가족은 `404 FAMILY_NOT_FOUND`이며 일부만 저장하지 않는다.
기기의 임의 ID가 우연히 서버 ID와 같을 수 있으므로, 반드시 서버 생성 응답/조회 목록의 ID를 사용한다.

### 충돌과 실패

| 응답 | FE 처리 |
| --- | --- |
| 400 VALIDATION_FAILED | field에 해당하는 입력/직렬화 수정. 실패 시 저장값과 버전 유지 |
| 401 | 세션 갱신/재로그인 정책 적용 |
| 403 PROFILE_INCOMPLETE | 프로필 완료 후 재시도 |
| 404 FAMILY_NOT_FOUND | 가족·토글 재조회, 사라진 선택 안내. 다른 사람으로 자동 치환 금지 |
| 409 ANALYSIS_SELECTION_VERSION_CONFLICT | 가족·토글 재조회 후 변경 내역을 사용자에게 보여주고 확인 받아 다시 저장 |

```json
{
  "status": 409,
  "code": "ANALYSIS_SELECTION_VERSION_CONFLICT",
  "message": "다른 기기에서 분석 대상이 변경되었습니다. 다시 조회한 뒤 선택해주세요.",
  "field": "version"
}
```

수락한 PUT은 동일 값 저장이어도 version을 1 올린다. 응답을 못 받은 PUT을 이전 version으로
반복 전송하거나 최신 version만 끼워 무조건 재시도하지 않는다. GET으로 실제 저장 상태를 확인한다.
빠른 연속 토글 변경은 요청을 직렬화하거나 UI에서 저장 버튼으로 묶어 처리한다.

## 3. 상품·검색·추천·이력·챗봇 공통 적용

공통 AnalysisSelectionService를 사용하는 API에 다음 우선순위를 적용한다.

1. 명시한 `analysisMode=self/selected/none`은 **그 요청만의 대상 선택**이다. 서버 토글을 저장하지 않는다.
2. 로그인 요청에서 analysisMode/includeSelf/familyProfileIds를 모두 생략하면 서버 저장 선택을 사용한다.
3. 저장 선택이 아직 없으면 본인만 분석한다. 공개 비로그인 조회는 none이다.

`includeSelf`나 `familyProfileIds`만 단독으로 보내지 않는다. 요청별 선택에는 analysisMode가 필요하다.
전원 OFF 저장 후 아무 선택 파라미터 없이 상품을 조회하면 분석 status는 NOT_EVALUATED다.
가족을 포함한 이력은 본인 개인화 선호로 학습하지 않으며, 실제 열람 이력은 로그인 계정에 유지한다.
선택에는 ID만 저장한다. 분석 시 가족의 **현재 서버 이름·조건**을 읽으므로 토글 저장 당시 조건을 고정하지 않는다.

영향 경로: 상품 상세·ID 상세·용량 옵션·search·filter, safe-recommendations, 대체 추천,
선택 정보를 사용하는 행동 이력, `/api/chat`의 서버 프로필 경로.
상품 응답의 `analysis.selection`, 추천 응답의 `analysisSelection`은 실제 적용한 대상이다.
FE는 이 값이 화면의 대상과 일치하는지 확인한다. 대상이 바뀌면 예전 분석 결과와 추천 cursor를 폐기하고 새로 요청한다.

### 챗봇

서버 토글을 따르는 요청에서는 Body의 `profile`/`profiles`를 **생략**한다.

```json
{
  "message": "이 상품의 주의할 성분을 설명해줘",
  "barcode": "실제상품바코드",
  "externalAiConsent": true
}
```

externalAiConsent는 실제 사용자 동의를 받은 경우에만 true로 전달한다. 저장형 채팅은 기존 계약대로
conversationId/clientMessageId를 추가한다. 이 변경이 외부 AI 동의나 저장형 채팅을 자동 활성화하지 않는다.

- BE가 저장 선택으로 현재 서버 조건을 조회하고 기존 `chat-analysis-v2`의 profile/profiles 및
  analysisContext에 전달한다. AI 계약 버전, 판정 우선순위와 확인 응답 규칙은 변경하지 않는다.
- 구형 Body profile/profiles는 호환을 위해 **요청 전용 입력**으로 남는다. 가족/토글 서버 저장으로 이관하지 않는다.
- `profiles: []`는 서버 선택 사용이 아니라 **해당 요청의 전원 OFF**다. 서버 동기화 전환 후 빈 배열을 기본 전송하지 않는다.
- Body 프로필과 Query 선택을 혼용하면 기존처럼 400이다. AI는 저장 토글을 따로 추정하지 않고 전달받은 analysisContext만 따른다.

## 4. 기존 기기 가족 정보 가져오기: 자동 이관 금지

초기 배포에서는 자동 이관 작업/백필/API 호출을 만들지 않는다. 필요할 경우 사용자가 선택한 항목을
기존 `POST /api/users/me/family-profiles`로 하나씩 추가하는 확인형 화면을 FE에 구현한다.

1. 현재 로그인 계정을 표시하고 서버 가족 목록을 먼저 읽는다. 읽기에 실패하면 업로드를 진행하지 않는다.
2. 자동 팝업 후 업로드하지 않고, 사용자가 ‘기기의 가족 정보 가져오기’를 명시적으로 선택하도록 한다.
3. 기본 체크는 모두 해제한다. 이름·관계·이모지·알레르기·식이조건을 검수하고 필요한 항목만 체크한다.
   다른 계정 소유로 확인되는 캐시는 후보에서 제외한다. 소유자가 불명확한 구형 자료는 별도 안내·동의가 필요하다.
4. 체크한 항목만 생성한다. nickname/relation/emoji와 기존 문자열 ID 계약의 조건 필드만 전달한다.
   계정의 본인 프로필을 가족으로 복제하거나, 로컬 ID/ownerId/isActive/version을 생성 Body에 넣지 않는다.
5. 기존 서버 가족을 이름으로 자동 병합·덮어쓰기하지 않는다. 같은 이름도 다른 사람일 수 있다.
   중복으로 보이는 항목은 사용자가 기존 항목을 유지할지 새로 만들지 확인한다. 계정당 최대 20명이다.
6. 생성 응답의 서버 ID와 가족 version을 계정별로 저장한다. 가져온 가족은 OFF다.
   사용자가 토글을 다시 선택했을 때에만 최신 선택 version으로 PUT 한다. 과거 ON/OFF를 복사하지 않는다.
7. 가져오기 취소·실패 시 원본 로컬 자료를 자동 삭제하지 않는다. 성공 항목과 실패 항목을 나눠 표시한다.

**주의:** 기존 가족 생성 POST는 멱등 import API가 아니다. 자동 재시도/백그라운드 전체 재전송을 하지 않는다.
응답 유실 시 먼저 서버 목록을 다시 확인하고 사용자 확인을 받는다. 이름 일치만으로 생성 성공을 확정하지 않는다.
무인 대량 이관이나 정확한 재시도가 필요해지면 별도 idempotency key 기반 import 계약을 추가해야 한다.
이번 변경은 자동 이관 방지 정책과 서버 저장 기능을 제공하며, 사용자 동의 화면 자체는 FE 작업이다.

## 5. 삭제·계정 전환·기기 동기화

- 가족 삭제는 기존 가족 version을 검사한다. 성공 시 선택된 ID도 같은 트랜잭션에서 제거한다.
  선택이 실제 바뀐 경우에만 선택 version을 1 올린다. 마지막 가족 삭제 후 본인을 자동 ON 하지 않는다.
- 가족 수정은 가족 version만 바꾸며 선택 version은 유지한다. 본인 프로필 version도 별개이다.
- 가족 생성·수정·삭제 후 가족 목록과 선택을 재조회하고 상품/챗봇 분석 결과를 갱신한다.
- A → B → A 전환 시 A 가족/선택 캐시를 B에게 표시하거나 B 서버에 업로드하지 않는다.
  요청 시작 userId와 응답 시 현재 userId가 다르면 응답을 버린다. 동일 계정의 오래된 조회 응답도 최신 version을 덮지 않게 한다.
- 로그아웃은 서버 토글을 삭제하지 않는다. 회원 탈퇴는 해당 계정의 선택/선택 가족 연결을 삭제한다.
- 저장 실패 시 로컬 UI를 성공으로 확정하지 않는다. 갱신된 토글과 오래된 분석 결과를 함께 보여주지 않는다.

## 6. 배포 및 검증

- V20은 `account_analysis_selections`, `account_analysis_selection_families`만 추가한다.
  users·family_profiles·상품 데이터의 기존 행을 백필하지 않는다. 기존 기기 자료도 읽지 않는다.
- 2026-11-10 백업·복제 검증 후 로컬 MySQL V18~V20을 적용했다. AWS/운영은 미적용이다.
  기존 전달 ZIP/덤프는 갱신하지 않았다. [최종 결과·배포 안내](account-state-v18-v20-deployment.md)를 따른다.
- 서버 담당자는 DB 백업 → 별도 복원 DB에서 미적용 V18/V19/V20 순서 검증 → FE 계약 확인 → 승인 후 배포한다.
  Flyway 이력 확인 없이 테이블만 수동 생성하지 않는다. V19는 본인 수정 요청에도 version이 필수라 FE를 함께 확인한다.
- 기존 FE가 매번 analysisMode=self 또는 Body profile/profiles를 보내면 저장 토글이 적용되지 않는다.
  새 API 배포만으로 APK가 자동 연동되는 것은 아니다. FE 전환을 별도 확인한다.
- 롤백 시 구버전 BE는 저장 선택을 무시할 수 있다. 선택 가족을 보호 대상으로 안내한 상태에서 조용히 롤백하지 말고
  해당 분석 기능을 안내/제한한 후 조율한다. 사용자 선택 테이블을 삭제하여 롤백하지 않는다.

검증: `./gradlew test --tests '*AccountAnalysisSelection*'`, `./gradlew test bootJar`.
H2에서 실제 JWT·MVC·트랜잭션으로 계정 격리, 최초 동시 저장, stale version,
가족 삭제 경쟁, 전원 OFF, 상품/추천/챗봇 일치, 자동 이관 없음, 탈퇴 정리를 검사한다.
V20 DDL은 H2 MySQL 호환 모드에서 별도 검증한다. 이는 실제 MySQL 복원 검증을 대체하지 않는다.

2026-11-10 최초 코드 구현 시점의 실행 결과:

- 신규 테스트 16건 통과(통합 15건 + V20 DDL 1건).
- 전체 `test bootJar --offline --no-daemon`: 407건 중 400건 통과, 기존 조건부 7건 제외, 실패/오류 0건.
- JDK 21 실행 파일 빌드 및 `git diff --check` 성공.
- 실제 로컬 MySQL·AWS·운영 DB 변경, Git 커밋/push, Android 수정은 하지 않았다.

후속 DB 적용 검증: MySQL 8.0.44 전체 백업/복제 대조 후 V18~V20 적용·반복 실행 0건을 확인했다.
실제 MySQL의 동시 토글 저장, 계정 분리, 상품/챗봇 선택 반영, 가족 삭제 등 62항목을 통과하고
로컬 원본도 V20 적용·기동·기존 데이터 보존 검증을 완료했다. 최신 main 통합 후 전체 시험은
428건 중 420건 통과/조건부 8건 제외이다. AWS/운영과 Android는 수정하지 않았다.
