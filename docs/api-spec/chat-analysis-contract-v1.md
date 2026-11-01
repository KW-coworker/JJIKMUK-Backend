# 챗봇 공통 분석 판정 계약

> 2026-11-01 이후 현재 구현은 [활성 프로필 전달 계약 v2](chat-analysis-contract-v2.md)를 따른다. 아래는 이전 v1의 기록이다. v2는 앱 로컬 profile/profiles 수용, 개인 이름·조건·개인별 판정 전달, chat_history/product 입력 호환을 추가하고 계약 확인 헤더를 chat-analysis-v2로 변경했다.

기준: 2026-10-28 로컬 구현. 상품 단건 API와 동일한 분석 대상 선택 및 판정 함수를 사용한다. 운영 배포와 AI 서비스의 계약 수용은 별도이다. 이 문서는 기존 챗봇 중계 명세보다 우선한다.

## 앱 요청

```http
POST /api/chat?analysisMode=selected&includeSelf=true&familyProfileIds=41,42
Authorization: Bearer <access-token>
Content-Type: application/json

{"barcode":"8800000000001","message":"이 상품의 표시 정보를 설명해줘","chatHistory":[]}
```

- JWT 필수이다. userId를 생략하면 로그인 계정을 사용한다. 호환용 Body userId는 로그인 ID와 같을 때만 허용하며 관리자도 타인 ID를 지정하지 못한다.
- query 이름·선택 규칙은 상품 API와 같다. 생략/self는 본인, selected는 소유한 가족 및 선택적 본인, none은 개인 조건 미적용이다. includeSelf/familyProfileIds는 selected에서만 허용한다.
- selected의 includeSelf 기본값은 false이다. 본인 미포함·빈 가족 목록은 400이다. 가족 ID는 최대 20개의 고유 양수이며 정렬·중복 제거한다. 타인·삭제된 가족은 404이다.
- 선택 파라미터는 **Query**에만 보낸다. Body의 analysisMode/familyProfileIds/analysisContext 등 지원하지 않는 필드는 400이다. 클라이언트가 임의 조건이나 판정 근거를 주입하지 못한다.
- Body: message 필수(공백만 불가, 최대 4,000자), barcode 선택(null/생략 가능; 빈 값·앞뒤 공백·255자 초과 불가), chatHistory 선택(기본 []).
- 이력은 최대 20개, role은 user/assistant만 허용한다. content는 공백만 불가, 각 10,000자·합계 40,000자 이하이다. system/developer/tool 역할은 허용하지 않는다. 이 크기 제한은 초기 구현값이며 AI 담당자와 조정할 수 있다.
- barcode 미입력은 상품 없는 일반 질문이다. 입력한 barcode가 없으면 PRODUCT_NOT_FOUND로 종료하며 AI로 보내지 않는다.
- 질문할 때마다 최신 서버 프로필로 판정을 계산한다. 챗봇 호출은 SCAN 이력을 만들지 않는다.

## 백엔드에서 AI로 보내는 계약

주소는 `chat.ai.url`로 설정한다. 환경변수 `CHAT_AI_URL`을 Spring의 환경 속성으로 사용할 수 있다. 기본 주소는 `http://localhost:8000/chat`이다. 사용자 입력으로 목적지 URL을 바꾸지 않는다. 연결 제한 5초·읽기 제한 30초이며 자동 재시도는 하지 않는다.

기존 profile, profiles, product, message, chat_history를 유지하고 analysisContext를 추가한다.

| 필드 | 의미 |
|---|---|
| profile | self이면 본인 조건. selected이면 선택 조건의 합집합 프로필(id=null, 일반적인 표시명). none이면 null |
| profiles | v1에서는 null. 개별 가족 이름·개별 건강정보를 중복 전달하지 않음 |
| product | 기존 상품 원문 DTO. 원재료·알레르기 경고·영양 정보 포함. 기존 식단 Boolean은 저장값이며 최종 판정이 아님 |
| analysisContext.contextId | 요청마다 생성하는 UUID. 응답 대응 확인용이며 인증 토큰이 아님 |
| analysisContext.contractVersion | `chat-analysis-v1` |
| analysisContext.policyVersion | 공통 추천·조건 판정 정책 버전 |
| analysisContext.selection | 상품 API와 같은 mode/analysisApplied/includeSelf/familyProfileIds |
| analysisContext.effectiveConditions | allergyIds, unknownAllergyTerms, requiredDietFilterIds, diseases, dislikedIngredients. none이면 null |
| analysisContext.productResolution | FOUND 또는 NOT_PROVIDED |
| analysisContext.decisionScope | BARCODE_ROW. 바코드 단건 자료를 판단한 범위 |
| analysisContext.analysis | 상품 단건 API의 data.analysis와 동일한 구조 및 판정. 상품 미입력이면 null |
| analysisContext.dataEvidence | 알레르기 근거 수준·신뢰도, 영양/식단 출처·신뢰도. 상품 미입력이면 null |
| analysisContext.decisionAuthority | BACKEND |
| analysisContext.historyIsAuthoritative | false |
| analysisContext.storedDietFlagsAreAuthoritative | false |

