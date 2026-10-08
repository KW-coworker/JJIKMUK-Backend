# 사용자 알레르기·식이조건 저장/API 계약

## 공통 형식

- 현재 DB 및 API 호환성을 유지하기 위해 배열이 아니라 **쉼표로 결합한 문자열**을 사용한다.
- 신규 요청의 표준값은 화면 표시 이름이 아니라 영문 ID다.
- 서버는 쉼표, 세미콜론, 슬래시, `|`, 줄바꿈을 입력 구분자로 허용하지만 저장·응답은 쉼표로 정규화한다.
- 항목 앞뒤 공백, 중복은 제거한다.
- 미선택과 전체 해제는 모두 JSON `null`을 사용한다. 빈 문자열도 서버에서 `null`로 정규화한다.
- 이모지와 `SignUpCondition.Allergy`, `SignUpCondition.Vegetarian` 같은 화면 이동용 상위 선택값은 전송하지 않는다.

## 필드별 계약

| 필드 | 형식 | 규칙 |
|---|---|---|
| `allergies` | 알레르기 ID 복수 문자열 | 26개 공통 ID, 알 수 없는 값은 `400` |
| `specialDiet` | 채식 ID 0~1개 + 영양 조건 ID 복수 문자열 | 채식 유형을 2개 이상 보내면 `400`, 알 수 없는 값은 `400` |
| `diseases` | 자유 입력 복수 문자열 또는 `null` | 식이 선호를 질환으로 변환하지 않음 |
| `dislikedIngredients` | 자유 입력 복수 문자열 또는 `null` | 최대 50개, 항목당 100자, 전체 1,000자 |

`specialDiet`의 채식 유형 ID:

```text
vegan
lactoVegetarian
ovoVegetarian
lactoOvoVegetarian
pescatarian
pollotarian
```

`specialDiet`의 식이·영양 조건 ID:

```text
lowSugar
lowSodium
glutenFree
lowCalorie
lowFat
highProtein
```

한글 표시 이름과 기존 별칭도 이전 데이터 호환을 위해 입력 시 인식하지만, 서버 저장 및 조회 응답은 위 ID로 반환한다.

## 1. 선택값이 있는 회원가입

선택:

- 알레르기: 계란 + 밀
- 식이조건: 저당 + 고단백
- 채식 유형: 락토오보
- 기저질환·기피 식재료: 미입력

```json
{
  "email": "user@example.com",
  "password": "password",
  "nickname": "사용자",
  "allergies": "egg,wheat",
  "specialDiet": "lactoOvoVegetarian,lowSugar,highProtein",
  "diseases": null,
  "dislikedIngredients": null,
  "verificationToken": "signup-verification-token"
}
```

회원 조회 응답에서도 네 선택 필드는 같은 표준 문자열 또는 `null`로 반환된다.

## 2. 아무 조건도 선택하지 않은 회원가입

```json
{
  "email": "user@example.com",
  "password": "password",
  "nickname": "사용자",
  "allergies": null,
  "specialDiet": null,
  "diseases": null,
  "dislikedIngredients": null,
  "verificationToken": "signup-verification-token"
}
```

선택 필드는 회원가입 요청에서 생략할 수도 있으며, 서버는 생략된 값을 `null`로 취급한다.

## 3. 기존 조건을 모두 해제하는 프로필 수정

`PUT /api/users/{id}`는 전체 교체 방식이므로 해제할 필드를 명시적으로 `null`로 보낸다.

```json
{
  "nickname": "사용자",
  "allergies": null,
  "specialDiet": null,
  "diseases": null,
  "dislikedIngredients": null
}
```

## 구형·알 수 없는 값 처리

- 지원하는 한글 표시 이름과 과거 별칭은 표준 ID로 변환한다.
- 신규 회원가입 및 프로필 수정에서 알 수 없는 알레르기·식이조건 값은 `400 Bad Request`로 거부한다.
- 기존 DB에 남아 있는 알 수 없는 `specialDiet` 값은 추천 조건으로 사용하지 않는다.
- 기저질환과 기피 식재료는 자유 입력이므로 형식·길이만 검증한다.
