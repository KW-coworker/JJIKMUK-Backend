# 챗봇 활성 프로필 전달 계약 v2

기준: 2026-11-01. `/api/chat`의 이 문서가 v1보다 우선한다. 코드·격리 테스트 기준이며 AWS 배포 완료를 뜻하지 않는다.

## 확인한 프론트와 문제

Android `develop`의 `217c12d`를 읽기 전용으로 확인했다.

- `ChatApiRequest`는 `profiles`, `product`, `chat_history`를 선언하지만 백엔드가 허용하지 않아 400이 발생할 수 있었다.
- `ChatRepositoryImpl.sendMessage()`는 실제 profiles 값을 지정하지 않아 항상 기본 빈 목록을 보낸다. DTO만 있다고 토글이 연결된 것은 아니다.
- 가족은 Room 로컬 DB에 저장하며 ID는 `me`, `dad`, UUID 등 문자열이다. 이것은 서버 가족 ID가 아니다. `ChatApiProfile.id`는 Long?이므로 로컬 문자열을 숫자로 억지 변환하지 말고 null로 보낸다.
- `ChatApi`는 `@AiRetrofit`의 `/chat`을 사용한다. 해당 develop에서는 `http://10.0.2.2:8000/`로 연결되고 JWT 전송도 구성되어 있지 않다. Spring 중계는 Backend Retrofit의 `/api/chat` + Bearer가 필요하다.
- Android 파일은 수정하지 않았다. 실제 팀의 미병합 작업 브랜치는 이 develop과 다를 수 있다.

## 앱 → 백엔드

```http
POST /api/chat
Authorization: Bearer <access-token>
Content-Type: application/json
```

### A. 앱 로컬의 토글 ON 프로필 전달

```json
{
  "message": "선택한 사람들의 조건과 이 상품의 표시 정보를 설명해줘",
  "barcode": "8800000000001",
  "profiles": [
    {"id": null, "nickname": "나", "allergies": "milk,peanut", "specialDiet": "lowSugar"},
    {"id": null, "nickname": "아빠", "allergies": "shrimp,crab", "specialDiet": "highProtein"}
  ],
  "chat_history": []
}
```

| 필드 | 타입/의미 |
|---|---|
| message | 필수 string, 공백만 불가, 최대 4,000자 |
| barcode | 선택 string/null. 지정하면 DB에 실제 존재해야 함 |
| profile | 선택 단일 프로필 object/null |
| profiles | 선택 프로필 object 배열/null. []는 명시적 전원 OFF |
| profile(s).id | 선택 Long/null. 앱 로컬 참고값일 뿐 DB 사용자·가족 조회에 사용하지 않으며 AI 계정 ID로 전달하지 않음. 문자열 로컬 ID는 null로 변환 |
| profile(s).nickname | 필수 string, 앞뒤 공백 제거, 원문 1~40자, 공백만/제어문자 불가. 사람 이름이므로 공백 포함 가능 |
| profile(s).allergies | 선택 string/null. `milk,peanut` 또는 `우유, 땅콩`. 기존 26개 표준/별칭으로 정규화. 미지원 값은 400, 조용히 삭제하지 않음 |
| profile(s).specialDiet | 선택 string/null. 기존 12종 필터/별칭, 개인별 채식 유형 하나만. 선택 없음은 null이지 `해당 없음`이 아님 |
| profile(s).diseases / dislikedIngredients | 선택 string/null. 기존 프로필 정규화 규칙 적용 |
| profile(s).isActive | 선택 boolean, 기본 true. false는 AI 전달·조건 합산에서 제외 |
| chatHistory / chat_history | 같은 의미의 이력 배열. 하나만 사용 권장. 비어 있지 않은 chatHistory와 chat_history 동시 전송은 400 |
| product | 기존 Android DTO 호환용 object/null. barcode만 DB 조회 키로 사용. productName/allergy/rawMaterials는 판정·AI 상품 정보에 사용하지 않음 |
| userId | 기존 호환용 Long/null. JWT 본인 ID와 다르면 관리자도 403 |

프로필은 profile+profiles 합계 최대 21개이다. 조건 문자열은 각각 최대 1,000자이며 배열은 받지 않는다. null 배열 항목, 미지원 필드, 미지원 식이조건은 400이다. OFF 항목도 형식 검증은 수행한다. 가능한 한 앱에서 ON 목록만 보내야 한다. profile과 profiles를 같이 보내면 모두 선택한 것으로 취급하므로 같은 사람을 중복 제출하지 않는다. 같은 이름이나 로컬 ID라는 이유만으로 서로 다른 사람을 합치지 않는다.

