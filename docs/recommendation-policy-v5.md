# 추천 조건·식단 UNKNOWN·평가 기준 변경 (2026-10-23)

현재 정책 버전: `unified-hard-constraints-evidence-v5.1`. v5의 조건 통일에 원재료 충돌 검사를 추가했다.

## 1. 동일한 필수 조건

`GET /api/products/safe-recommendations`와 `GET /api/recommendations/products/{barcode}`는
`RecommendationPolicy.requiredFilters`에서 `specialDiet + 기존 질병 파생 조건`을 합친다.
사용자 프로필에 필수/선호 구분이 없으므로 선택한 식단을 임의 완화하지 않는다.
질병→식단 매핑, 영양 분류 임계값, 개인화 점수 가중치는 이번에 새로 정하지 않았다.

| 상황 | 홈 추천 | 대체 상품 추천 |
|---|---|---|
| 알레르기 PASS + 식단 PASS | 반환 가능 | 유사도·개인화 정렬 후 반환 가능 |
| 알레르기 DANGER / 식단 MISMATCH / 기피 성분 확인 | 제외 | fallback에서도 제외 |
| 알레르기 또는 식단 UNKNOWN, 명시적 충돌 없음 | 제외 | 검증 후보가 없을 때만 별도 확인 필요 대안 최대 1개 |
| 반환 가능한 후보 없음 | EMPTY | ACTION_REQUIRED + 다음 행동 |

홈의 `PREFERENCE_MATCHED`, `preferences`, `preferenceFilterIds`는 호환을 위해 이름만 유지한다.
`preferenceRelaxed=false`이며 `MIXED/PREFERENCE_RELAXED`는 더 이상 생성하지 않는다.
새 필드: `requiredDietFilterIds`, `policyVersion`, 각 상품의 `dietConstraints`,
`exclusions.dietMismatch/dietUnknown`. health 제외 수는 diet 제외 수의 부분집합이므로 합산하지 않는다.
홈은 탐색 상한 5000개 때문에 EMPTY여도 hasNext=true가 가능하다. 두 API의 후보 풀과 순위까지 같다는 의미는 아니다.

## 2. 개별 식단 판정

기존 상품 Boolean 12개와 DB 스키마는 유지한다. 추천 시 요구된 속성마다 `attributes`를 계산한다.

```json
{
  "key": "lowSugar",
  "status": "UNKNOWN",
  "storedValue": false,
  "evidenceOrigin": "INFERRED",
  "confidence": 0.8,
  "reason": "MISSING_OR_INVALID_EVIDENCE",
  "ingredientEvidence": []
}
```

- `MET`: 근거 검사 통과 + 저장 Boolean true.
- `NOT_MET`: 비건 원재료의 명시적 충돌 또는 근거 검사 통과 + 저장 Boolean false.
- `UNKNOWN`: 명시적 충돌이 없으며 Boolean과 무관하게 근거 검사 실패.
- reason: `UNRELIABLE_ORIGIN`(식단 UNKNOWN/IMPUTED), `INSUFFICIENT_CONFIDENCE`(저장 신뢰도 없음/0.5 미만),
  `MISSING_OR_INVALID_EVIDENCE`(원재료/영양 근거 부족), `STORED_CLASSIFICATION`(저장 분류 사용).
- v5.1 추가 reason: `EXPLICIT_INGREDIENT_CONFLICT`(비건 원재료 충돌),
  `AMBIGUOUS_INGREDIENT_EVIDENCE`(향·무첨가·식물성 대체 표현 등으로 동물성 여부 단정 불가).
  `ingredientEvidence`는 판정에 사용한 성분 키워드 배열이며 해당 근거가 없으면 빈 배열이다.
- 비건은 젓갈·액젓·육류·유제품·계란 등의 명시적 원재료를 저장 Boolean/출처/신뢰도보다 먼저 검사한다.
  충돌 시 저장값이 true이거나 신뢰도가 결측이어도 NOT_MET이며 두 추천 서비스와 확인용 후보에서 제외한다.
  코코아버터·땅콩버터 등 식물성 동명 표현과 서로 다른 원재료 문자열의 연결로 인한 오탐을 방지한다.
  공장 공동 사용 알레르기 경고는 비건의 실제 원재료로 간주하지 않는다.