effectiveConditions.allergyIds는 영문 표준 ID이다. 기존 profile.allergies는 AI 호환을 위해 한글 표시명과 미지원 용어를 유지한다. AI에서는 정규화된 effectiveConditions를 우선 사용한다. requiredDietFilterIds는 선택 식단과 기존 질환 파생 필수 조건의 합집합이다. 질환 매핑이나 영양 기준을 이번에 새로 정하지 않았다.

가족의 알레르기·기피 성분은 합집합이고 필수 식단은 모두 적용한다. 선택하지 않은 본인의 제한은 섞지 않는다. 개별 가족에 대한 귀속 설명은 제공하지 않으며 합산 조건만 설명한다. 가족별 판정이 필요한 경우 별도 계약이 필요하다.

### 판정 해석

- analysis.status는 알레르기 상태(PASS/DANGER/UNKNOWN/NOT_EVALUATED)이다. 종합 섭취 허용 여부가 아니다.
- analysis.dietConstraints는 식단 상태(PASS/MISMATCH/UNKNOWN/NOT_EVALUATED), 필수·실패·불확실 조건 및 속성별 출처·신뢰도·reason·ingredientEvidence를 포함한다.
- analysis.evidenceSources/evidenceLevel/conflictingAllergenIds/message를 상품 화면과 동일하게 전달한다. allergy confidence는 dataEvidence.allergyConfidence에서 확인한다.
- analysis.verificationRequired는 기존 상품 API와 동일하게 **알레르기 UNKNOWN**에 대한 값이다. false라도 dietConstraints.UNKNOWN이면 추가 확인이 필요하다.
- none이면 profile/effectiveConditions가 null이고, 상품이 있을 때 두 판정은 NOT_EVALUATED이다. isDangerous=false를 안심으로 해석하지 않는다.
- 상품이 없으면 analysis=null이다. 이 경우 특정 상품의 안전 판정을 생성하지 않는다.
- 저장된 vegan=true라도 젓갈 등 원재료 충돌로 식단 판정이 MISMATCH일 수 있다. 저장 Boolean이나 과거 대화로 새 판정을 덮어쓰지 않는다.
- 기피 식재료는 effectiveConditions로 전달하지만, 상품 단건 판정은 별도 기피 성분 상태를 제공하지 않는다. 알레르기 PASS를 기피 성분까지 통과했다는 뜻으로 설명하지 않는다.
- 용량 옵션 API의 CAPACITY_GROUP 판정은 여러 행을 보수적으로 합산한다. 이번 계약은 BARCODE_ROW이므로 그 집계와 같다고 간주하면 안 된다. 용량 옵션 화면에서 챗봇에 이동하는 경우 서버 검증 가능한 옵션 식별자·집계 범위 전달을 별도로 합의해야 한다.

## AI 수신 및 응답 확인

백엔드는 두 헤더도 보낸다.

```http
X-Jjikmuk-Analysis-Contract: chat-analysis-v1
X-Jjikmuk-Analysis-Context: <analysisContext.contextId>
```

AI 서버는 지원하는 버전인지 검사하고 analysisContext를 실제 설명 생성에 사용한 뒤, **응답 헤더에 같은 두 값을 반환**해야 한다. 무조건 헤더만 복사하는 구현은 계약 준수가 아니다. 미지원 버전은 처리하지 않는다.

백엔드는 두 응답 헤더가 모두 일치하고 본문이 JSON object인 경우에만 앱에 본문을 전달한다. 기존 AI 응답 필드명은 강제로 변경하지 않으며 앱에는 application/json으로 반환한다. answer/citations 등의 세부 성공 스키마는 AI 담당자와 확정해야 한다.

