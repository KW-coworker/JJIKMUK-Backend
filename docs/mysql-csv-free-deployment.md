# CSV 없이 새 MySQL 서버에서 실행하기

현재 백엔드는 일반 실행 시 `Product.csv`와 `ProductNeighbors.csv`를 읽지 않습니다.
`PRODUCT_IMPORT_ENABLED=false`, `RECOMMENDATION_IMPORT_ENABLED=false`가 기본값입니다.
대신 새 서버의 MySQL에 **기존 DB 전체를 복원**해야 합니다. 상품 데이터만 복사하면
추천 후보, 사용자 정보, 적재 버전, Flyway 기록이 빠져 정상 기동을 보장할 수 없습니다.
또한 `backend/src/main/resources/db/migration`의 V1~V8 SQL 파일을 애플리케이션 코드와
함께 Git에 포함해야 복원된 Flyway 기록과 실행 코드가 일치합니다.

## 1. 준비

- 새 MySQL 서버는 원본과 호환되는 MySQL 8.0으로 준비합니다. 원본의 `SELECT VERSION()`과
  대상 버전을 확인하고, 가능하면 먼저 동일 버전으로 복원 시험을 합니다.
- 백업·복원용 MySQL 클라이언트(`mysqldump.exe`, `mysql.exe`)를 준비합니다.
  이 PC에는 `C:\Program Files\MySQL\MySQL Server 8.0\bin\`에 있습니다.
- 덤프는 사용자 계정·알레르기·검색/추천 이력을 포함할 수 있습니다. 저장소 밖의
  접근 제한된 위치에 보관하고 암호화된 경로로 전송합니다. Git에 올리지 않습니다.
- 원본과 대상에 각각 별도의 MySQL 옵션 파일을 만듭니다. 예를 들어
  `C:\secure\source.cnf`, `C:\secure\target.cnf`이며 내용은 아래 형식입니다.
  이 파일도 Git에 올리지 않습니다.

  ```ini
  [client]
  host=DB_HOST
  port=3306
  user=DB_USER
  password="DB_PASSWORD"
  ```

- 원본 백업 계정은 전체 애플리케이션 DB를 읽을 수 있어야 합니다. 뷰·트리거·루틴·이벤트가
  있다면 해당 메타데이터 조회 권한도 필요합니다. 대상 복원 계정에는 새 DB 생성과 테이블,
  인덱스, 데이터, 루틴/이벤트 복원 권한이 필요합니다. MySQL 계정·권한 자체는 이 덤프에
  포함되지 않으므로, 새 서버의 백엔드 접속 계정도 따로 준비합니다.
- 덤프 중 원본 DB에 테이블 변경(DDL)이 없어야 합니다. 최종 전환 때는 상품 적재와 쓰기를
  멈추고 백업하는 것이 안전합니다. `--single-transaction`의 일관성 보장은 InnoDB에 한정됩니다.

## 2. 원본 DB 확인과 백업

PowerShell에서 `backend/scripts`를 실행합니다. 아래 경로는 실제 환경에 맞게 바꿉니다.
덤프 출력 경로는 **저장소 밖의, 아직 존재하지 않는 파일**이어야 합니다.

```powershell
$mysql = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe'
$mysqldump = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe'
./backend/scripts/Verify-JjikmukDatabase.ps1 -DefaultsFile 'C:\secure\source.cnf' -MySqlExecutable $mysql
./backend/scripts/Export-JjikmukDatabase.ps1 -DefaultsFile 'C:\secure\source.cnf' -OutputFile 'D:\backups\jjikmuk-dump-YYYYMMDD.sql' -MySqlDumpExecutable $mysqldump
```

출력된 `products`·`product_neighbor_sets` 건수, `PRODUCT_DB_%`·
`PRODUCT_NEIGHBOR_DB_VERSION` 값, Flyway 성공 기록과 덤프의 SHA-256을 기록합니다.
CSV 원본의 행 수와 DB 건수는 중복 바코드 처리 등에 따라 다를 수 있으므로 비교 기준은
**덤프 직전에 원본 DB에서 Verify 스크립트가 출력한 실제 건수**입니다.
백업 실패 시 `.partial` 파일이 남습니다. 원인을 확인하기 전에는 복원에 사용하지 마세요.

## 3. 새 서버에 복원

덤프를 안전하게 새 서버로 옮긴 뒤, 전송된 파일의 SHA-256이 백업 때 출력된 값과 같은지
확인합니다. 복원 스크립트는 대상 DB가 이미 있으면 중단하고, 없는 경우에만 생성합니다.
운영 DB나 이미 사용 중인 DB 이름을 대상으로 실행하지 마세요. 중간에 실패해도 생성한 DB를
자동 삭제하지 않습니다.

```powershell
$mysql = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe'
./backend/scripts/Restore-JjikmukDatabase.ps1 `
  -DefaultsFile 'C:\secure\target.cnf' `
  -DumpFile 'D:\backups\jjikmuk-dump-YYYYMMDD.sql' `
  -DatabaseName 'jjikmuk' `
  -ExpectedSha256 'BACKUP_COMMAND_OUTPUT_SHA256' `
  -MySqlExecutable $mysql
```

