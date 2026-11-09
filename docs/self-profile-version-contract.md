# 본인 프로필 충돌 방지 — V19 / 2026-11-10

## 변경 이유

두 기기가 같은 과거 프로필을 읽은 뒤 서로 수정하면 나중 요청이 먼저 저장된 알레르기 등을
덮어쓰던 문제를 막는다. 사용자 행을 잠근 짧은 트랜잭션 안에서 버전을 비교하고,
검증·프로필 저장·버전 증가를 함께 커밋한다. 충돌 요청은 아무 값도 저장하지 않는다.
가족 프로필 API의 version 정책은 변경하지 않는다.

## API 계약 — FE 수정 필수

| API | 변경 |
| --- | --- |
| `GET /api/users/me`, `GET /api/users/{id}` | `data.version` 추가 |
| 관리자 `GET /api/users` | 각 사용자 응답에 version 추가 |
| `PATCH /api/users/me` | 조회한 version 필수, 선택 필드 생략=유지 |
| `PUT /api/users/me`, `PUT /api/users/{id}` | 조회한 version과 nickname 필수, 선택 필드 생략=초기화 |
| `POST /api/users/me/profile/complete` | 조회한 version과 nickname 필수, 전체 제출 및 완료를 한 번에 저장 |

버전은 0 이상의 JSON 정수(Long 범위)이다. 누락/null/문자열/소수/배열/boolean/범위 초과는
400 `VALIDATION_FAILED`, field=`version`이다. 조회나 로그인만 할 때는 version을 보내지 않는다.
회원가입 요청에도 version을 추가하지 않는다. 신규 계정과 V19 적용 직후 기존 계정은 0부터 시작한다.
기존 hasPassword, profileCompleted, photoUrl 등 응답 필드는 유지한다.
프로필 응답에는 `Cache-Control: no-store`를 설정하지만 FE 자체 캐시는 별도로 userId별 분리해야 한다.

조회 응답 일부(발췌):

```json
{
  "message": "내 프로필 조회 성공",
  "data": {
    "id": 17,
    "nickname": "찍먹사용자",
    "allergies": "milk",
    "specialDiet": "lowSugar",
    "hasPassword": true,
    "profileCompleted": true,
    "version": 3
  }
}
```

해당 조회 이후의 수정:

```http
PATCH /api/users/me
Authorization: Bearer <access-token>
Content-Type: application/json

{"version":3,"allergies":"milk,peanut"}
```

성공 시 200, 최신 프로필과 `data.version=4`를 반환한다. 다른 기기의 version=3 요청은:

```json
{
  "status": 409,
  "message": "프로필이 변경되었습니다. 최신 정보를 다시 조회한 뒤 수정해주세요.",
  "code": "PROFILE_VERSION_CONFLICT",
  "field": "version"
}
```

## 세부 규칙

- `version`은 프로필 편집용이다. JWT `tokenVersion`, 가족 version과 혼용하지 않는다.
- 수정 성공마다 정확히 1 증가한다. 같은 값을 보내거나 version만 보내는 PATCH도 증가한다.
- 닉네임 중복/값 검증 실패와 버전 충돌은 증가하지 않으며 기존 값도 유지한다.
- 서로 다른 필드를 수정해도 읽었던 전체 프로필 버전이 오래됐으면 충돌이다. 자동 병합하지 않는다.
- 중간 PATCH는 profileCompleted를 바꾸지 않는다. 완료 요청은 프로필·완료 상태·버전을 함께 저장한다.
- 비밀번호/인증 세션/사진/가족/즐겨찾기 변경은 이 프로필 편집 버전을 증가시키지 않는다.
  이 기능은 사진 교체 등의 동시 수정까지 제어하는 범용 계정 버전이 아니다.
- 구형 PUT 및 관리자의 타인 프로필 수정도 검사한다. 버전 생략 호환 경로를 두지 않는다.
- 동일한 version의 두 동시 수정 요청은 하나만 성공하고 다른 하나는 409다.
- 성공 응답 유실 후 예전 요청 재전송도 409일 수 있다. GET으로 실제 저장 상태를 먼저 확인한다.

## FE 처리 순서

