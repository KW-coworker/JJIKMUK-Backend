# 계정별 채팅·프로필 버전·가족 선택 V18~V20 배포 안내

기준: 2026-11-10. `team/main`의 `2618585` 위에 계정 저장 변경을 통합했다.
AWS 및 운영 DB에는 접속하거나 변경하지 않았다. 별도 기능 브랜치의 push/PR과 운영 배포는 다르다.

## 변경 범위

| 버전 | DB 변경 | API 영향 |
| --- | --- | --- |
| V18 | `chat_conversations`, `chat_turns` 추가 | 계정별 채팅방·대화 조회/삭제, 저장형 `/api/chat` |
| V19 | `users.profile_version BIGINT NOT NULL DEFAULT 0` 추가 | 본인 프로필 수정·완료 시 `version` 필수, 오래된 요청 409 |
| V20 | `account_analysis_selections`, `account_analysis_selection_families` 추가 | 계정별 본인·가족 토글 GET/PUT, 생략한 분석 대상에 저장 선택 적용 |

기기 가족/채팅을 자동 이관하지 않는다. 새 가족은 자동 ON 하지 않는다. 설정을 한 번도 저장하지 않은
계정만 본인 ON/가족 OFF 기본값을 사용한다. 사용자가 저장한 전원 OFF는 유지하고 `NOT_EVALUATED`로 처리한다.

## 로컬 검증 결과

로컬 `jjikmuk` V20 적용 및 최종 보존·기동 검증을 완료했다. AWS 검증 결과가 아니다.

- MySQL 8.0.44의 로컬 V17 전체 31개 테이블을 일관성 백업했다. 파일 크기는 5,716,531,614바이트다.
- 백업 SHA-256: `de3e24e839edf284d8adc99d0964f924ff96b939d68005162c0a0eb8e848fe50`
- 백업으로 새 `jjikmuk_v20_rehearsal_20261110`을 복원하고 기존 데이터의 정확한 행 수/체크섬을 대조했다.
- 실제 Flyway로 V18~V20 3건을 적용하고 전체 이력 검증 및 재실행 0건을 확인했다.
- 복제 MySQL에 실제 백엔드/JWT/HTTP를 연결해 62항목을 통과했다. 외부 AI 대신 로컬 응답 서버를 사용했다.
  - 두 기기의 프로필·토글 공유와 stale version 409, 동시 토글 수정에서 단 하나의 성공
  - 다른 계정의 가족 선택·채팅 조회 차단, 채팅 생성/메시지 재시도 중복 방지
  - 실제 상품·챗봇의 저장 가족 선택 반영, 전원 OFF 처리, 대상 변경 시 과거 대화 문맥 분리
  - 가족 삭제 시 선택 제거/버전 증가, 회원 탈퇴 시 대화·선택 정리, MySQL FK/유니크 제약
- 실패한 검증 스크립트 시도도 보존했다. pending 마이그레이션 사전 검사 순서, 테스트 닉네임 및
  유효 바코드 선택을 보완한 뒤 재검증했다. 서비스 코드/DB 판정 기준을 완화하지 않았다.
- 복제 시험에서 만든 계정을 제거한 뒤 기존 전체 데이터가 보존됐음을 다시 확인했다.
- 원본 로컬에도 동일한 3건만 적용했다. 테이블 31→35개, Flyway 이력 18→21행(기존 baseline 포함),
  신규 네 테이블 0행, 기존 회원 10명의 profile_version=0이다. 원본에는 테스트 계정을 만들지 않았다.
- 상품 1,348,425건, 기존 회원 10명, 이력 2건, 추천 후보 집합 233,658건과 기존 이미지 URL이 그대로 유지됐다.
  보호 대상 기존 테이블은 EXTENDED 체크섬, users는 새 컬럼을 제외한 모든 필드의 해시,
  기존 Flyway는 이력/체크섬을 대조했다. 전체 원본 행 수도 동일하다.