- 식단 신뢰도를 원재료 존재만으로 0.7/0.8로 새로 만들어 주던 요청 시점의 보정은 제거한다.
- 채식 6종·글루텐프리는 유효한 원재료 문자열을 요구한다. 공백/null/N/A/정보 없음 등은 결측 취급한다.
- 영양 5종은 해당 수치가 유한한 0 이상 값이며 영양 출처가 SOURCE/NORMALIZED/CALCULATED여야 한다.
  원본 값 0은 결측이 아니지만 UNKNOWN/IMPUTED/INFERRED 영양값만으로 통과시키지 않는다.
- 속성 중 NOT_MET가 하나라도 있으면 종합 MISMATCH, 없고 UNKNOWN이 있으면 UNKNOWN, 모두 MET면 PASS이다.
  MISMATCH와 UNKNOWN이 섞여도 failedFilters와 uncertainFilters를 각각 보존한다.

중요한 한계: 이 변경은 기존 저장 분류의 **근거 충분성 검사 및 일부 명시적 비건 충돌 검사**이지 공식 비건/글루텐프리 인증이나
영양 기준 재계산이 아니다. 현재 출처·신뢰도는 상품 단위여서 개별 분류의 원본 라벨/추론 이력을
완전히 복원하지 못한다. INFERRED 분류도 명시된 근거 검사를 통과하면 사용하며 실제 정확도 검수가 필요하다.
검색용 Boolean 필터는 그대로이다. 안전 판단 UI는 product.vegan 같은 Boolean만 보지 말고
추천 응답의 dietConstraints와 attributes를 사용한다. 실제 섭취 안전을 보증하는 값이 아니다.

## 3. 오프라인 평가

V13은 평가용 3개 테이블만 확장한다. 상품이나 사용자 데이터의 일괄 업데이트는 없다.
기존 평가 사례는 RECOMMENDATION으로 유지하고, 기존 실행의 새 지표는 NULL(미측정)이다.

| 정답 유형 | 관련 바코드 | 기대 결과 |
|---|---|---|
| RECOMMENDATION | 검수한 적합 대체 상품 1개 이상 | VERIFIED 또는 PASS/PASS인 RELAXED_SAFE |
| VERIFICATION_REQUIRED | 검수한 확인 필요 대안 1개 이상 | UNKNOWN 별도 채널 + 경고 + 다음 행동 |
| ABSTAIN | 빈 문자열 | 두 배열 비움 + ACTION_REQUIRED + 다음 행동 |

`forbidden_barcodes`에는 검수자가 확인한 위험/명시적 식단 위반 상품을 기록한다.
모델의 PASS 판정을 정답으로 복사하지 않는다. 관련/금지 바코드 중복은 평가 입력 오류이다.

- Hit@K/MRR/NDCG: RECOMMENDATION 사례만 분모. UNKNOWN fallback은 적중으로 계산하지 않는다.
- NDCG의 이상적 정답 수는 `min(K, 정답 수)`로 고정하여 적게 반환하거나 중복 반환해 점수가 부풀지 않게 한다.
- verificationFallbackHitRate: 확인 필요 사례에서 표시 규칙·금지 검사를 통과한 관련 fallback 적중률.
- correctAbstentionRate: ABSTAIN 사례의 올바른 보류율.
- outcomeMatchRate: 예상한 결과 유형과 채널/제약 검사를 모두 통과한 사례 비율.
- unexpectedEmptyResponseRate: 반환이 기대된 사례 중 실제 빈 응답 비율. 전체 emptyResponseRate는 관찰용으로 유지한다.
- presentationViolationCount: UNKNOWN을 검증 채널에 포함, 경고/다음 행동 없는 확인 필요 대안,
  두 채널 혼용, 중복 반환 등 계약 위반 수.
- 정답 유형별 사례 수와 K를 함께 저장한다. 해당 유형 사례가 없으면 보류율/확인 필요 적중률은 null이다.
  추천 사례가 없을 때 랭킹 수치는 0으로 기록하지만 미평가이며 랭킹 임계값은 적용하지 않는다.

