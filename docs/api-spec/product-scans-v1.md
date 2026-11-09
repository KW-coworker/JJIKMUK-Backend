# 스캔 사진 → 상품 후보 목록 API (기본 비활성)

2026-11-09. 검토 대상 추가 계약. 기존 `/api/ocr` 및 수동 상품 검색 계약을 바꾸지 않는다.

## 목적과 처리 흐름

사진 → 기존 검출기·인식기 → 여러 OCR 문구로 로컬 상품 인덱스 검색·재정렬 → 실제 DB 상품 일괄 확인 → 순위가 있는 후보 목록.
정확한 SKU 하나를 확정하지 않으며 용량 차이는 허용한다. 상품명·맛을 우선하고 브랜드를 보조 근거로 쓴다. 이 목록은 알레르기·개인 적합성 판정이 아니다.

유료 사진 재시도는 별도 기능이다. 근거가 부족하고 서버 양쪽 허용 설정·승인된 개발 계정·공유 호출 예산이 모두 있을 때만 최대 1회 시도한다. 현재 기본 OFF이며 실제 유료 호출은 검증하지 않았다. 사용자에게서 받은 동의를 임의 생성하지 않는다. 일반 사용자 공개 전에는 별도 동의 UX/계약이 필요하다.

## 요청

`POST /api/product-scans`

- 기존 앱 JWT: `Authorization: Bearer <access-token>`
- `Idempotency-Key`: 촬영/선택한 사진에 부여한 소문자 canonical UUID v4. 같은 사진의 결과 재조회에는 같은 키를 유지한다.
- `Content-Type: multipart/form-data; boundary=...`
- 파일 파트 **image 하나**, JPEG/PNG, 최대 10MiB. 다른 파일·텍스트 파트는 거절한다. 전체 요청 상한은 10MiB+64KiB.
- 앱은 사용자 ID, 모델, 카탈로그 버전, 유료 호출 허용 여부를 보내지 않는다. 로그인 주체와 운영 설정은 백엔드가 결정한다.
- 클라이언트 자동 재시도·리다이렉트·인증 실패 후 사진 재전송 없음. 전송 전 기존 세션 갱신은 유지한다.

## 성공 예시 (모두 가상 데이터)

```json
{
  "message": "상품 스캔 결과",
  "data": {
    "schemaVersion": "scan-list-v1",
    "scanId": "d4e760c2-977a-4f06-989e-3ee1f3716268",
    "requestId": "f360f06f-04f5-44a8-a053-6c754dc98829",
    "catalogVersion": "fixture-v1",
    "status": "MATCHES_FOUND",
    "method": "LOCAL_OCR_MATCHING",
    "gptUsed": false,
    "dbAbsenceConfirmed": false,
    "products": [{
      "product": {
        "productId": 2,
        "barcode": "NO_BARCODE_ROW_2",
        "productName": "시험새우칩",
        "manufacturer": "시험제조사",
        "imageUrl": null,
        "allergy": null
      },
      "analysis": null
    }]
  }
}
```

- `X-Request-ID` 응답 헤더는 `data.requestId`와 같다. `Cache-Control: no-store`.
- `MATCHES_FOUND`: 1~50개. 배열 순서를 그대로 표시한다. 별도 키워드 GET을 호출해 다시 정렬하지 않는다.
- `MANUAL_SEARCH_REQUIRED`: products는 `[]`. 직접 검색/재촬영으로 안내한다. DB에 없다고 확정하는 뜻이 아니다.
- `method`: LOCAL_OCR_MATCHING 또는 IMAGE_GPT_MATCHING. 후자인 경우에만 `gptUsed=true`.
- `dbAbsenceConfirmed`: 항상 false. 검색 실패를 DB 미등록 증거로 사용하지 않는다.
- `analysis`: 반드시 null. nullable 상품 필드도 키를 생략하지 않는다.
- 상세 진입에는 기존 계약의 **barcode 문자열을 그대로** 사용한다. 무바코드 상품의 `NO_BARCODE_ROW_...`도 유효한 내부 조회 키다. productId를 barcode로 바꾸지 않는다.
- 스캔 직후 검색창은 빈 값으로 두고, 사용자가 직접 검색하면 기존 상품 검색 API를 사용한다.
- 완료 결과는 24시간 재사용한다. 재사용 응답의 gptUsed는 과거 처리 방식이며 추가 과금 횟수가 아니다. 실패/진행 중/만료 기록은 자동 재실행하지 않는다.

## 실패

새 API의 실패는 flat `{ "status": 503, "code": "CATALOG_MISMATCH", "message": "..." }` 형식이다. 기존 OCR 오류 형식은 변경하지 않는다. 기존 JWT 필터 오류는 기존 인증 계약을 따른다.

| HTTP | 대표 코드 | 앱 처리 |
|---|---|---|
| 400/413/415/422 | INVALID_REQUEST / IMAGE_TOO_LARGE / UNSUPPORTED_IMAGE / INVALID_IMAGE | 사진·요청 확인 |
| 401/403 | 기존 JWT·프로필 오류 | 기존 인증 복구/프로필 완료 흐름; 사진 자동 재전송 금지 |
| 409 | IDEMPOTENCY_KEY_REUSED / SCAN_OUTCOME_UNKNOWN | 결과 불명확 안내; 자동 재실행 금지 |
| 429 | SCAN_BUSY / RATE_LIMITED | Retry-After 참고, 사용자 재시도만 허용 |
| 503 | SCAN_DISABLED / INDEX_NOT_READY / CATALOG_MISMATCH | 새 기능 준비 상태 점검. 빈 정상 결과로 처리하지 않음 |
| 502/504 | SCAN_UPSTREAM_FAILED / SCAN_UPSTREAM_INVALID_RESPONSE / SCAN_TIMEOUT_OUTCOME_UNKNOWN | 기술 오류. DB 미등록·GPT 필요로 판단하지 않음 |

