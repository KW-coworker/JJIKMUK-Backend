# 4단계: 추천 개선

## 완료 범위

추천은 `ProductNeighbors.csv`의 상품별 Top 100을 후보로 사용하되, API 요청 시점에
사용자 안전 조건을 먼저 적용하고 통과한 상품만 개인화 점수와 MMR로 재정렬한다.
LLM은 이 결과와 근거를 설명하는 역할만 맡으며 안전 판정이나 바코드 선택을 하지 않는다.

```text
기준 상품 + 사용자 프로필
→ 사전 계산 후보 Top 100 조회
→ 알레르기 hard constraint
→ 식단·영양 hard constraint
→ 비선호 원재료 제외
→ 시간 감쇠 행동 이력으로 취향 점수 계산
→ 유사도 0.70 + 취향 0.25 + 데이터 품질 0.05
→ MMR(관련성 0.85, 중복 억제 0.15)
→ 엄격 후보가 0개면 안전한 저유사도 후보 또는 확인 필요 후보 1개 선택
→ 근거·점수·추적 ID와 함께 반환
```

취향 이력이 없으면 취향을 0점으로 간주하지 않고 남아 있는 유사도와 품질 가중치를
다시 정규화한다. 가중치는 환경변수로 바꿀 수 있으며, 이후 오프라인 평가와 사용자
피드백을 기준으로 버전을 올려 조정한다.

## 안전성 hard constraint

알레르기 판정은 다음 세 상태를 사용한다.

- `DANGER`: 사용자 알레르기와 원재료·알레르기 경고의 충돌이 확인됨. 즉시 제외한다.
- `PASS`: 공식/표기 근거(`VERIFIED_SOURCE`, `DECLARED_LABEL`)에서 충돌이 확인되지 않음.
- `UNKNOWN`: 정보가 없거나 추론·원재료 파생 정보만 있어 부재를 확정할 수 없음. 검증된 안전 추천에서는 제외한다. 엄격 후보가 하나도 없을 때에만 `fallbackItems`의 `VERIFICATION_REQUIRED` 후보가 될 수 있으며, 안전 상품으로 표현하지 않는다.

국내 표시 대상에 맞춰 난류, 우유, 메밀, 땅콩, 대두, 밀, 고등어, 게, 새우,
돼지고기, 복숭아, 토마토, 아황산류, 호두·잣, 닭고기, 쇠고기, 오징어, 조개류와
주요 동의어를 판정한다. `밀`이 `밀크`나 `메밀`에 잘못 걸리지 않도록 단일 글자
경계를 별도로 처리했다.

식단 판정은 `PASS`, `MISMATCH`, `UNKNOWN`을 사용한다. 플래그가 거짓이면
`MISMATCH`, 플래그가 참이어도 판정 원본·신뢰도·필요 원재료/영양값이 부족하면
`UNKNOWN`이다. `MISMATCH`는 항상 제외하고, `UNKNOWN`은 엄격 추천에서 제외하되 명시적
불일치가 없는 경우에만 확인 필요 대안 후보가 될 수 있다. 예를 들어 저당은
`is_low_sugar=true`뿐 아니라 실제 `sugar_g` 값도 있어야 통과한다.

빈 화면 방지를 위한 반환 우선순위는 다음과 같다.

1. `VERIFIED`: 안전성과 식단 조건을 모두 통과하고 최소 유사도 이상인 일반 추천
2. `RELAXED_SAFE`: 안전성과 식단 조건을 통과했지만 최소 유사도만 미달한 대안 1개
3. `VERIFICATION_REQUIRED`: `DANGER`와 식단 `MISMATCH`, 비선호 원재료를 제외한 뒤 남은 `UNKNOWN` 중 최상위 1개
4. `ACTION_REQUIRED`: 반환 가능한 상품이 전혀 없을 때 라벨 촬영·다른 상품 선택 안내

`DANGER`와 식단 `MISMATCH`는 결과 수를 채우기 위해 완화하지 않는다. 확인 필요 후보는
안전 추천과 섞지 않고 별도 필드로 내려 보내며, 실제 포장 라벨 확인 전에는 섭취 판단에
사용하지 않도록 경고한다. 후보의 위험 단계가 같으면 기존 `ProductNeighbors.csv` 순위가
높은 상품, 최종 동률이면 바코드 오름차순으로 선택한다.

