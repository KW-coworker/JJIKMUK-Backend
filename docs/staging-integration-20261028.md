# 스테이징 버전 대조·핵심 사용자 흐름 통합 검증

검증일: 2026-10-28. 결론: **로컬 백엔드 흐름은 통과했지만, 앱·AI·원격 스테이징을 포함한 전체 통합은 완료되지 않았다.**

## 1. 범위와 버전

사용자 승인에 따라 원격 서버에는 익명 GET 조회만 시도했다. 회원가입·프로필·가족·이력 변경은 H2 메모리 DB에서만 수행했다. 운영/로컬 MySQL·원본 CSV는 변경하지 않았고, 배포·병합·커밋·push도 하지 않았다.

| 대상 | 검증 기준 | 상태 |
|---|---|---|
| Android | `KW-coworker/JJIKMUK-Android`, `feature/product-search`, `9a37a9034fc5d11d10bf2d0facf81fc1922315a2` | 별도 복사본, 원래 앱 소스 수정 없음 |
| 로컬 Backend | HEAD `072ddac` + 기존 미커밋 작업 + 이번 테스트 코드 | V14 스키마 파일, 인증 v2, 공통 판정 v5.1, `chat-analysis-v1` |
| 팀 Backend 저장소 | `KW-coworker/JJIKMUK-Backend` main `4647daa651a283ca67d4b76b9ae0b06920dbaf81` | 10월 15일 버전, 마이그레이션 파일은 V12까지 |
| 로컬 AI | 기존 프로젝트의 `AI/app` 소스 지문으로 고정 | 최신 팀 AI 버전인지 미확인 |
| 원격 실행 서버 | `jjikmuk-backend-dev.tail198441.ts.net` | 조회 timeout, Tailscale 대상 peer `Online=false`, 실행 커밋/DB 버전 미확인 |

제공된 Backend 저장소의 main과 원격 feature 브랜치들을 확인했지만 Python/AI 코드가 없었다. 해당 저장소의 `/api/chat`은 AI 서버에 중계하는 Kotlin 코드이며, 별도의 AI 실행 코드가 아니다. 저장소 main의 버전과 실제 배포 버전이 같다고 단정할 수 없다.

**정렬한 것은 검증 기준과 버전 차이이다. 실제 스테이징 배포 버전 정렬은 하지 않았다.** 로컬 변경을 보존했으며 상세 파일별 SHA-256, JAR/APK SHA-256은 결과 폴더의 `version-and-test-manifest.json`에 기록했다.

## 2. 테스트 결과

| 검증 | 결과 | 의미와 한계 |
|---|---|---|
| Backend 전체 회귀 테스트 | 170개 중 166 통과, 4 건너뜀, 실패 0 | 대용량 CSV opt-in 테스트 4개는 미실행 |
| Backend 신규 HTTP 흐름 | 시나리오 4개 통과, HTTP 요청 50회 모두 기대 상태 일치 | 실제 Tomcat·JWT·서비스·JPA, H2 사용 |
| Backend 실행 JAR | 빌드 성공 | 전체 캐시 무시 빌드 후 마지막 테스트 추가분 재검증 |
| Android 기존 테스트 | 54개 통과 | 선택한 커밋의 기존 테스트, 실기기 테스트 아님 |
| Android Debug APK | 빌드 성공 | 설치·화면 조작·카메라 촬영 미실행 |
| Android 신규 계약 대조 | 4개 중 2 통과, 2 실패 | 아래 식단 판정 누락·미분석 상태 손실 재현 |
| 로컬 AI 기존 테스트 | 78 통과, 2 건너뜀 | 실제 LLM/RAG 외부 호출 차단 |
| 로컬 AI 최신 요청 계약 | 불일치 확인 | 정확한 백엔드 요청은 HTTP 422 |
| 원격 서버/API | 미검증 | 첫 공개 API 조회가 timeout |

Android는 최초 한글 경로에서 AGP 경로 경고와 테스트 클래스 로딩 오류가 발생했다. 같은 커밋을 영문 경로로 복사한 뒤 설정/앱 소스를 바꾸지 않고 54개 테스트 및 APK 빌드가 통과했다. 원래 브랜치의 기능 오류와 구분한다. 연결된 Android 기기/에뮬레이터가 없어 UI E2E 성공을 주장하지 않는다.

## 3. 실제 HTTP로 확인한 핵심 흐름