1. 수정 화면 진입 시 GET me로 프로필과 version을 함께 읽는다.
2. 그 화면에서 편집 중인 원본 버전과 사용자 입력을 유지한다.
3. 저장 시 해당 version과 변경할 필드를 보낸다. 새 계정의 version과 섞지 않는다.
4. 성공 시 응답 프로필/새 version을 캐시에 반영한다.
5. 409면 입력 초안을 보존하고 최신 프로필을 재조회한다. "다른 기기에서 프로필이 변경되었습니다"를 안내한다.
6. 최신 값과 내 입력을 사용자가 확인한 뒤 다시 저장할 때만 최신 version으로 제출한다.
   GET 뒤 version 숫자만 바꾸어 예전 전체 본문을 자동 재전송하지 않는다.
7. 400 field=version이면 FE 요청/배포 계약 오류를 확인한다. 401 재로그인 흐름과 구분한다.
8. 응답 유실 후 GET에서 완료/저장 결과가 확인되면 완료 처리한다. 변경 여부가 모호하면 사용자 확인을 받는다.

서버가 보장하는 것은 충돌 감지이지 모든 기기의 실시간 화면 갱신이 아니다.
다른 기기는 화면 재진입/새로고침 시 다시 조회해야 한다.

## DB 및 배포

- V19는 `users.profile_version BIGINT NOT NULL DEFAULT 0` 컬럼만 추가한다.
- 기존 계정/조건/세션을 삭제하거나 변경하지 않는다. 컬럼 기본값만 0으로 채운다.
- 2026-11-10 백업·복제 검증 후 로컬 MySQL V18~V20을 적용했다. AWS/운영에는 적용하지 않았다.
- 2026-11-09에 만든 전달용 ZIP은 V17 스냅샷이며 V18 SQL만 별도 포함한다.
  해당 ZIP을 수정하거나 덮어쓰지 않았다. 이번 V19와 새 API 계약은 그 ZIP에 없다.
- 배포 순서: 백업 → 복원한 격리 MySQL에서 V18/V19 순차 검증 → FE 버전 지원 확인 → 승인된 배포.
  Flyway 이력/체크섬을 확인하고, 수동 ALTER 뒤 Flyway 중복 실행이나 임의 repair는 하지 않는다.
- 버전 없는 구형 FE의 수정 요청은 400이 된다. FE 수정과 배포 시점/필요한 업데이트 안내를 조율한다.
- 구버전 백엔드와 신버전 백엔드를 동시에 쓰기 요청에 노출하지 않는다. 구버전은 버전을 올리지 않고
  수정할 수 있어 보호가 깨진다. 쓰기를 제한한 전환 또는 트래픽을 한 버전으로 전환하는 배포가 필요하다.
- 롤백 시 컬럼은 유지한다. 구버전으로 쓰기를 재개했다면 새 배포 전 버전 기준을 다시 검증한다.
- 이후 별도 배치/관리 도구가 nickname/allergies/diseases/specialDiet/dislikedIngredients/
  profileCompleted를 직접 변경할 때도 같은 잠금·버전 증가 규칙을 지켜야 한다.

## 검증 범위

`UserProfileVersionIntegrationTest`는 실제 JWT·MVC·DB 트랜잭션을 사용하는 격리 H2 시험이다.
동시 HTTP 수정, 기기 간 오래된 요청, 버전 형식, PUT/관리자 우회 차단, 완료 상태 원자성,
검증 실패 후 기존 값 유지, 계정 격리, 세션·가족 버전 독립성을 검사한다.
`UserProfileVersionMigrationTest`는 H2 MySQL 호환 모드에서 V19 SQL의 기존 행 보존·기본값·NOT NULL을 검사한다.
실제 MySQL/Flyway 리허설은 후속 검증에서 수행했다. FE/AWS 통합 시험은 별도이다.

2026-11-10 실행 결과: JDK 21에서 `./gradlew test bootJar --offline --no-daemon` 성공.
전체 391개 중 384개 통과, 기존 테스트 7개 스킵, 실패/오류 0개이다.
신규 프로필 버전 통합 테스트 10개와 V19 DDL 테스트 1개는 모두 통과했다.
`git diff --check`도 통과했다. 실제 MySQL 스키마/데이터와 기존 전달 ZIP은 변경하지 않았다.

위 결과는 프로필 코드 구현 시점이다. 후속 로컬 V18~V20 적용에서 실제 MySQL의 stale profile 409와
기존 값 보존도 검증했다. 최신 main 통합 전체 시험은 428건 중 420건 통과/조건부 8건 제외이다.
[최종 DB 검증·배포 안내](account-state-v18-v20-deployment.md)를 따른다. 기존 전달 ZIP과 AWS는 그대로다.
