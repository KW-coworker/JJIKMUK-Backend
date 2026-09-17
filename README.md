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

## 협업

작업은 기능 브랜치에서 진행하고, PR 제목은 `feat: ...`, `fix: ...` 등의
Conventional Commits 형식으로 작성합니다. PR에는 관련 커밋과 링크, 검증 결과,
리뷰 요청사항 및 이슈 번호를 기록하고, 검토 후 Squash and merge합니다.
