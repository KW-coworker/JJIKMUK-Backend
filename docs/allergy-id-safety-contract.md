# 알레르기 ID 및 안전 판정 계약

## API와 저장 형식

- 알레르기는 표시 이름이 아니라 아래 소문자 ID로 주고받습니다. `users.allergies`는 기존 스키마를 유지하며 ID를 쉼표로 구분한 문자열로 저장합니다. 예: `milk,wheat`.
- 회원가입 `allergies`, 프로필 수정 `allergies`는 과거 한글 명칭도 입력받아 ID로 정규화합니다. 알 수 없는 항목은 `400`을 반환하며 삭제하거나 `PASS`로 취급하지 않습니다.
- 기존 DB의 한글 문자열은 읽을 때 해석합니다. `견과류`는 `walnut,pine_nut,almond`, `갑각류`는 `shrimp,crab`으로 보수적으로 펼칩니다. `글루텐`은 밀 알레르기 ID의 동의어가 아닙니다. 알 수 없는 과거 값이 남으면 판정은 `UNKNOWN`입니다.
- 현재 챗봇 AI 인터페이스는 한글 알레르기명을 사용하므로 백엔드가 ID를 표시명으로 변환해 전달합니다. AI 내부 판단 로직 자체는 이 공통 판정 서비스로 교체된 것이 아니며, 챗봇 팀과 별도 연동 검증이 필요합니다.
- ID 목록: `egg`, `milk`, `soy`, `wheat`, `pork`, `chicken`, `shrimp`, `crab`, `squid`, `mackerel`, `shellfish`, `oyster`, `mussel`, `abalone`, `peach`, `tomato`, `peanut`, `walnut`, `buckwheat`, `pine_nut`, `sulfites`, `sesame`, `almond`, `mustard`, `celery`, `beef`.
- `밀가루`는 `wheat`의 동의어이며 별도 ID가 아닙니다. `gluten_free`는 별도의 식단 조건입니다.

## 판정

상품 상세, 상품명 검색, 필터 검색, 추천이 모두 `AllergySafetyService`를 사용합니다.

| 상태 | 의미 | 추천 처리 |
| --- | --- | --- |
| `DANGER` | 원재료, 알레르기 경고 또는 알레르기 정규화값에서 사용자 항목과 충돌하는 표현 발견 | 추천에서 제외 |
| `PASS` | 필요한 근거가 있고 표기 자료상 충돌이 발견되지 않음. 섭취 안전 보증이 아님 | 다른 조건을 통과하면 추천 가능 |
| `UNKNOWN` | 원재료/출처 부족, 미지원 사용자 값, 세부 조개류 불명 등 | 일반 추천에서 제외하고 별도 확인 필요로 표시 |

`allergy_warning`만 존재할 때는 충돌을 찾을 수 있지만, 충돌이 없다는 사실만으로 `PASS`가 되지 않습니다. `PASS`에는 비어 있지 않은 `raw_materials`와 `DECLARED_LABEL` 또는 `VERIFIED_SOURCE` 수준이 필요합니다. `sesame`, `almond`, `mustard`, `celery`는 현재 데이터에서 누락 가능성을 더 보수적으로 취급해 `VERIFIED_SOURCE`만 `PASS` 근거로 인정합니다. `shellfish`는 굴·홍합·전복까지 포함합니다. 개별 항목 선택 시 `조개류`, `견과류`, `갑각류`, `어류`처럼 하위 성분을 특정할 수 없는 포괄 표기만 있으면 `UNKNOWN`입니다.

상품 응답의 기존 `analysis.isDangerous`, `dangerousIngredients`, `message`는 유지합니다. 새 필드는 `status`, `conflictingAllergenIds`, `evidenceSources`, `evidenceLevel`, `verificationRequired`입니다. `dangerousIngredients`는 표시용 한국어이고, 앱 로직은 `status`와 ID를 사용해야 합니다. 비로그인 조회의 개인 판정은 `UNKNOWN`입니다.

## 주의 및 후속 검증

현재 `DECLARED_LABEL`은 레거시 데이터의 경고 텍스트로 추정될 수 있습니다. 원재료의 완전성·라벨 최신성·교차오염 여부를 자동 검증한 값이 아닙니다. 따라서 `PASS`도 실제 포장 라벨 및 의료 지침을 대체할 수 없습니다. 데이터 출처 검증과 대표 상품 수작업 평가셋이 다음 단계입니다.