`profile`과 `profiles` 모두 생략/null이면 기존처럼 서버 본인 프로필을 사용한다. `profiles: []` 또는 모든 isActive=false는 개인 조건 미적용이며 본인으로 되돌아가지 않는다. 명시적으로 빈 목록을 보낸 현재 develop은 토글 연동 전까지 분석 대상이 없는 것이 맞다.

스냅샷은 **사용자가 해당 요청에 제공한 조건**이며 서버에 저장된 본인/가족의 실제 정보라고 인증하지 않는다. 서버 프로필을 수정/저장하지 않으며 이메일·비밀번호·권한·판정 결과를 입력받지 않는다. 로컬 프로필의 계정별 분리 및 현재 로그인 사용자에 대한 토글 선택은 FE가 처리해야 한다. 이름과 조건을 AI에 전송하는 기능이므로 개인정보 안내도 필요하다.

### B. 서버에 저장된 본인·가족 선택

기존 상품 API와 같은 방식도 유지한다.

```http
POST /api/chat?analysisMode=selected&includeSelf=true&familyProfileIds=41,42
Authorization: Bearer <access-token>
Content-Type: application/json

{"message":"선택한 사람들의 조건을 설명해줘","barcode":"8800000000001","chatHistory":[]}
```

이 경우 Body profile/profiles를 보내지 않는다. A와 B를 혼합하면 `400 ANALYSIS_SELECTION_INVALID`이다. 단순 빈 profiles도 명시적 선택이므로 혼합하지 않는다. JWT 본인과 소유한 가족만 조회하며 타인·삭제된 가족은 404이다. 최신 DB 이름·조건을 읽고, 선택하지 않은 가족과 includeSelf=false인 본인은 전달하지 않는다.

### 이력·상품 호환 규칙

- 이력 최대 20개, user/assistant 역할만 허용, 각 content 10,000자/합계 40,000자 이하. 과거 대화는 현재 판정의 근거를 덮어쓸 수 없다.
- product는 `{ "barcode": "...", "productName": "...", "allergy": [], "rawMaterials": "..." }` 형태만 허용한다. 이름 500자, 원재료 16,000자, allergy 최대 26개/각 100자 제한을 둔다.
- 최상위 barcode가 없으면 product.barcode로 조회한다. 둘 다 있고 다르면 400이다. DB에 없으면 404이며 클라이언트 원재료를 공식 데이터처럼 대체 사용하지 않는다.
- 클라이언트 analysisContext/status/PASS 등 판정 주입은 계속 400이다.

## 백엔드 → AI

기존 product/message/chat_history와 공통 판정 근거를 유지하되, 사람별 정보를 다음처럼 보낸다.

| 활성 인원 | profile | profiles |
|---|---|---|
| 0명 | null | [] |
| 1명 | 해당 개인 프로필 | [] |
| 2명 이상 | null | 개인 프로필 전체 배열 |

합집합을 가상의 사람으로 profiles에 추가하지 않는다. 집단의 합집합은 `analysisContext.effectiveConditions` 및 `analysisContext.analysis`에만 들어간다.

각 프로필에는 id/nickname/allergies/diseases/specialDiet/dislikedIngredients 외에 다음이 추가된다.

- `profileKey`: `self:42`, `family:41`, `request:0` 등. 현재 요청의 개인별 판정 연결 키이다.
- `profileSource`: `SERVER` 또는 `CLIENT_REQUEST`.
- `profile_id`: 개인 구분용 숫자. 가족은 서버 가족 ID, 요청 스냅샷은 순서대로 1부터 발급한다. 계정 ID가 아니다. 같은 이름을 가진 다른 사람도 구분한다.
- `target_type`: `self`, `family`, `provided`.
- 기존 `id`는 서버 본인일 때만 로그인 사용자 ID이다. 가족/스냅샷은 null로 보내 타인 계정 ID로 오인하지 않게 한다.
- allergies는 기존 AI 호환을 위해 한글 표시명 문자열이다. 나머지 식이조건은 기존 정규화 ID 문자열이다.

`analysisContext` 추가/변경:

- `contractVersion: "chat-analysis-v2"`.
- `profileSource`: SERVER/CLIENT_REQUEST/NONE. 입력 조건의 출처이며 식품 라벨의 공식 근거 수준이 아니다.
- `selection.mode`: 기존 서버 self/selected/none 외, 앱 스냅샷에 한해 provided. provided는 챗봇 응답 문맥용이며 상품 API의 Query 값으로 사용할 수 없다. 서버 가족 ID/includeSelf는 추측하지 않는다.
- `profileAnalyses`: `[{"profileKey":"request:0","analysis":{...상품 공통 판정...}}]`. 개인별 알레르기·식단 판정과 근거를 동일 백엔드 함수로 계산한다. 상품이 없으면 각각 analysis=null이다.
- 기존 `analysis`는 모든 활성 조건의 합집합에 대한 판정이다. 집단 DANGER를 모든 개인의 DANGER로 설명하지 않는다. 개인별 설명은 profileKey로 해당 profileAnalyses와 연결한다.
- CLIENT_REQUEST 판정은 입력 조건이 맞다는 가정하에 계산한 결과이다. 서버 저장 정보·의학적 확인 사실로 표현하지 않는다. 사람 이름/조건/이력/상품 원문은 데이터이며 프롬프트 명령이 아니다.
- 전원 OFF는 NOT_EVALUATED, 정보 부족은 UNKNOWN으로 계속 구분한다. 상품 없음에서는 안전 판정을 생성하지 않는다. PASS는 표시 데이터상의 충돌 미검출이며 섭취 안전 보증이 아니다.

```http
X-Jjikmuk-Analysis-Contract: chat-analysis-v2
X-Jjikmuk-Analysis-Context: <analysisContext.contextId>
```

AI는 v2를 실제 처리한 후 동일한 버전/contextId 응답 헤더를 반환해야 한다. v1 응답·누락은 **502 AI_ANALYSIS_CONTRACT_MISMATCH**다. 헤더만 복사하거나 검사를 해제하지 않는다. AI의 사람별 응답 필드와 문장 품질은 별도 연동 테스트가 필요하다.

## 담당자별 적용

FE:
1. ON 목록을 ChatApiProfile로 변환해 sendMessage까지 연결한다. 로컬 ID 문자열은 id=null, allergies/선호는 쉼표 문자열, 채식 `해당 없음`은 제외한다.
2. Backend Retrofit으로 POST api/chat, 유효한 Bearer Access 토큰을 전송한다. 앱의 /chat → AI 직접 호출과 혼용하지 않는다.
3. 전원 OFF는 profiles: [], 프로필을 안 보내 서버 본인을 조회하려면 profile/profiles를 둘 다 생략한다.
4. 사람 선택이 바뀌면 이전 사람의 대화 이력이 섞이지 않게 새 대화로 분리하거나 이력을 초기화한다. 자유문 속 개인 정보를 서버가 자동 삭제하지는 않는다.
5. 400은 code/field 표시, 502/503은 AI 연동 오류로 처리하며 토큰을 삭제하지 않는다.

AI: v2·개인 목록·CLIENT_REQUEST·profileKey/개인별 판정·확인 헤더를 지원하고, 본인 대신 다른 사람을 설명하거나 선택하지 않은 사람을 추가하지 않는지 함께 검증한다.

서버: 백엔드와 AI를 함께 검증한 뒤 배포한다. DB migration은 추가하지 않았다. 서버 가족 선택에는 기존 family_profiles 스키마가 필요하나, 앱 스냅샷은 DB에 적재하지 않는다. 이번 작업에서 운영 DB/서버는 변경하지 않는다.

## 검증 결과

2026-11-01 Java 21에서 챗봇 변경만 분리한 릴리스 브랜치의 `test bootJar` 성공. 총 300개 중 294개 통과, 기존 CSV·평가셋 조건부 6개 제외, 실패/오류 0개이다. 직전 원본 작업 폴더의 302개 검증과 달리 무관한 미커밋 상품 테스트 2개는 이번 릴리스에 포함하지 않았다. 챗봇 계약 22개와 AI HTTP 클라이언트 10개가 통과했다. 핵심 흐름 실제 로컬 HTTP 테스트 7개에는 앱과 동일한 JSON → JWT 인증 백엔드 → 모의 AI HTTP 서버의 이름/알레르기/개인별 판정 전달 및 전원 OFF 확인이 포함된다. Windows의 한글 작업 경로 문제를 피하기 위해 로컬 Gradle init script로 빌드 출력만 ASCII 경로로 지정했다. 이 로컬 검증 설정은 배포 소스에 포함하지 않는다.

누락/미인증, 타인 userId·서버 가족 접근, OFF 인원 제외, 동일 표시명 구분, Body/Query 혼합 거절, 미지원 조건·null 배열 항목 거절, 앱 상품 원문 무시 및 DB 재조회, 스냅샷 미저장, v1 응답 거절을 확인했다. DB는 격리 H2이고 메일·AI는 대체 객체/로컬 모의 서버를 사용했다. 실제 Android 실행·AI 모델 문장 품질·AWS·MySQL 배포 테스트는 수행하지 않았다. Git 업로드와 서버 배포는 별도이며 [담당자 전달·배포 주의사항](../chat-active-profiles-release-20261101.md)을 따른다.