- 적용된 원본 DB에서 Hibernate validate로 기동 성공, 공개 필터 200/비로그인 선택 조회 401,
  Flyway 최종 validate 성공을 확인했다. 기동 시험은 외부 AI/회원 생성 없이 종료했다.
- JDK 21 `test bootJar --offline --no-daemon`: 428건 중 420건 통과, 조건부 8건 제외, 실패/오류 0건.
  제외 항목은 원본 CSV/외부 평가셋/별도 Python 연동 조건이 필요한 기존 시험이며 V18~V20 시험은 제외하지 않았다.
- 배포 도구 모의 단위 시험: CD 85건 중 78건 통과/Windows에서 Linux 전용 7건 제외,
  운영 도구 39건 및 챗봇 도구 11건 통과. 실제 AWS 명령은 실행하지 않았다.

백업·검증 로그는 개발 PC의 비공개 작업 폴더에 보관하며 Git에 포함하지 않는다.
기존 2026-11-09 전달 ZIP과 SQL은 갱신하지 않았다. **이번 백업도 적용 전 V17 복구용**이며
V20 배포용 신규 덤프가 아니다. SQL 파일을 전달할 때는 버전·용도·해시를 반드시 구분한다.

## 서버 담당자 배포 절차

1. 실행 커밋, 실제 DB 호스트/스키마, Flyway 성공 버전과 체크섬, Hibernate/Flyway 실행 설정을 먼저 확인한다.
   V17 미만이면 선행 마이그레이션과 V17 영양 기준량 백필까지 별도로 점검한다. 코드 배포가 백필을 대신하지 않는다.
2. 서버 자체의 최신 DB 전체 백업을 만들고 해시와 복원 가능 여부를 확인한다. 기존 회원·가족·즐겨찾기·이력·
   인증 세션·`chatbot_logs`를 보존한다. **개발 PC의 전체 덤프를 운영 DB에 덮어쓰지 않는다.**
3. 그 운영 백업으로 별도 복원 DB를 만들고, 이번 커밋의 Flyway V18→V19→V20을 먼저 검증한다.
   새 테이블의 이름 충돌, FK 타입, 데이터/이력 보존, 반복 migrate 0건, 실제 API를 확인한다.
   수동 CREATE/ALTER 후 임의 baseline/repair/checksum 변경으로 통과시키지 않는다.
4. FE가 프로필 `version` 필수를 지원하는지 확인한다. 미지원 APK는 수정·프로필 완료 요청이 400이 되므로
   FE 배포와 전환 시점을 조율한다. 구버전 BE와 신버전 BE가 동시에 프로필을 쓰지 않도록 한다.
5. 승인된 작업 시간에 쓰기 요청을 잠시 제한하고, 운영 접속 대상에 바인딩된 승인된 Flyway 실행 경로로
   미적용 마이그레이션만 적용한다. 현재 CI/CD가 Flyway를 비활성화했다면 **main merge만으로 DB는 바뀌지 않는다.**
   배포 가드가 DB 준비를 확인하도록 하고, 가드를 우회하거나 GitHub Actions에서 임의 SQL을 실행하지 않는다.
6. 동일 커밋의 BE를 배포하고 Hibernate schema validate·기동·로그인·프로필 조회/수정·가족 토글·계정별 채팅을
   승인된 테스트 계정으로 확인한 뒤 트래픽을 연다. AI의 `chat-analysis-v2` 확인 헤더/동의 계약도 유지해야 한다.
7. 실패하면 쓰기를 제한하고 원인을 확인한다. MySQL DDL은 트랜잭션 전체 롤백을 보장하지 않는다.
   신규 대화/선택 테이블이나 profile_version을 임의 삭제하지 않는다. 구버전 BE는 토글과 버전 보호를 무시하므로
   기능 제한/안내 없이 조용히 되돌리지 않는다. 복원은 백업 이후 발생한 운영 기록 손실을 검토한 승인 작업으로만 한다.

이 PR을 main에 합치면 기존 자동 CD가 실행될 수 있다. **DB 준비와 FE 계약 확인 전에는 merge하지 않는다.**
자동 배포 파이프라인, AWS 설정, 운영 스키마를 이번 작업에서 변경하지 않았다.

