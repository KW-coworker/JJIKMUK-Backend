# JJIKMUK-Backend

찍먹 식품 정보·검색·개인화 추천 API의 Spring Boot 백엔드입니다.

## 로컬 실행

1. MySQL에 기존 `jjikmuk` DB의 **전체 스키마와 데이터**를 복원합니다.
   `Product.csv`와 `ProductNeighbors.csv`는 Git에 포함되지 않습니다.
2. `application-local.properties.example`을 `application-local.properties`로 복사하고
   DB 접속 정보 및 `jwt.secret`을 설정합니다. 실제 설정 파일은 Git에서 제외됩니다.
3. JDK 21 환경에서 `./gradlew test`로 확인한 뒤 `./gradlew bootRun`을 실행합니다.
   일반 실행에서는 상품·추천 후보 CSV 자동 적재가 비활성화되어 있습니다.

새 MySQL 서버 이전 절차는 [CSV 없는 DB 배포 가이드](docs/mysql-csv-free-deployment.md)에
정리했습니다. 대량 상품 적재·검색 인덱스·추천 작업은 `docs/`의 단계별 가이드를 참고하세요.

## 회원 인증·프로필·추천 API

- [계정·인증·프로필 계약(A06~A13)](docs/account-auth-profile-contract.md)
- [이메일 OTP와 인증 완료 증명](docs/email-verification-api.md)
- [알레르기·식이조건 저장 계약](docs/user-preference-contract.md)
- [계정별 채팅 저장 및 FE 연동 계약](docs/account-chat-storage-api.md)
- [본인 프로필 버전 충돌 방지(V19)](docs/self-profile-version-contract.md)
- [가족 토글 계정 동기화·선택형 가져오기(V20)](docs/family-selection-sync-contract.md)
- [V18~V20 로컬 MySQL 적용 결과·서버 배포 절차](docs/account-state-v18-v20-deployment.md)
- [맞춤 안심 상품 추천 API](docs/safe-product-recommendation-api.md)
- [상품 통합 검색·분류 API](docs/product-classification-api.md)

Google 로그인에는 서버에서 허용할 Web OAuth Client ID를 `GOOGLE_CLIENT_ID`로 설정합니다.
DB·JWT·메일 설정은 `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, `JWT_SECRET`,
`MAIL_USERNAME`, `MAIL_PASSWORD` 환경변수 또는 로컬 설정 파일로 전달합니다.

스키마 변경은 Flyway V1~V20으로 관리합니다. V18은 계정별 채팅방·대화 저장 테이블,
V19는 본인 프로필 수정 버전, V20은 계정별 분석 대상 토글 저장을 추가하며,
운영 적용 전 복원 DB에서 마이그레이션을 검증해야 합니다. 구형 JWT에 `tokenVersion`이 없는 경우 재로그인이 필요합니다.
프로필 `PUT`은 전체 수정이며, 생략한 선택 필드는 초기화됩니다.
본인 프로필 `PATCH`·`PUT`·완료 요청에는 조회한 `version`이 필수입니다.
오래된 버전은 `409 PROFILE_VERSION_CONFLICT`이며 FE 연동 후 조율된 배포가 필요합니다.
가족 토글은 `GET/PUT /api/users/me/analysis-selection`으로 동기화합니다.
분석 대상 생략 시 저장된 선택을 사용하며, 미설정 계정만 본인 기본값을 사용합니다.
기기 가족 정보는 자동 이관하지 않습니다. 사용자가 확인한 항목만 명시적으로 추가합니다.

## 협업

작업은 기능 브랜치에서 진행하고, PR 제목은 `feat: ...`, `fix: ...` 등의
Conventional Commits 형식으로 작성합니다. PR에는 관련 커밋과 링크, 검증 결과,
리뷰 요청사항 및 이슈 번호를 기록하고, 검토 후 Squash and merge합니다.
