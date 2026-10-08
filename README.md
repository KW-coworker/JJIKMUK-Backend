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
- [맞춤 안심 상품 추천 API](docs/safe-product-recommendation-api.md)
- [상품 통합 검색·분류 API](docs/product-classification-api.md)

Google 로그인에는 서버에서 허용할 Web OAuth Client ID를 `GOOGLE_CLIENT_ID`로 설정합니다.
DB·JWT·메일 설정은 `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, `JWT_SECRET`,
`MAIL_USERNAME`, `MAIL_PASSWORD` 환경변수 또는 로컬 설정 파일로 전달합니다.

이번 버전에는 Flyway V9~V12가 포함됩니다. 운영 적용 전 복원 DB에서 마이그레이션을
검증해야 합니다. 기존 JWT에는 `tokenVersion`이 없으므로 업데이트 후 재로그인이 필요합니다.
프로필 `PUT`은 전체 수정이며, 생략한 선택 필드는 초기화됩니다.

## 협업

작업은 기능 브랜치에서 진행하고, PR 제목은 `feat: ...`, `fix: ...` 등의
Conventional Commits 형식으로 작성합니다. PR에는 관련 커밋과 링크, 검증 결과,
리뷰 요청사항 및 이슈 번호를 기록하고, 검토 후 Squash and merge합니다.
