# 최초 DB 구조 준비

사용자는 2026-11-10에 원본 V17~V20 DB 준비부터 백엔드 CD 설치·배포·최종 검증까지 승인했다. 이 실행기는 그중 DB 준비만 수행한다. 상품 덤프·이미지·영양 데이터는 가져오지 않는다.

`backend-initial-db.yml`은 main·정확한 커밋·새 요청·최초 시도·CD OFF 조건을 검사하고 원본 JAR를 테스트·빌드한다. 기존 실행 역할로 지정 RDS의 암호화·자동 백업·최근 복원 시점을 확인하고 수동 스냅샷을 한 번 생성한다. 스냅샷이 available이고 현재 main이 같을 때만 고정 SSM 명령을 보낸다. 사용자에게 CloudShell이나 인증 파일을 다시 요청하지 않는다.

호스트에서는 관측한 기존 JAR·실행 인자·환경·설정 지문을 대조한다. DB V1~V16 이력과 V17~V20 미적용 상태가 정확할 때만 원본 SQL 네 개를 적용한다. 앱 내부 Flyway는 계속 OFF다. 수동 적용에는 같은 JAR의 Flyway 11.14.1, MySQL 드라이버 9.7.0을 사용한다. 비밀번호와 JDBC URL은 서버 내 메모리·stdin 파이프에만 있고 GitHub·SSM 출력으로 내보내지 않는다.

적용 후 기존 컬럼·인덱스·외래키 보존, 새 테이블의 컬럼·기본값·고유 인덱스·외래키, SQL 이력·체크섬을 확인한다. HTTP 여섯 항목을 검사한 뒤 기존 앱과 설정의 무변경을 다시 대조한다. 백엔드·챗봇·OCR 서비스를 재시작하지 않는다.

작업은 새 폴더 `/opt/jjikmuk-initial-<묶음해시16자리>`, SSM 다운로드 폴더, 고정 감사 폴더 `/var/lib/jjikmuk-backend-initial-db-20261110`를 생성·보존한다. 임시 systemd 서비스 한 개에 전체 실행 시간과 프로세스 그룹 종료를 설정한다. 기존 서비스 설정은 바꾸지 않는다.

오류 또는 시간 초과이면 원본 기록과 부분 결과를 보존하고 자동 재실행·Flyway repair·baseline·DROP·데이터 복원을 하지 않는다. MySQL DDL은 클라이언트를 종료해도 서버에서 이미 완료됐을 수 있으므로 상태를 다시 조사해야 한다. JAR 롤백과 DB 복원은 별개다.

검증은 합성 데이터의 일회용 MySQL에서 원본 네 SQL 적용, 기존 행 보존, 기본값·인덱스·외래키, 재실행 거절을 검사한다. 별도 Linux 실패 주입으로 시간 초과 시 분리된 자식 프로세스까지 종료됨을 확인한다. 이 검증용 DB의 baseline 16은 테스트에서만 만들며 운영 이력은 변경하거나 꾸미지 않는다.

근거: [Flyway target](https://documentation.red-gate.com/flyway/reference/configuration/flyway-namespace/flyway-target-setting), [Flyway validate](https://documentation.red-gate.com/flyway/reference/commands/validate), [systemd-run](https://freedesktop.org/software/systemd/man/latest/systemd-run.html).