덤프는 `products`뿐 아니라 `product_neighbor_sets`, `system_configs`,
`flyway_schema_history`, 사용자/이력 테이블과 인덱스를 포함합니다. 현재 JPA 설정은
`ddl-auto=validate`이며, Flyway V1부터는 기존 테이블을 변경하므로 빈 DB에 애플리케이션만
실행해서 같은 상태를 만들 수 없습니다.

## 4. 복원 검증과 백엔드 연결

원본에서 기록한 실제 건수를 아래 예상값으로 넣어 대상 DB를 검사합니다.

```powershell
./backend/scripts/Verify-JjikmukDatabase.ps1 `
  -DefaultsFile 'C:\secure\target.cnf' `
  -DatabaseName 'jjikmuk' `
  -ExpectedProductCount <원본 Verify의 products 값> `
  -ExpectedNeighborCount <원본 Verify의 product_neighbor_sets 값> `
  -MySqlExecutable $mysql
```

행 수뿐 아니라 출력된 버전 마커와 Flyway 기록을 원본과 비교합니다. 백엔드 실행 환경의
`DB_URL`을 새 서버의 `jdbc:mysql://HOST:3306/jjikmuk?...`로, `DB_USERNAME`·`DB_PASSWORD`를
새 서버 계정으로 지정합니다. `JWT_SECRET` 등 필수 비밀값도 별도로 설정합니다.
로컬에서는 Git에서 제외된 `backend/application-local.properties`를 사용할 수 있습니다.

일반 API 실행에서는 아래 값을 유지합니다.

```text
PRODUCT_IMPORT_ENABLED=false
RECOMMENDATION_IMPORT_ENABLED=false
PRODUCT_SEARCH_MODE=locate
HIBERNATE_DDL_AUTO=validate
```

검색을 `fulltext`로 운영했다면 새 MySQL에서도 `ngram_token_size=2`, `search_keywords`
백필 및 `ft_products_search_keywords` ngram 인덱스를 추가 확인한 뒤 해당 모드를 켭니다.
일단 `locate`로 기동하면 이 서버 설정 차이로 검색 검증에 실패하는 것을 피할 수 있습니다.

백엔드가 정상 기동한 뒤 `GET /api/products/{실제 원본 바코드}`로 상품을 조회하고,
로그인 후 `GET /api/recommendations/products/{실제 원본 바코드}`로 추천을 점검합니다.
원본 DB에 백업 후 새 쓰기가 발생했다면 대상은 그 변경을 포함하지 않습니다. 최종 전환 전
쓰기를 중단하고 다시 백업·복원하거나 별도 증분 동기화 계획을 세워야 합니다.

참고: [MySQL 8.0 mysqldump 공식 문서](https://dev.mysql.com/doc/refman/8.0/en/mysqldump.html),
[SQL 덤프 복원 공식 문서](https://dev.mysql.com/doc/refman/8.0/en/reloading-sql-format-dumps.html)