`Product.csv` 재적재 시 다음 메타데이터를 생성한다.

- `food_type`: 제품 유형 → 소분류 → 중분류 → 대표식품 → 대분류 순으로 첫 유효값
- 알레르기 근거 수준과 신뢰도
- 영양값 원본/정규화 여부와 매칭 점수 기반 신뢰도
- 식단 분류의 추론 출처와 입력 정보량 기반 신뢰도

## 사용자 행동과 개인화

`POST /api/histories/events`에서 다음 행동을 기록한다.

| 행동 | 가중치 | 의미 |
|---|---:|---|
| `SCAN` | 0.25 | 약한 관심 신호 |
| `DETAIL_VIEW` | 0.50 | 상세 확인 |
| `SEARCH_CLICK` | 1.00 | 검색 결과 선택 |
| `FAVORITE` | 3.00 | 강한 선호 |
| `EAT` | 2.50 | 실제 섭취 |
| `DISLIKE` | -3.00 | 명시적 비선호 |

각 이벤트는 `weight × exp(-경과일/30)`으로 감쇠한다. 같은 상품을 반복 조회해
점수를 과도하게 지배하지 않도록 상품별 누적 절댓값을 6으로 제한하고, 스캔·상세조회·
검색 클릭 같은 수동적 신호의 상품별 합은 1로 더 엄격하게 제한한다. 현재 사용자에게
위험하거나 필수 식단 조건을 통과하지 못한 과거 상품은 취향 벡터에서 제외한다.

요청 예시는 다음과 같다.

```http
POST /api/histories/events
Authorization: Bearer <token>
Content-Type: application/json

{"barcode":"8800000000000","actionType":"FAVORITE"}
```

## 추천 API와 근거

기존 API는 유지한다.

```http
GET /api/recommendations/products/{barcode}?limit=10&minScore=0.2
```

응답에 다음이 추가된다.

- `requestId`, `policyVersion`: 결과 재현과 사용자 피드백 연결용
- `referenceSafety`: 기준 상품 자체의 `PASS/DANGER/UNKNOWN`
- 각 상품의 `safety`, `dietConstraints`
- `dataEvidence`: 알레르기·영양·식단 데이터의 원본/추론 여부와 신뢰도
- `scoreBreakdown`: 활성 가중치와 각 점수 기여분
- `reasons`: 같은 식품 유형, 안전 근거, 식단 충족, 취향·품질 근거
- `excluded`: 엄격 추천 풀에서 위험, 안전성 미상, 식단 불일치, 식단 근거 부족 등으로 제외된 개수. 일부 UNKNOWN은 이후 별도 fallback으로 선택될 수 있음
- `timing`: 후보/상품/이력 조회와 랭킹 소요 시간
- `resultMode`: `VERIFIED`, `RELAXED_SAFE`, `VERIFICATION_REQUIRED`, `ACTION_REQUIRED`
- `items`: 기존과 동일하게 검증된 엄격 추천만 포함
- `fallbackItems`: 엄격 추천이 없을 때만 최대 1개의 대안을 포함
- `fallbackReason`, `fallbackCandidateCount`: fallback이 발생한 이유와 선택 가능 후보 수
- 각 fallback 상품의 `verificationRequired`, `warnings`, `requiredActions`: 화면 경고와 다음 행동

프런트엔드는 `items`가 비었을 때 곧바로 "추천 없음"을 표시하지 않고 `resultMode`를 먼저
확인해야 한다. `VERIFICATION_REQUIRED`이면 `fallbackItems`를 일반 추천 카드와 구분해
노란색 경고, "안전성 확인 필요" 배지, 제품 뒷면 확인·촬영 행동과 함께 표시한다.

```json
{
  "message": "안전성을 확정할 수 없어 제품 라벨 확인이 필요한 대안을 표시합니다.",
  "data": {
    "resultMode": "VERIFICATION_REQUIRED",
    "items": [],
    "fallbackItems": [
      {
        "recommendationTier": "VERIFICATION_REQUIRED",
        "verificationRequired": true,
        "warnings": ["공식 알레르기 표기 근거가 충분하지 않습니다."],
        "requiredActions": ["제품 뒷면의 원재료와 알레르기 표시를 확인해 주세요."]
      }
    ]
  }
}
```