## 백엔드 설정과 보존 범위

| 설정 | 기본값 | 의미 |
|---|---|---|
| scan.enabled | false | 새 API 활성화 |
| scan.catalog.version | 빈 값 | 운영 products 데이터셋 버전 |
| scan.catalog.source-sha256 | 빈 값 | 해당 데이터셋 SHA-256 |
| scan.catalog.row-count | 0 | 해당 데이터셋 행 수 |
| scan.image-fallback.enabled | false | 유료 사진 재시도 허용 스위치 |
| scan.image-fallback.approved-user-ids | 빈 값 | 별도 승인된 개발 계정 ID 목록 |
| ocr.proxy.base-url / service-token | 기존 설정 | 기존 비공개 OCR 주소·내부 토큰 재사용 |

Spring 환경변수 이름은 각각 SCAN_ENABLED, SCAN_CATALOG_VERSION, SCAN_CATALOG_SOURCE_SHA256, SCAN_CATALOG_ROW_COUNT, SCAN_IMAGE_FALLBACK_ENABLED, SCAN_IMAGE_FALLBACK_APPROVED_USER_IDS다. 비밀값을 저장소에 넣지 않는다.

`ProductDatasetMarker`로 products 테이블의 기존 데이터셋 메타데이터를 SELECT하고 설정과 비교한다. 후보를 barcode로 한 번에 읽고 productId·상품명·제조사까지 대조한다. 불일치면 503으로 중단한다. DB에 쓰거나 메타데이터를 새로 덮어쓰는 코드/마이그레이션은 없다.

새 API는 별도 JWT 체인·동시 1건·3초 간격 제한을 사용한다. 비공개 OCR의 기존 단일 worker/업로드 보호도 공유한다. 사진 요청이 worker를 점유하는 동안 기존 OCR 요청이 BUSY가 될 수 있으므로 활성화 전에 실제 부하 검증이 필요하다.

## 활성화 전제와 담당자 확인

1. OCR 담당: 보존된 OCR 기준 소스와 현재 모델을 사용한 로컬 패키지, RO catalog/jamo/DF 인덱스, 영속 요청 원장을 준비한다. 운영 DB와 인덱스의 실제 일치 확인이 아직 남아 있다.
2. 백엔드 담당: 본 PR 계약·JWT·일괄 조회·기존 기능 회귀 검토 후 병합 여부 결정. 설정만 채워 검증을 생략하면 안 된다.
3. 프론트 담당: 연결 PR 검토. 기본 false인 `jjikmuk.scanListEnabled`를 테스트 APK에서만 true로 빌드한다. 이전 APK는 기존 경로 유지.
4. 별도 AWS 승인 후 OCR → 백엔드 → 테스트 APK 순으로 연결 점검한다. HTTPS Base URL 및 기존 API 주소 변경은 필요 없다.
5. 실제 모델을 포함한 Linux 메모리/지연·RDS 조회·휴대폰 목록/상세·기존 기능을 확인한 뒤 활성화한다. 문제 시 새 기능을 OFF하고 기존 경로 APK를 사용한다. DB 롤백/모델 교체는 필요 없다.
6. GPT 사진 경로는 모의 테스트만 통과했다. 실제 모델 이미지 지원·출력·공유 예산을 별도 승인된 유료 시험으로 확인하기 전 켜지 않는다.

## 검증 근거와 한계

- 백엔드 전체 369개 중 363 PASS, 기존 6 SKIP, 실패 0 + bootJar 성공.
- 신규 JWT 검사: 일반·Google·연결 계정의 **서버 JWT** 수용, 만료·로그아웃·폐기·삭제·프로필 미완료 거절. Google OAuth 토큰 발급 문제를 해결했다는 뜻은 아니다.
- Python HTTP multipart/이미지 디코더/worker/검색/영속 원장 → Kotlin proxy/모의 DB 일괄조회 → Android parser fixture 연결 성공. 실제 모델·RDS는 대체 객체다.
- Android 358 PASS, 기능 ON APK 빌드 성공. Python 전체 125 PASS; 최종 이미지 응답 변경 후 관련 24개 재검사 PASS.
- 저장된 OCR 196건에서 포팅 전후 상위 50개 순서·게이트 판단 196/196 동일. 이번 작업으로 정확도가 추가 향상됐다는 지표가 아니다.
- 운영 DB/인덱스 일치, AWS, Linux 이미지, 실제 휴대폰, 실제 이미지 GPT 호출은 미검증. 병합·배포·유료 호출 없음.

로컬 선택적 wire 검사: OCR 패키지의 `integration_server.py`로 loopback fixture 서버 실행 후 SCAN_TEST_OCR_URL과 SCAN_TEST_PUBLIC_OUTPUT을 지정해 `./gradlew test bootJar`. 외부 서버 주소는 테스트가 거부한다. 일반 CI에서는 이 검사 1개가 추가로 건너뛰어진다.