1. 이메일 코드 요청 → 4자리/300초 확인 → 코드 검증 → 가입 증명 1,800초 확인 → 회원가입 → 로그인.
2. 내 프로필 조회·PATCH 수정 → 가족 생성 → 본인+가족 합산 조건으로 상품 조회.
3. 상품명 검색 → 100g/200g 용량 옵션 2개 → 카테고리 조건 검색.
4. 맞춤 추천 → 커서 추가 로딩 → 전달한 바코드 중복 제외 → 분석 조건이 달라진 커서 거부.
5. 대체 상품 추천에서 알레르기 PASS와 필수 식단 PASS 확인.
6. 행동 이력 생성·조회 → 챗봇 중계. AI로 보낸 공통 판정 JSON이 동일 조건의 상품 상세 판정 JSON과 같은지 비교.
7. Refresh 회전 → 로그아웃 → 폐기된 세션의 토큰으로 `/api/users/me` 요청 시 401.
8. 정보 부족 UNKNOWN, 비건 플래그와 새우 원재료 충돌 MISMATCH를 추천에서 제외하는지 검증.
9. 타인 가족 사용 404, 타인 userId 챗봇 요청 403, 비로그인 챗봇 401, AI 계약 확인 누락 502를 확인.
10. 구형 `allergies=soy` 쿼리는 JWT 본인 조건을 바꾸지 않으며, 서버 가족 ID 선택을 해야 가족 알레르기가 적용됨을 재현.

테스트 상품은 쌀칩·우유칩·콩칩·새우칩·정보누락 등 8개의 합성 상품이다. 실제 134만 건 검색 품질·인덱스·부하·MySQL 마이그레이션 성능 검증은 아니다. 이메일은 SMTP mock, AI는 HTTP 계약 대역이므로 실제 메일 도착이나 생성 답변 품질을 검증한 것도 아니다.

## 4. 해결이 필요한 연동 차이

### 우선 1 — 실제 로그인과 토큰 전달

- Android `feature/auth/presentation/login/LoginViewModel.kt`는 `FakeAuthValidator`로 테스트 계정만 검사한다.
- `AccessTokenStore`와 Authorization 인터셉터는 있지만, 현재 앱 소스에서 `setAccessToken` 호출자를 찾지 못했다.
- 따라서 기존 화면의 로그인 성공이 Backend JWT 발급·저장을 뜻하지 않는다. 맞춤 추천·내 프로필·챗봇 전체 흐름의 출발점이 막혀 있다.
- 프론트 인증 담당이 실제 `/api/auth/login`, `/refresh`, `/logout` 및 가입 증명 흐름을 연결한 커밋을 제공해야 한다. 인증 v2 문서를 기준으로 묶어 재검증한다.

### 우선 2 — 가족 선택을 서버 분석 계약으로 연결

- Android 가족 데이터는 로컬 Room/문자열 UUID 기준이고, ProductApi는 `userId`·`allergies`만 전달한다.
- 최신 Backend는 JWT 소유권을 확인한 서버 가족 ID와 `analysisMode`, `includeSelf`, `familyProfileIds`를 사용한다.
- 재현: 본인=우유, 가족=대두, 상품=콩칩일 때 `?allergies=soy`는 본인 기준 PASS, `?analysisMode=selected&familyProfileIds=...`는 DANGER이다. 가족을 선택한 화면에 본인 결과를 표시하지 않도록 반드시 계약을 바꿔야 한다.
- 검색·상세·용량 옵션·홈 추천·대체 추천·챗봇에 동일한 선택을 전달하고, 변경 시 기존 결과/커서를 초기화해야 한다. 로컬 UUID를 서버 숫자 ID로 임의 변환하면 안 된다.

### 우선 3 — 식단 판정과 미분석 상태를 앱에서 유지

추가 계약 테스트 2개가 실패했다.

| 재현 | 현재 앱 처리 | 필요한 처리 |
|---|---|---|
| `analysis.status=PASS`, `analysis.dietConstraints.status=MISMATCH` | `ProductAnalysisDto`에 `dietConstraints`가 없어 버림 | 알레르기와 식단 판정을 별도 필드로 받고 둘 다 표시 |
| `analysis.status=NOT_EVALUATED` | `ProductRepositoryImpl`에서 Unknown으로 매핑 | 미분석 전용 상태와 안내 문구 추가 |

첫 번째 PASS는 알레르기 충돌이 없다는 뜻이지 모든 식단에 적합하다는 뜻이 아니다. 현재 UI의 알레르기 배지를 전체 적합 판정으로 해석해서는 안 된다. UNKNOWN/MISMATCH의 이유·필요 확인 사항도 DTO→도메인→화면까지 유지해야 한다.

### 우선 4 — 챗봇 요청 경로와 AI 계약 동시 정렬