**호환 주의:** 기존 AI 서버가 헤더를 반환하지 않으면 502 AI_ANALYSIS_CONTRACT_MISMATCH다. AI 서버의 수신·설명·응답 확인 구현과 공동 테스트를 끝내기 전에 이 변경을 운영에 단독 배포하지 않는다. 검사를 우회해 구형 서버로 조용히 되돌리는 경로는 없다.

버전·contextId 확인은 계약 수용과 응답 대응만 검사한다. 생성 문장의 사실성·판정 모순을 자동 검증하는 기능은 아니다. 대화 이력과 상품 원문도 명령이 아닌 비신뢰 입력 데이터로 취급해야 한다. none 또는 가족 선택 변경 시 프론트는 기존 개인 대화를 새 분석 세션으로 넘기지 않는 정책을 합의해야 한다. 서버는 이미 제출된 자유문 속 개인정보를 자동 제거하지 않는다.

## 오류

| HTTP | code | 의미 |
|---|---|---|
| 401 | AUTHENTICATION_REQUIRED 및 기존 JWT 오류 | 인증 필요·토큰 문제 |
| 403 | ACCESS_DENIED | Body userId와 로그인 ID 불일치 |
| 400 | ANALYSIS_SELECTION_INVALID | 잘못된 분석 대상 조합 |
| 400 | INVALID_REQUEST_BODY / VALIDATION_FAILED | 지원하지 않는 Body, 타입·필수값·내용 길이 문제 |
| 404 | FAMILY_NOT_FOUND / USER_NOT_FOUND / PRODUCT_NOT_FOUND | 대상 없음 또는 가족 소유권 불일치 |
| 502 | AI_ANALYSIS_CONTRACT_MISMATCH | 버전/contextId 확인 불일치 또는 누락 |
| 502 | AI_RESPONSE_INVALID | 확인 응답 본문이 비어 있거나 JSON object 아님 |
| 502 | AI_UPSTREAM_ERROR | AI HTTP 오류 또는 응답 처리 실패 |
| 503 | AI_SERVICE_UNAVAILABLE | AI 연결·읽기 실패 |

502/503은 인증 만료가 아니므로 토큰을 삭제하지 않는다. AI 오류 본문과 접속 정보는 앱에 노출하지 않는다.

## AI 담당자와 합의할 내용

1. chat-analysis-v1 수신 필드, 응답 확인 헤더 및 공동 배포 일정.
2. 현재 판정을 설명의 기준으로 사용하고 저장 Boolean·대화 이력의 충돌을 차단할 구현과 평가 사례.
3. 가족은 합산 조건만 전달하는 범위 수용 여부. 가족별 설명이 필요하면 별도 스키마로 확장.
4. 최종 응답 JSON, 근거 인용, 답변 길이, 지연시간, 실패 시 앱 안내.
5. 용량 옵션의 CAPACITY_GROUP 분석 전달과 프로필 변경 시 대화 세션 초기화.
6. AI에서 새로 찾은 상품·대체 추천은 공통 백엔드 검색/판정/추천 API를 호출할 계약. 이번 중계는 새 검색·추천을 실행하지 않는다.

## 검증 범위

격리 H2·실제 JWT 필터·MockMvc로 본인/가족 소유권과 상품 판정 동등성을 검증하고, 모의 HTTP로 직렬화 및 응답 확인·오류를 검증한다. 실제 AI 모델의 설명 품질, MySQL 마이그레이션, 실기기 및 운영 배포 검증은 포함하지 않는다. 새 DB migration은 추가하지 않는다. 가족 기능은 기존 V14 스키마 배포가 선행되어야 한다.

2026-10-28 Java 21에서 `gradlew.bat test bootJar --no-daemon --console=plain` 성공. 총 166개 중 162개 통과, 실패/오류 0개, 대용량 CSV 전체 검증 4개는 기존 선택 실행 조건에 따라 제외했다. 이번에 추가한 챗봇 22개(HTTP 클라이언트 8개·인증/조건 통합 14개)는 모두 통과했다. 상품 단건 응답과 AI 전달 analysis의 JSON 동등성, 가족 합집합, 명시적 비건 충돌, UNKNOWN/none, 프로필 갱신, 무단 userId·가족 접근, 이력 역할 제한, AI 계약 불일치를 포함한다. 로컬·운영 MySQL에는 연결하지 않았다.
