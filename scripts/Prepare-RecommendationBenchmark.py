"""Freeze a small, real-catalog pilot BEFORE running recommendations.

Reads a Local-RecommendationEvaluation.py collect snapshot only. Never connects to DB.
These are AI-assisted, evidence-reviewed regression judgments, NOT clinical gold labels.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys


# Functionally similar products, not lexical matches to English fragments or '손맛'.
# Labels are independent of recommendation scores and evaluated response ordering.
RELEVANCE = {
    "0000088001494": (r"두부", r""),
    "2000000021345": (r"SHIN RAMYUN|AnSungTangMyun|컵라면|왕뚜껑", r""),
    "3150012065201": (r"누룽지", r"차"),
    "4580372910412": (r"두유|베지밀|삼육검은콩|빈&트로피칼|The 건강한 약콩", r""),
    "8800251190022": (r"김치|깍두기", r"덮밥|만두|지짐이"),
    "8801019309830": (r"포키|빼빼로|칸쵸|초코송이|웨하스|롤리폴리|빈츠|랑드샤|다이제초코|사브레|브루느와", r""),
    "8801043004107": (r"새우깡|자갈치|왕새우|감자깡|포스틱|인디안밥|오잉|맛새우|꽃게랑|스모키베이컨칩|도리토스|콘칲|예감|고래밥", r""),
    "8801056001261": (r"사이다|스프라이트|토닉워터|토닉 워터|진저에일|데미소다|프리미엄.?소다|트레비", r""),
    "8801062007394": (r"초코파이|쵸코파이|초코크림파이|크림파이|초코케익|초코 쌀케익|치즈케익|치즈크림케익", r"믹스|파우더"),
    "8801117678302": (r"포카칩|감자칩|나쵸|보더칩|99칼로리칩|오!감자|예감|도리토스", r""),
}

PROFILES = {
    "general": {"allergies": "", "specialDiet": ""},
    "milk": {"allergies": "milk", "specialDiet": ""},
    "soy": {"allergies": "soy", "specialDiet": ""},
    "multi": {"allergies": "soy,milk,wheat,peanut", "specialDiet": ""},
    "vegan": {"allergies": "", "specialDiet": "vegan"},
    "milk_vegan": {"allergies": "milk", "specialDiet": "vegan"},
    "low_sugar": {"allergies": "", "specialDiet": "lowSugar"},
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Frozen labels already exist: do not overwrite after observing results")
    evidence = json.loads(args.snapshot.read_text(encoding="utf-8"))
    products = {p["barcode"]: p for p in evidence["candidates"]}
    refs = {r["product"]["barcode"]: r for r in evidence["references"]}
    pools = {b: [products[n.split('|')[0]] for n in r["neighbors"].split(',')] for b, r in refs.items()}
    relevant = {}
    for barcode, pool in pools.items():
        include, exclude = RELEVANCE[barcode]
        relevant[barcode] = sorted(p["barcode"] for p in pool
            if re.search(include, p["product_name"] or "", re.I)
            and not (exclude and re.search(exclude, p["product_name"] or "", re.I)))

    cases = []

    def add(slug, barcode, profile, outcome, expected=None, forbidden=None, reason=""):
        expected = relevant[barcode] if expected is None else sorted(expected)
        forbidden = sorted(forbidden or [])
        assert not (set(expected) & set(forbidden)), slug
        assert bool(expected) == (outcome != "ABSTAIN"), slug
        assert set(expected + forbidden) <= {p["barcode"] for p in pools[barcode]}, slug
        cases.append({"case_id": "local-pilot-20261023-" + slug, "reference_barcode": barcode,
            "reference_name": refs[barcode]["product"]["product_name"], "profile": profile,
            "expected_outcome": outcome, "expected_relevant_barcodes": expected,
            "forbidden_barcodes": forbidden, "judgment_reason": reason})

    for index, barcode in enumerate(RELEVANCE, 1):
        add(f"{index:02d}-general", barcode, "general", "RECOMMENDATION",
            reason="제한 조건 없는 대체 상품 탐색. 용량·브랜드 차이는 허용하고 사용 용도가 다른 상품은 관련 정답에서 제외.")

    for index, barcode in enumerate(["0000088001494", "3150012065201", "8801056001261"], 11):
        pool = pools[barcode]
        assert all(p["allergy_evidence_level"] not in ("DECLARED_LABEL", "VERIFIED_SOURCE") for p in pool)
        bad = {p["barcode"] for p in pool if re.search(r"우유|분유|유당|버터|유크림|치즈", " ".join(
            p[k] or "" for k in ["raw_materials", "allergy", "allergy_warning"]))}
        add(f"{index:02d}-milk-evidence", barcode, "milk", "VERIFICATION_REQUIRED",
            expected=set(relevant[barcode])-bad, forbidden=bad,
            reason="후보 100건 모두 공식 표시 근거 수준 미충족. 우유 유래 성분 명시 상품은 제외하고 나머지도 안심 추천이 아닌 추가 확인으로만 제공.")

    soy_reference = "4580372910412"
    soy_pool = pools[soy_reference]
    assert all(re.search(r"대두|두유|검정콩|검은콩", p["raw_materials"] or "") for p in soy_pool)
    for index, profile in [(14, "soy"), (15, "multi")]:
        add(f"{index:02d}-soy-conflict", soy_reference, profile, "ABSTAIN", expected=[],
            forbidden=[p["barcode"] for p in soy_pool],
            reason="100개 후보 원재료에 두유·대두·검정콩·검은콩을 명시. 분류 열의 미검출과 관계없이 대두 제한 대상. 가족 합집합 API 자체가 아닌 복수 알레르기 프로필 평가.")

    pocky_pool = pools["8801019309830"]
    assert all(p["is_low_sugar"] == 0 and p["sugar_g"] is not None and p["sugar_g"] > 5
        and p["nutrition_data_origin"] in ("SOURCE", "NORMALIZED", "CALCULATED") for p in pocky_pool)
    add("16-low-sugar-negative", "8801019309830", "low_sugar", "ABSTAIN", expected=[],
        forbidden=[p["barcode"] for p in pocky_pool],
        reason="영양 수치 존재, 저장된 저당 분류가 전 후보 false. 이 검사는 기존 저당 분류 계약의 유지 여부이며 영양 표시 기준·단위의 임상/법적 타당성 검증이 아님.")

    grain = "3150012065201"
    animal = {p["barcode"] for p in pools[grain] if "멸치" in (p["raw_materials"] or "")}
    plant_grains = {p["barcode"] for p in pools[grain] if p["barcode"] in relevant[grain]
        and p["is_vegan"] == 1 and p["raw_materials"] and p["barcode"] not in animal}
    add("17-vegan-grain", grain, "vegan", "RECOMMENDATION", expected=plant_grains, forbidden=animal,
        reason="곡류 중심 누룽지의 기존 비건 분류 유지, 멸치 제품 제외. 추론 속성의 분류 계약 평가이며 비건 인증 확인이 아님.")
    add("18-milk-vegan-grain", grain, "milk_vegan", "VERIFICATION_REQUIRED", expected=plant_grains,
        forbidden=animal, reason="비건 조건을 만족하더라도 우유 알레르기 근거 부족을 PASS로 바꾸면 안 됨.")
    low_sugar_grains = {p["barcode"] for p in pools[grain] if p["barcode"] in relevant[grain]
        and p["is_low_sugar"] == 1 and p["sugar_g"] is not None
        and p["nutrition_data_origin"] in ("SOURCE", "NORMALIZED", "CALCULATED")}
    add("19-low-sugar-grain", grain, "low_sugar", "RECOMMENDATION", expected=low_sugar_grains,
        reason="수치/출처가 존재하는 저당 분류 상품을 정답으로 고정. 영양 수치 결측인 false 상품은 NOT_MET 정답으로 만들지 않음.")
    kimchi = "8800251190022"
    fish = {p["barcode"] for p in pools[kimchi] if re.search(r"새우|멸치|액젓|젓갈|돼지고기|닭고기|소고기|유크림|분유|난황|계란",
        p["raw_materials"] or "")}
    plant_kimchi = {"8809225710501", "8809650020152", "8809650020404"}
    assert all(products[b]["is_vegan"] == 1 for b in plant_kimchi)
    add("20-vegan-kimchi", kimchi, "vegan", "RECOMMENDATION", expected=plant_kimchi, forbidden=fish,
        reason="원재료에 채소·물·소금·조미료가 기록된 백김치/물김치 3종을 검토 정답으로 지정. 생선젓·육류 등의 명시 상품 제외. 다른 식물성 상품을 김치 대체 정답으로 간주하지 않음.")

    manifest = {"dataset_version": "local-real-products-pilot-20261023-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evidence_sha256": hashlib.sha256(args.snapshot.read_bytes()).hexdigest(),
        "label_status": "AI-assisted evidence-reviewed pilot; not expert gold",
        "scope": "Alternative RecommendationService, Top100 frozen pool, K=10, synthetic profiles without history",
        "limitations": ["10개 의도 표집 상품: 전체 상품/사용자 대표성 없음", "관련성 정답은 부분 판정이며 비관련/미판정이 혼재",
            "의료적 안전성·실물 라벨·비건 인증 검증 아님", "선호 이력·홈 추천 API·HTTP 인증·부하/동시접속은 별도 평가",
            "기존 식단/영양 분류 계약 검사는 해당 분류의 사실 정확도를 입증하지 않음",
            "후보 100개 밖의 좋은 상품은 평가 범위 밖"],
        "profiles": PROFILES, "cases": cases}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"file": str(args.output), "cases": len(cases),
        "outcomes": dict(Counter(c["expected_outcome"] for c in cases)),
        "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
