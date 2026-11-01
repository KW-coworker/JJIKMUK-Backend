# V16 배포·검증 안내

대상: 가족 `relation`·`emoji`, 계정별 상품 즐겨찾기, 최근 본 상품의 분석 대상 분리.
요청·응답 계약은 [family-favorites-recent-v1.md](family-favorites-recent-v1.md)를 따른다.

## 2026-11-02 로컬 실행 결과

- MySQL 8.0.44, 로컬 jjikmuk: V15 → V16 성공. 재실행 0건, Flyway validate 성공.
- 새 전체 백업 5,134,277,262바이트 생성 후 별도 복제 DB 복원·대조 완료. 비공개 SHA-256 및 원본 필드 해시 증거는 로컬 작업 기록에 보관했다.
- 복제 DB에 먼저 적용한 뒤 실제 HTTP/DB 검증 41개 항목 통과. 테스트 계정 생성·삭제와 행동 쓰기는 복제 DB에서만 수행했다.
- 원본 적용 전후 상품 1,348,425건, 추천 세트 233,658건, 사용자 10건, 이력 2건 유지. 해당 데이터와 분류 멤버십·가족·ID 시퀀스의 기존 필드 해시가 일치했다. 속성 기록 건수 1,348,425건 유지.
- H2 전체 회귀: 313개 중 307개 성공, 6개 조건부 평가 테스트 건너뜀, 실패/오류 0. bootJar 성공.
- AWS/운영 DB와 Android 코드는 변경하지 않았다. 이 검증은 실제 기기 QA나 운영 규모 histories 성능 검증을 대신하지 않는다.

## 배포 순서

1. 대상 서버와 DB를 명시하고 현재 Flyway V15 성공 여부, 상품 ID 누락 여부를 확인한다. 상품 ID는 기기별 임시 번호나 바코드가 아니며 데이터셋 갱신 후에도 재사용하지 않는다.
2. DB 전체 백업과 복원 가능 여부를 확인한다. 백업에는 계정·인증·행동 정보가 있으므로 공개 저장소/PR에 첨부하지 않는다.
3. 운영과 같은 MySQL의 별도 복제 DB에서 V16을 적용한다. 기존 migration checksum을 수정하거나 `repair`로 우회하지 않는다.
4. 가족·이력의 기존 값 보존, 새 열 기본값, utf8mb4 이모지, 즐겨찾기 유일성/계정 외래키, 반복 migrate 0건을 확인한다. 실제 MySQL에서 API 요청도 검증한다.
5. histories ALTER/인덱스 생성 시 metadata lock·동시 쓰기·작업 시간을 확인하고 승인된 시간대에 운영에 적용한다. MySQL DDL은 일반 데이터 트랜잭션처럼 전체 롤백되지 않는다. 부분 실패 시 자동 재시도/repair 대신 스키마와 Flyway 상태를 대조한다.
6. V16을 필요로 하는 백엔드를 배포한다. `ddl-auto=validate`, Flyway 적용을 유지한다. V16 없이 새 Entity를 배포하면 시작에 실패할 수 있다.
7. 로그인 → 가족 조회/수정 → 좋아요 등록/목록/해제 → self/selected/none 상세 조회 → 최근 목록을 확인한다. 실제 앱을 통해 다른 기기에서도 같은 계정의 데이터가 보이는지 확인한다.

운영으로 로컬 전체 덤프를 덮어쓰지 않는다. 운영 사용자 데이터를 유지하면서 **버전 관리되는 V16 마이그레이션**을 적용하는 작업이다. 이 브랜치의 push/PR은 운영 배포나 DB 적용을 뜻하지 않는다.

## 변경되는 DB 구조

| 대상 | 변경 |
|---|---|
| family_profiles | nullable `relationship`, `emoji`, VARCHAR(32), utf8mb4 |
| histories | `analysis_mode` 기본 self, `personalization_allowed` 기본 true, 조회용 인덱스 2개 |
| product_favorites | 계정·productId 유일 키, users ON DELETE CASCADE, 생성 시각·바코드 보관 |

API 필드명은 **relation**이고 내부 DB 열만 relationship이다. 상품 테이블 교체를 위해 product_favorites → products 외래키는 만들지 않는다.

기존 FAVORITE 이력으로 현재 찜 상태를 추정해 채우지 않는다. 앱 로컬 가족/좋아요 이전은 FE와 사용자 동의·중복 정책을 정한 후 별도로 수행한다. 과거 기록에 없던 분석 대상은 소급 추정하지 않는다.

## 검증 도구

- 격리 H2 회귀 테스트: `./gradlew test bootJar`
- MySQL 검증: `scripts/Verify-FamilyFavoritesV16.java` (Java 21 source-file 실행)
- Java classpath는 같은 빌드의 bootJar를 별도 작업 디렉터리에 풀어 `BOOT-INF/classes`와 `BOOT-INF/lib/*`로 구성한다. 플랫폼별 classpath 구분자를 사용한다. 추출물/로그/덤프는 Git 외부에 둔다.
- 환경변수: `V16_URL`, `V16_SCHEMA`, `V16_USER`, `V16_PASSWORD`, `V16_UUID`, `V16_HOST`, `V16_OUTPUT`. 자격증명은 명령행·Git·보고서에 넣지 않는다.
- JDBC URL은 127.0.0.1만 허용한다. UUID와 MySQL hostname을 별도 확인하며 AWS/원격 DB를 대상으로 실행하지 않는다.
- `verify`: V16/Flyway/열/인덱스/외래키를 읽기 전용 확인한다.
- `migrate`: V15 → V16 한 건 적용, checksum 검증, 재실행 0건을 확인한다. 로컬 원본 jjikmuk에는 백업과 복제 검증이 완료된 뒤 `V16_ALLOW_LOCAL_APPLY=backup-and-clone-verified`를 명시해야 한다. 이 값은 승인 의사를 나타내며 백업을 자동 생성하거나 검증하는 기능은 아니다.
- `smoke`: `jjikmuk_v16_rehearsal_YYYYMMDD_8자리hex` 형식의 **폐기 가능한 복제 DB에만** 테스트 계정을 만들고 API를 호출한다. localhost 임시 포트와 ddl validate를 사용하며 CSV 적재·백필·평가 작업은 비활성화한다. 원본 jjikmuk에서는 실행을 거부한다.
- 실패한 clone은 진단을 위해 유지하며 운영/원본에 적용하지 않는다. 테스트 로그에는 토큰/응답 본문을 출력하지 않는다.

## FE 연동 핵심

- 가족 생성/수정/응답: nullable `relation`, `emoji`. PATCH 생략은 유지, null/공백은 해제다.
- 하트는 `PUT/DELETE /api/users/me/favorites/{productId}`. 성공 후 별도 FAVORITE 이벤트를 보내지 않는다.
- 좋아요 목록과 `view=recent` 이력은 `data.items` 객체 구조다. 기존 전체 이력의 `data` 배열과 구분한다.
- 상세 GET은 self/selected/none 모두 로그인 계정의 최근 본 상품으로 자동 기록한다. 전원 OFF에도 Bearer를 유지하며 중복 SCAN/DETAIL_VIEW를 전송하지 않는다.
- family/none 조회 이력은 본인 취향 학습에서는 제외한다.
- 이번 작업은 실시간 push 동기화가 아니다. 기기 로그인·화면 재진입 시 서버 데이터를 재조회한다.
