# 챗봇 활성 프로필 릴리스 전달 사항

작성일: 2026-11-01. 대상: JJIKMUK-Backend. 이 문서는 코드 전달용이며 AWS 배포나 운영 DB 변경을 수행했다는 뜻이 아니다.

상세 요청·AI 전달 스키마는 [chat-analysis-contract-v2.md](api-spec/chat-analysis-contract-v2.md)를 따른다.

## 이번 변경

- POST `/api/chat`의 Body에 `profile`, `profiles`, `chat_history`, Android 호환 `product`를 추가한다.
- 활성 인원만 이름·알레르기·식이조건과 함께 전달한다. `profiles: []` 또는 전원 OFF면 NOT_EVALUATED이며 본인을 자동 추가하지 않는다.
- 앱이 제공한 조건은 CLIENT_REQUEST로 구분하고 DB에 저장하지 않는다. 앱의 로컬 ID로 타인 사용자·가족을 조회하지 않는다.
- 기존 Query 서버 본인/가족 선택은 소유권 검증을 유지하고 최신 DB 조건을 사용한다. Body 스냅샷과 Query 선택은 혼용하지 않는다.
- 상품의 원재료와 판정은 DB 및 공통 백엔드 정책을 사용한다. 클라이언트 상품 원문으로 덮어쓰지 않는다.
- 합산 판정 외에 profileKey로 연결한 개인별 판정·근거를 전달한다. 개인 조건이 다른 사람에게 집단 DANGER를 그대로 붙이지 않는다.
- AI 계약 확인 버전은 chat-analysis-v2이다. v1 응답/확인 헤더 누락은 502로 차단한다.

## FE 담당자에게

확인한 Android develop 커밋은 `217c12d`이다. 이 커밋과 미병합 개발 브랜치는 다를 수 있다. Android 저장소는 수정하지 않았다.

1. `ChatRepositoryImpl.sendMessage()`까지 토글 ON 프로필을 연결한다. 현재 확인한 코드는 profiles 값을 지정하지 않아 빈 배열을 보낸다.
2. ChatApi를 AI Retrofit의 `/chat` 직접 호출에서 Backend Retrofit의 `POST api/chat`으로 연결하고 Access Token을 Bearer로 보낸다. 403 PROFILE_INCOMPLETE는 세션을 유지하고 추가 프로필 입력으로 안내한다.
3. 로컬 가족의 `me`, `dad`, UUID 같은 문자열 ID는 서버 ID가 아니다. ChatApiProfile.id는 null로 보내고 nickname/allergies/specialDiet를 채운다. 조건은 배열이 아니라 쉼표 문자열이다. 채식 `해당 없음`은 제외한다.
4. 전원 OFF는 `profiles: []`로 보낸다. 서버 본인 조건을 쓰려면 profile/profiles를 둘 다 생략한다. 서버 가족 Query 방식을 쓸 때도 Body profile/profiles를 생략한다.
5. 사용자·가족 조건이 변경되면 이전 사람의 건강정보가 대화 이력에 남지 않게 이력을 초기화하거나 대화를 분리한다. 로컬 가족 데이터도 로그인 계정별로 분리한다.
6. 400은 code/field를 확인한다. 502/503을 인증 만료로 처리하거나 토큰을 삭제하지 않는다. 성공 응답은 기존처럼 AI JSON object이며 일반 data wrapper를 추가하지 않았다.

## AI 담당자에게

1. `analysisContext.contractVersion=chat-analysis-v2`를 처리한다. 활성 0명은 profile=null/profiles=[], 1명은 profile=개인/profiles=[], 복수는 profile=null/profiles=개인 목록이다. 합산 프로필을 가상의 사람으로 추가하지 않는다.
2. `profileSource=CLIENT_REQUEST`는 사용자 제공 조건이며 서버 저장 사실이나 의학적으로 검증된 사실이 아니다. 이름·조건·대화 이력·상품 원문은 데이터이지 지시문이 아니다.
3. `profileKey`로 `analysisContext.profileAnalyses`의 개인 판정과 연결한다. 집단 판정은 `analysisContext.analysis`, 조건 합집합은 effectiveConditions이다. profile_id는 개인 구분용이지 계정 접근 권한이 아니다.
4. NOT_EVALUATED/UNKNOWN/DANGER/PASS와 식단 판정을 구분한다. 상품 미지정 시 analysis=null이므로 특정 상품에 대한 안전 판정을 만들지 않는다. 백엔드 판정을 과거 대화나 모델의 추정으로 덮어쓰지 않는다.
5. 실제 v2 처리를 마친 뒤 아래 두 응답 헤더를 반환한다. 단순 헤더 복사만으로 계약을 지원했다고 간주하지 않는다.