기본 게이트: 위반 0, outcomeMatchRate=1, 예상 밖 빈 응답 0, 추천 사례 Hit@K>=0.30,
NDCG>=0.15, p95<=1000ms. 경고 대안 노출률 상한은 기존처럼 기본 1.0이다.
기존 `RECOMMENDATION_EVALUATION_MAXIMUM_EMPTY_RESPONSE_RATE` 대신
`RECOMMENDATION_EVALUATION_MAXIMUM_UNEXPECTED_EMPTY_RESPONSE_RATE`를 사용한다.

실행 전 스테이징 DB에 Flyway V13을 적용하고 `prepare_product_recommendation_evaluation.sql`을 참고하여
검수 정답을 준비한다. `recommendation-evaluation` 프로필은 평가 실행/결과 테이블에 기록한다.
코드 테스트는 합성 fixture와 격리 H2로 검증한다. 실제 상품 정답셋 구축, 운영 MySQL 성능 측정,
AWS 반영은 별도이며 자동 테스트 통과로 실제 추천 정확도를 주장하지 않는다.

## 4. v5 최초 코드 검증 결과

2026-10-23, Java 21에서 `gradlew.bat test bootJar --rerun-tasks --no-daemon --console=plain` 실행 성공.
총 116개 중 112개 통과, 실패/오류 0개, 대용량 CSV 전체 검증 4개는 기존 기본 설정으로 건너뛰었다.
두 추천 서비스의 공통 조건, 12개 식단 속성, UNKNOWN/불충족 혼재,
보정 영양값 제외, 올바른 빈 응답, 독립 금지 정답, 고정 K·중복 감점,
확인 필요 대안의 경고, 평가 결과 저장 경로를 포함한다.
평가 테이블 DDL 테스트는 H2용으로 MySQL의 다중 ADD/ALGORITHM 문법을 변환한 것이므로
운영 MySQL에서 Flyway V13을 실행·검증한 결과와는 구분한다. 운영 DB·CSV는 변경하지 않았다.

## 5. v5.1 수정 및 동일 평가셋 재검증

- SOY 근거 목록에 검정콩·검은콩·서리태·서목태·흑태·백태·메주콩을 추가했다.
  모든 `콩` 포함 문자열을 대두로 바꾸지는 않으며 땅콩·완두콩·병아리콩 등 오탐 방지 테스트를 추가했다.
- `8809546050393`의 검정콩분말이 대두 위험으로 검출되어 대두/복수 알레르기 사례의 확인용 후보에서도 제외된다.
- `8809579000297`의 젓갈이 비건과 충돌하여 저장값 true와 관계없이 NOT_MET이다.
  DB의 기존 원재료·분류값을 덮어쓰지 않고 요청 시 판정으로 차단한다. 비건 외 채식 유형 정의는 변경하지 않았다.
- 테스트 및 bootJar 빌드 성공: 총 125개 중 121개 통과, 실패/오류 0개, 선택적 CSV 테스트 4개 건너뜀.
- 로컬 MySQL V13에서 기존 20개 사례·10개 기준 상품·963개 고유 후보·사용자 조건·정답을 대조하고 재사용했다.
  정책 v5 → v5.1의 결과는 기대 동작 17/20 → 20/20, 금지 상품 반환 3/118 → 0/116,
  Hit@10 12/13 → 13/13, 올바른 보류 1/3 → 3/3, NDCG@10 0.8345 → 0.8706이다.
  품질 게이트는 실패에서 통과로 변경됐다. 빈 응답 1/20 → 3/20은 위험 후보를 차단한 올바른 보류이다.
- 이 실제 데이터 평가는 대체 추천 서비스 경로이며, 홈 추천은 통합 테스트로 동일한 제외 정책을 검증했다.
  HTTP/JWT 연동, 동시 부하, 개인 이력 순위는 이번 평가 범위가 아니다.
- 소규모 AI 보조 검수 파일럿이며 전문가 gold set이나 전체 상품의 안전성/정확도 100%를 뜻하지 않는다.
  기존 고정 정답과 기준 보고서를 보존했고 로컬 평가 실행 1개·결과 20개만 추가했다. 운영 DB는 접근·수정하지 않았다.