- Android는 `@AiRetrofit`의 `http://10.0.2.2:8000/chat`으로 직접 요청한다. Backend JWT 인터셉터를 거치지 않는다.
- 최신 설계는 앱→인증된 Backend `/api/chat`→AI 순서이다. 앱 요청에 선택한 용량 바코드와 공통 가족 선택을 전달해야 한다.
- 기존 로컬 AI에 Backend의 실제 합성 요청을 전송하면 `profiles:null`을 List로 받을 수 없어 422가 발생한다.
- 진단용 사본에서 `profiles:[]`만 바꾸면 200이지만 `analysisContext`가 버려지고 버전/context 응답 헤더도 없다. 이 한 필드만 바꾸는 것으로는 해결되지 않는다.
- AI 담당자가 `chat-analysis-v1`의 공통 판정·근거를 실제로 사용하도록 구현하고, 사용한 계약 버전/context ID를 확인 응답해야 한다. 헤더만 되돌려주는 형식적 수정은 충분하지 않다.
- 이번에 AI 실행 코드나 앱 본체를 임의 수정하지 않았다. 최신 AI 저장소/브랜치를 확보한 뒤 같은 요청으로 재검증해야 한다.

### 우선 5 — 서버의 배포 묶음 확정

- 팀 Backend main은 V12 파일까지이고, 로컬의 V13/V14·가족/세션·공통 판정 변경이 포함되어 있지 않다.
- 서버 담당자에게 실제 실행 커밋/컨테이너 이미지 태그, Flyway 성공 버전, API/AI 각 버전을 요청한다. 비밀번호·키는 보고서에 넣지 않는다.
- 승인된 스테이징에 백업·마이그레이션 검증·코드 배포를 한 묶음으로 계획해야 한다. **이번 H2 테스트 통과는 MySQL V14 마이그레이션 성공을 증명하지 않는다.**
- Tailscale 서버를 다시 온라인으로 만든 후 공개 카탈로그부터 GET 재검증한다. 계정 생성 등 원격 쓰기 테스트는 별도 승인 전까지 하지 않는다.

## 5. 이번에 추가한 파일과 재실행 방법

- `src/test/kotlin/org/jjikmuk/backend/integration/CoreUserFlowHttpIntegrationTest.kt`: 실제 HTTP 흐름 4개, 합성 응답/상태 기록.
- `scripts/Probe-StagingReadOnly.py`: 원격 공개 GET 진단. 인증·배포·DB 작업 없음.
- `scripts/Probe-LocalAiContract.py`: 외부 키/환경 파일 로딩·외부 소켓 차단, 메모리 저장소 AI 계약 진단.
- `scripts/Summarize-StagingIntegration.py`: 버전 지문·JUnit 결과 집계 및 산출물 복사.
- 별도 Android 사본에만 `BackendSnapshotContractTest.kt`와 합성 응답 fixture 추가. 기존 앱 소스는 그대로이다.

Backend 디렉터리에서:

```powershell
$env:JAVA_HOME='C:\Program Files\Java\jdk-21'
.\gradlew.bat test bootJar --no-daemon --console=plain
# HTTP 흐름만 실행하려면
.\gradlew.bat test --tests '*CoreUserFlowHttpIntegrationTest' --no-daemon --console=plain
```

Android 별도 영문 경로에서:

```powershell
$env:ANDROID_HOME='C:\Users\gksdn\AppData\Local\Android\Sdk'
.\gradlew.bat testDebugUnitTest assembleDebug --no-daemon --console=plain
```

추가 계약 테스트를 포함하면 현재 브랜치에서 위 2건은 실패하는 것이 재현 결과이다. 통과시키기 위해 판정 필드 검증을 제거하지 않는다.

## 6. 결과 위치와 다음 완료 조건

결과 폴더: `C:\Visual_Studio_Code\식품DB\staging-integration-20261028`

- `version-and-test-manifest.json`: 버전, 소스 지문, 테스트 집계.
- `core-http-checks.json`: 합성 HTTP 50회 상태 기록. 토큰·OTP·비밀번호 미포함.
- `core-flow-samples.json`: 프론트/AI 대조용 합성 응답.
- `ai-contract.json`, `ai-tests.xml`: 로컬 AI 계약 불일치와 기존 테스트 결과.
- `android-baseline/junit`, `android-contract-junit`, `backend-junit`: 기존 테스트와 신규 계약 검증을 분리한 결과.
- `BackendSnapshotContractTest.kt`: 프론트 전달용 재현 테스트 원본.

다음 완료 조건은 (1) 실제 인증·가족 선택을 연결한 Android 커밋, (2) 공통 판정을 사용하는 AI 커밋, (3) 백업/마이그레이션 검증된 Backend 배포 묶음, (4) 온라인 스테이징에서 승인된 범위의 API 확인, (5) 실제 기기에서 스캔→검색→옵션→추천→챗봇 UI 검증이다. 이 조건이 충족되기 전에는 전체 통합 완료로 표기하지 않는다.