## FE·AI 전달 사항

- 프로필 GET 응답의 `version`을 편집 화면과 함께 보관하고 PATCH/PUT/프로필 완료 요청에 포함한다.
  409 `PROFILE_VERSION_CONFLICT`이면 초안을 보존하고 최신 정보와 사용자 의사를 확인한다. 숫자만 바꿔 자동 덮어쓰지 않는다.
- `GET /api/users/me/analysis-selection`으로 복원하고 `PUT`에 `version`, `includeSelf`, `familyProfileIds`를 모두 보낸다.
  409 `ANALYSIS_SELECTION_VERSION_CONFLICT`도 재조회/확인한다. 가족 데이터 version과 선택 version은 별개다.
- 저장 토글 사용 시 상품·추천·챗봇의 요청별 분석 선택을 생략한다. 챗봇 Body `profile`/`profiles`도 생략한다.
  `profiles: []`는 서버 설정 사용이 아니라 해당 요청의 전원 OFF이다. 명시적 요청은 서버 설정을 덮어쓰지 않는다.
- 로컬 가족을 사용자 확인 없이 업로드하지 않는다. 사용자가 선택한 항목만 기존 가족 POST로 생성하고 서버 ID를 사용한다.
  가족 생성 POST는 멱등 import가 아니므로 응답 유실 시 자동 재전송하지 않는다.
- 채팅방 생성 후 `/api/chat`에 `conversationId`·`clientMessageId`를 함께 보낸다. 저장형 요청에는 기기 chatHistory를 보내지 않는다.
  JWT 계정별 목록으로 복원하고, 계정 전환 시 이전 캐시/요청을 정리하며 늦은 응답은 버린다.
- AI 요청 계약/확인 헤더는 여전히 `chat-analysis-v2`다. 현재 `analysisContext`가 판정 근거이며,
  저장용 ID는 AI에 전달하지 않는다. FE/AI 실제 기기 연동과 AWS 배포는 별도 확인이 필요하다.

상세: [채팅 저장](account-chat-storage-api.md), [프로필 버전](self-profile-version-contract.md),
[가족 선택·확인형 가져오기](family-selection-sync-contract.md).

## 검증 스크립트 재사용

`scripts/Verify-AccountStateV20.java`는 JDK 21 source launcher로 실행한다. 빌드한 bootJar에서
`BOOT-INF/classes`, `BOOT-INF/lib/*`를 별도 로컬 폴더에 추출해 classpath를 구성한다.
DB 자격증명은 환경변수로만 전달하고 로그·명령행·Git에 기록하지 않는다.

- 환경: `V20_SCHEMA`, `V20_URL`, `V20_USER`, `V20_PASSWORD`, `V20_UUID`, `V20_HOST`, `V20_OUTPUT`
- `V20_URL`은 `jdbc:mysql://127.0.0.1:<port>/<schema>?...`만 허용한다.
  스키마는 `jjikmuk` 또는 `jjikmuk_v20_rehearsal_YYYYMMDD`, 서버 UUID/hostname은 실제 대상과 일치해야 한다.
- `migrate`: V17에서만 시작하여 정확히 3건 적용, 재검증, 재실행 0건 확인.
  원본 `jjikmuk`에는 백업/복제 검증 후 `V20_ALLOW_LOCAL_APPLY=backup-and-clone-verified` 확인값이 추가로 필요하다.
- `smoke`: 복제 DB에서만 허용. 임시 계정·가족·대화를 만들고 정리하며 외부 AI를 호출하지 않는다.
- `verify`: V20/Flyway/schema 제약 읽기 검증. `startup`: 로컬 기동과 비로그인 GET만 확인하며 테스트 계정을 만들지 않는다.
- 각 실행의 `V20_OUTPUT`은 새 폴더를 사용한다. 운영 DB/SSH 터널을 이 도구에 연결하지 않는다.
  이 도구는 백업/운영 배포 도구가 아니며, 백업·원본 대조·복제 검증은 별도로 선행해야 한다.