사용자 테스트에서는 아래 API로 노출·클릭·수락·거절을 기록한다.

```http
POST /api/recommendations/feedback
Authorization: Bearer <token>
Content-Type: application/json

{
  "requestId":"<추천 응답 requestId>",
  "productBarcode":"8800000000001",
  "feedbackType":"CLICK",
  "rankPosition":2
}
```

지원 피드백은 `IMPRESSION`, `CLICK`, `ACCEPT`, `DISMISS`다. 한 요청·사용자·상품에서
같은 피드백의 중복 저장은 거부한다.

## 성능 로그와 오프라인 평가

V5 마이그레이션은 추천 실행 로그, 피드백, 평가셋, 평가 결과 테이블과 이력 조회
인덱스를 추가한다. V6는 결과 모드, fallback 후보·반환 수, 검증 필요 반환 수와 fallback
바코드를 추가한다. 실행 로그에는 후보 조회, 상품 100건 일괄 조회, 최근 이력 조회,
랭킹과 전체 지연 시간을 분리해 저장한다. 로깅 실패가 추천 API를 실패시키지 않도록
별도 제한 큐에서 비동기 저장한다.

운영 통계는 `db/operations/analyze_product_recommendations.sql`로 확인한다. 특히
`product_fetch_micros`와 `history_fetch_micros`를 분리했으므로 후보 저장 구조와 개인화
조회 중 실제 병목을 구분할 수 있다.

오프라인 평가셋은 사람이 검토한 `(사용자, 기준 상품, 관련 대체 상품 바코드)`로 만든다.
`prepare_product_recommendation_evaluation.sql`의 템플릿으로 활성 케이스를 등록한 뒤
다음과 같이 별도 프로세스로 실행한다.

```powershell
.\gradlew.bat bootRun --args='--spring.profiles.active=recommendation-evaluation'
```

측정 지표는 Hit@K, MRR, NDCG@K, hard-constraint 위반률, UNKNOWN 노출률,
검증 필요 노출률, fallback 사용 케이스 비율, 화면상 빈 응답률, catalog coverage,
평균/p95 지연 시간이다. `DANGER`와 식단 `MISMATCH`만 hard-constraint 위반으로 집계하고,
명시적으로 경고한 UNKNOWN은 검증 필요 노출률로 따로 측정한다. 화면상 빈 응답률 기본
상한은 0이며 검증 필요 노출률 상한은 환경변수로 조정한다. 평가셋이 없으면 실행을
중단해 의미 없는 성공값을 남기지 않는다.

## 적용 순서

1. 백업과 스테이징 검증 후 Flyway V5와 V6를 적용한다.
2. `histories` 인덱스 생성은 쓰기 부하가 적은 시간에 수행한다.
3. 제품 적재 버전 `V4.0-PRODUCTCSV-RECOMMENDATION-METADATA`로 Product.csv를
   스테이징 재적재해 `food_type`과 출처/신뢰도를 채운다.
4. ProductNeighbors 버전과 원본 Product 버전이 맞는지 확인한다.
5. 추천 로그를 먼저 관찰한 뒤 평가셋을 구축하고 LOCATE 검색과 무관한 별도 프로필로
   추천 평가를 실행한다.
6. 사용자 테스트 피드백을 모아 가중치를 조정할 때 `policyVersion`도 함께 올린다.

V5·V6 적용, 134만 행 제품 재적재, 운영 성능 평가는 실제 MySQL과 유지보수 시간대가
필요하므로 코드 테스트와 별개로 실행해야 한다.

## 안전 기준 참고

- 식품의약품안전처 「식품등의 표시기준」 고시 제2026-37호:
  https://www.mfds.go.kr/brd/m_205/view.do?seq=14968
- 식품의약품안전처 식품 알레르기 유발 식품 확인 안내:
  https://dietary4u.mfds.go.kr/upload/editor/20220531102508677.pdf