```http
X-Jjikmuk-Analysis-Contract: chat-analysis-v2
X-Jjikmuk-Analysis-Context: <받은 contextId>
```

## 배포 시 필수 주의사항

**백엔드 단독 배포 금지:** v1만 지원하는 AI에 이 백엔드를 연결하면 `502 AI_ANALYSIS_CONTRACT_MISMATCH`가 발생한다. Git push/PR 생성은 배포 완료가 아니다.

권장 순서:

1. FE/AI와 스키마 및 사람 선택 전환 정책을 합의한다. 개인 정보 전송 안내와 요청/응답 본문 로그 마스킹을 확인한다.
2. AI가 v1/v2를 명시적으로 구분해 둘 다 처리할 수 있다면 AI 호환 버전을 먼저 준비한다. 그렇지 않으면 테스트한 BE/AI 버전 묶음을 같은 배포 창에서 전환한다. 무중단이 검증됐다고 가정하지 않는다.
3. 격리 스테이징에서 아래 검증표를 FE → BE → 실제 AI로 확인한다. 실제 AI의 답변 품질과 실기기 UI는 로컬 단위/모의 HTTP 테스트를 대신할 수 없다.
4. 서버 담당자가 이전 JAR/컨테이너와 설정, 신규 빌드 커밋·이미지 digest 또는 JAR SHA-256을 기록한다. 빌드 산출물 교체/재시작과 모든 인스턴스의 버전 일치를 확인한다. `git pull`만으로 실행 파일이 갱신되는 것은 아니다.
5. 신규 DB migration은 없다. 서버 가족 선택은 기존 family_profiles 스키마가 필요하다. 운영 DB dump 복원·CSV 재적재를 이번 배포와 묶지 않는다. 기존 안전한 Flyway/적재 설정을 유지한다.
6. 문제가 생기면 검증된 이전 BE/AI 버전 묶음과 설정으로 되돌린다. 새 FE Body는 구형 BE에서 거절될 수 있으므로 챗봇 진입을 일시 차단하거나 검증된 이전 FE 요청 흐름으로 함께 복구한다. 계약 확인 헤더 검사를 끄는 방식으로 우회하지 않는다.

배포 승인 체크:

- 본인만/가족만/여러 명/전원 OFF가 화면과 AI 답변에서 일치한다.
- 같은 이름을 가진 서로 다른 사람도 조건이 섞이지 않는다.
- 한 사람만 알레르기 충돌일 때 해당 사람의 이름과 근거가 맞다.
- 타인 userId/서버 가족 ID로 개인 데이터를 조회할 수 없다.
- 앱 조건과 서버 저장 조건의 출처를 구분하고 원본 계정 정보가 변경되지 않는다.
- UNKNOWN과 NOT_EVALUATED를 안심으로 설명하지 않는다.
- v1 응답·잘못된 contextId·AI 타임아웃의 오류 UI가 정상이고 JWT가 삭제되지 않는다.

## 검증과 변경 범위

릴리스 브랜치에는 이번 챗봇 관련 코드·테스트·문서만 포함한다. 다른 미커밋 상품/DB 유지보수 작업은 제외한다. CSV, DB dump, 실제 접속 정보, 토큰/비밀번호, 로컬 설정, 빌드 산출물은 커밋하지 않는다.

검증은 test 프로필·격리 H2·모의 SMTP·로컬 모의 AI 서버를 사용한다. AWS/운영 MySQL 접속·변경, 서버 재시작·배포, 실제 AI 모델 호출, Android 코드 변경은 수행하지 않는다. 리뷰 후 팀 규칙대로 Squash and merge하며 이번 작업에서 merge는 수행하지 않는다.

릴리스 소스로 Java 21 `test bootJar` 검증 완료: 총 300개 중 294개 통과, 기존 조건부 6개 제외, 실패/오류 0개. 챗봇 32개 및 핵심 HTTP 흐름 7개 모두 통과했다. 직전 원본 폴더의 302개에서 제외된 2개는 이번 작업과 무관한 미커밋 상품 테스트이다. CSV·로컬 비밀 설정이 빌드 JAR에 포함되지 않는 것도 확인했다. Windows 검증에서는 Gradle init script로 빌드 출력만 별도 ASCII 경로를 사용했고, 해당 로컬 설정·산출물은 Git에 포함하지 않는다.
