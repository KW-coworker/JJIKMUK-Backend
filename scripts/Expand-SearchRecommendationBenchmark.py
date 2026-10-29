"""Local SELECT-only collection and pre-registered silver/regression benchmark expansion."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_eval", ROOT / "scripts/Local-RecommendationEvaluation.py")
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)

EXTRA_COLUMNS = ["clean_product_name", "product_group_key", "image_url", "carbs_g", "cholesterol_mg",
    "is_lacto_vegetarian", "is_ovo_vegetarian", "is_lacto_ovo_vegetarian", "is_pescatarian", "is_pollotarian",
    "is_low_sodium", "is_low_calorie", "is_low_fat", "is_high_protein"]

# Curated product-function families, fixed before reading recommendation outputs.
FAMILIES = [
    ("snack", "새우깡", "새우깡|자갈치|왕새우|감자깡|포스틱|오잉|꽃게랑|콘칲|고래밥", ""),
    ("snack", "포카칩", "감자칩|포카칩|오!감자|예감|나쵸|도리토스", ""),
    ("snack", "포키", "포키|빼빼로|웨하스|초코송이|빈츠|사브레|칸쵸", ""),
    ("dessert", "아이스크림", "아이스크림|빙과|소프트콘|바닐라콘", "믹스|파우더"),
    ("dessert", "초코파이", "초코파이|쵸코파이|크림파이|초코케익", "믹스"),
    ("convenience", "만두", "만두", "소스|전골|국"),
    ("convenience", "볶음밥", "볶음밥", "소스"),
    ("beverage", "두유", "두유|베지밀|삼육검은콩|약콩", "바|분말"),
    ("beverage", "사이다", "사이다|스프라이트|탄산수|토닉|소다|트레비", ""),
    ("beverage", "커피", "커피|라떼|에스프레소|아메리카노", "쿠키|과자|케이크"),
    ("dairy", "요거트", "요거트|요구르트|요플레", "아이스|분말|파우더|과자"),
    ("dairy", "우유", "우유|밀크", "과자|빵|초콜릿|사탕|비스킷|비누"),
    ("bakery", "식빵", "식빵|토스트", "소스"),
    ("bakery", "떡", "떡|절편|인절미|송편", "떡볶이|소스|국|과자"),
    ("noodles", "라면", "라면|라멘|RAMYUN|왕뚜껑|짜파게티|너구리|신라면", "스프|소스"),
    ("noodles", "국수", "국수|소면|중면|칼국수", "소스|육수|장국"),
    ("meat", "닭가슴살", "닭가슴살", "소시지|볶음밥"),
    ("meat", "소시지", "소시지|소세지|프랑크|비엔나", "빵|핫도그|볶음밥"),
    ("seafood", "김", "도시락김|조미김|구운김|재래김|돌김|김밥김|맛김", "김치|김밥|소스"),
    ("seafood", "참치", "참치", "김밥|소스|볶음밥|주먹밥"),
    ("plant", "두부", "두부", "과자|김치|찌개|양념"),
    ("plant", "누룽지", "누룽지", "차|삼계탕|과자"),
    ("sides", "김치", "김치|깍두기", "만두|볶음밥|덮밥|지짐이|전골"),
    ("sides", "단무지", "단무지|오이지|피클", "소스"),
    ("condiments", "간장", "간장", "양념|소스|치킨|게장|장아찌"),
    ("condiments", "고추장", "고추장", "볶음|삼겹|소스|양념"),
    ("special", "단백질", "프로틴|단백질", "칩|바|과자"),
    ("special", "홍삼", "홍삼", "사탕|캔디|젤리"),
]

# Deliberately narrow independent positive evidence, not the production allergy dictionary.
# Never use absence of these terms to label a product allergy-safe.
ALLERGENS = {
    "egg": "계란|달걀|난황|난백", "milk": "우유|탈지분유|전지분유|유청|유크림", "soy": "대두|검정콩|검은콩|두유|서리태",
    "wheat": "밀가루|소맥분|밀단백", "pork": "돼지고기|돈육", "chicken": "닭고기|계육|닭가슴살", "shrimp": "새우",
    "crab": "꽃게|게살|게엑기스", "squid": "오징어", "mackerel": "고등어", "shellfish": "바지락|조개|홍합|전복|굴추출",
    "oyster": "굴추출|굴농축|굴엑기스", "mussel": "홍합", "abalone": "전복", "peach": "복숭아", "tomato": "토마토",
    "peanut": "땅콩", "walnut": "호두", "buckwheat": "메밀", "pine_nut": "잣", "sulfites": "아황산나트륨|메타중아황산",
    "sesame": "참깨|참기름", "almond": "아몬드", "mustard": "겨자|머스타드", "celery": "셀러리|샐러리", "beef": "소고기|쇠고기|우육",
}
ANIMAL = "돼지고기|돈육|닭고기|계육|소고기|쇠고기|우육|멸치|새우|오징어|젓갈|액젓|우유|탈지분유|전지분유|유청|유크림|난황|난백|계란|달걀"

# Pre-run review of the collected names/types: not interchangeable with the sampled family.
REFERENCE_REVIEW = {
    "8801056001261": "사이다+주스 묶음 표기와 탄산음료 원재료만 있는 데이터: 단일 대체 용도 불명확",
    "2000000862729": "요거트맛 쉐이크는 일반 요거트와 용도가 다를 수 있으며 원재료/식품유형 누락",
    "8801007124247": "닭가슴살물만두는 닭가슴살 단품이 아닌 만두",
    "648436122417": "King Bowl(김치)는 김치 맛 제품 가능성, 식품유형/원재료 없어 확정 불가",
    "2500000120114": "간장 새우장은 간장 단품이 아닌 반찬",
}


def save(path, value):
    if path.exists():
        raise ValueError(f"Refusing to overwrite frozen evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def product_json(alias="p"):
    columns = list(dict.fromkeys(local.PRODUCT_COLUMNS + EXTRA_COLUMNS))
    return "JSON_OBJECT(" + ",".join(f"'{c}'," + (f"CAST({alias}.{c} AS UNSIGNED)" if c.startswith("is_") else f"{alias}.{c}") for c in columns) + ")"


def matches(text, include, exclude=""):
    return bool(re.search(include, text or "", re.I)) and not (exclude and re.search(exclude, text or "", re.I))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inspect", "collect", "enrich-original", "freeze", "diagnose-search"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--original", type=Path)
    args = parser.parse_args()
    out = args.output
    if args.action == "diagnose-search":
        db = local.LocalDatabase()
        # Data availability check only: English spelling versus Korean spelling.
        # Full-width/spaced aliases are not inferred as equivalent by this check.
        diagnostics = db.select("SELECT JSON_OBJECT('pocky_name_rows',SUM(LOCATE('pocky',LOWER(COALESCE(product_name,'')))>0),"
            "'pocky_clean_rows',SUM(LOCATE('pocky',LOWER(COALESCE(clean_product_name,'')))>0),"
            "'korean_pocky_rows',SUM(LOCATE(" + local.quote("포키") + ",COALESCE(product_name,''))>0),"
            "'products',COUNT(*)) FROM products")
        save(out / "search-catalog-diagnostics.json", {"server": db.identity, "counts": diagnostics,
            "note": "SELECT-only literal spelling counts; no transliteration or fuzzy matching"})
        print(json.dumps(diagnostics, ensure_ascii=False)); return
    if args.action == "enrich-original":
        old = json.loads(args.original.read_text(encoding="utf-8"))
        db = local.LocalDatabase()
        wanted = sorted({p["barcode"] for p in old["candidates"]} | {r["product"]["barcode"] for r in old["references"]})
        rows = []
        for start in range(0, len(wanted), 200):
            rows.extend(db.select("SELECT " + product_json() + " FROM products p WHERE p.barcode IN (" + ",".join(local.quote(b) for b in wanted[start:start+200]) + ")"))
        current = {p["barcode"]: p for p in rows}
        for product in old["candidates"] + [r["product"] for r in old["references"]]:
            if any(current[product["barcode"]].get(key) != value for key, value in product.items()):
                raise ValueError("Original evidence changed: " + product["barcode"])
        for ref in old["references"]:
            stored = db.select("SELECT JSON_OBJECT('neighbors',recommendations) FROM product_neighbor_sets WHERE source_barcode=" + local.quote(ref["product"]["barcode"]))[0]
            if stored["neighbors"] != ref["neighbors"]: raise ValueError("Original neighbors changed")
            ref["product"] = current[ref["product"]["barcode"]]
        old["candidates"] = [current[p["barcode"]] for p in old["candidates"]]
        old["original_sha256"] = hashlib.sha256(args.original.read_bytes()).hexdigest()
        old["enrichment_note"] = "All original product fields and neighbor lists compared equal; extra score fields collected SELECT-only before replay"
        save(out / "original-enriched-evidence.json", old)
        print("Original evidence verified and enriched:",len(rows)); return
    if args.action == "inspect":
        db = local.LocalDatabase()
        result = {"server": db.identity, "counts": db.select("SELECT JSON_OBJECT('products',(SELECT COUNT(*) FROM products),'neighbors',(SELECT COUNT(*) FROM product_neighbor_sets))"),
            "indexes": db.select("SELECT JSON_OBJECT('name',INDEX_NAME,'type',INDEX_TYPE) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='products' AND INDEX_TYPE='FULLTEXT'"),
            "search_mode": local.resolve(db.config.get("product.search.mode", "locate")),
            "grouping_mode": local.resolve(db.config.get("product.grouping.mode", "legacy"))}
        save(out / "inspection.json", result)
        print(json.dumps(result, ensure_ascii=False)); return
    if args.action == "collect":
        db = local.LocalDatabase()
        refs = []; missing = []
        for category, term, include, exclude in FAMILIES:
            # Use membership index first; LIMIT bounds the intentional per-family sample.
            rows = db.select("SELECT JSON_OBJECT('product'," + product_json() + ",'neighbors',n.recommendations,'model',n.model_version) "
                "FROM product_food_category_memberships c JOIN products p ON p.barcode=c.barcode "
                "JOIN product_neighbor_sets n ON n.source_barcode=p.barcode WHERE c.category_id=" + local.quote(category) +
                " AND LOCATE(" + local.quote(term) + ",p.product_name)>0 ORDER BY p.barcode LIMIT 5")
            rows = [r for r in rows if matches(r["product"]["product_name"], include, exclude)]
            if not rows:
                missing.append({"category": category, "term": term}); continue
            ref = rows[0]
            ref.update(category=category, term=term, relevance_include=include, relevance_exclude=exclude)
            refs.append(ref)
            print("Collected", category, term, ref["product"]["barcode"], flush=True)
        wanted = sorted({p.split("|")[0] for r in refs for p in r["neighbors"].split(",") if "|" in p})
        candidates = []
        for start in range(0, len(wanted), 200):
            candidates.extend(db.select("SELECT " + product_json() + " FROM products p WHERE p.barcode IN (" + ",".join(local.quote(b) for b in wanted[start:start+200]) + ")"))
        save(out / "expanded-evidence.json", {"server": db.identity, "references": refs, "candidates": candidates, "missing_families": missing})
        print(json.dumps({"references": len(refs), "candidates": len(candidates), "missing": missing}, ensure_ascii=False)); return
    evidence_path = out / "expanded-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    products = {p["barcode"]: p for p in evidence["candidates"]}
    profiles = {"general": {"allergies": "", "specialDiet": ""}}
    profiles.update({a: {"allergies": a, "specialDiet": ""} for a in ALLERGENS})
    profiles.update({d: {"allergies": "", "specialDiet": d} for d in ["vegan", "lactoVegetarian", "ovoVegetarian", "lactoOvoVegetarian", "pescatarian", "pollotarian", "lowSugar", "lowSodium", "glutenFree", "lowCalorie", "lowFat", "highProtein"]})
    profiles["multi"] = {"allergies": "milk,soy,wheat,peanut", "specialDiet": ""}
    profiles["milk_vegan"] = {"allergies": "milk", "specialDiet": "vegan"}
    profiles["dislike"] = {"allergies": "", "specialDiet": "", "dislikedIngredients": "고수"}
    cases = []; evidence_review = []
    for ref in evidence["references"]:
        pool = [products[v.split("|")[0]] for v in ref["neighbors"].split(",") if v.split("|")[0] in products]
        relevant = sorted(p["barcode"] for p in pool if matches(p["product_name"], ref["relevance_include"], ref["relevance_exclude"]))
        for profile_id, profile in profiles.items():
            positive_terms = [ALLERGENS[a] for a in profile["allergies"].split(",") if a]
            if profile["specialDiet"] == "vegan": positive_terms.append(ANIMAL)
            if profile.get("dislikedIngredients"): positive_terms.append("고수")
            pattern = "|".join(positive_terms)
            forbidden = []
            if pattern:
                for p in pool:
                    # Raw-ingredient-only positives. Ambiguous absence/flavour/substitute statements are withheld.
                    raw = p["raw_materials"] or ""
                    hits = sorted(set(re.findall(pattern, raw, re.I)))
                    if hits and not re.search("무첨가|미함유|불포함|대체|비건|향료|합성향", raw):
                        forbidden.append(p["barcode"])
                        evidence_review.append({"reference": ref["product"]["barcode"], "profile": profile_id,
                            "barcode": p["barcode"], "name": p["product_name"], "matched_terms": hits, "raw_materials": raw})
            cases.append({"case_id": f"expanded-{ref['product']['barcode']}-{profile_id}", "reference_barcode": ref["product"]["barcode"],
                "category": ref["category"], "profile": profile_id, "relevant_barcodes": relevant,
                "forbidden_barcodes": sorted(forbidden), "label_kind": "silver_product_function" if profile_id == "general" else "constraint_probe",
                "ranking_judged": profile_id == "general" and bool(relevant) and ref['product']['barcode'] not in REFERENCE_REVIEW,
                "reference_review": REFERENCE_REVIEW.get(ref['product']['barcode'])})
    search = []
    def add(case_id, query, fragment, kind, outcome="MATCH", pair=None):
        search.append({"case_id": case_id, "query": query, "fragments": [fragment] if fragment else [], "kind": kind,
            "expected_outcome": outcome, "pair_group": pair, "top_k": 10})
    for slug, term in [("protein-chip", "단백질칩"), ("soy-bar", "두유바"), ("spicy-shrimp", "매운새우깡")]:
        add(slug+"-compact", term, term, "original", pair=slug)
        add(slug+"-spaced", term[:-1]+" "+term[-1], term, "spaces", pair=slug)
    for term in ["포키", "초코파이", "신라면", "꼬깔콘"]:
        add("original-"+term, term, term, "original")
    for i, ref in enumerate(evidence["references"]):
        term = ref["term"]
        # Term expectations only: brand/capacity variants still must identify this product family.
        for suffix, query, kind in [("term",term,"family"), ("spaces"," ".join(term),"spaces"),
            ("brand",(ref["product"]["manufacturer"] or "").strip()+" "+term,"brand_plus_name"),
            ("typo",term[:-1]+"욤","single_character_typo"), ("punct", "-".join(term),"punctuation")]:
            add(f"family-{i:02d}-{suffix}", query, term, kind, pair=f"family-{i}" if suffix in ["term","spaces"] else None)
    for i, (q, fragment, kind, outcome) in enumerate([
        ("포", "포", "one_character", "MATCH"), ("김", "김", "one_character", "MATCH"),
        ("POCKY", "pocky", "latin", "MATCH"), ("pocky", "pocky", "latin", "MATCH"),
        ("두유바ZZQNONEXIST", "", "negative", "EMPTY"), ("검증용없는식품ZZQ999", "", "negative", "EMPTY"),
        ("   ", "", "empty_input", "EMPTY"), ("---", "", "empty_input", "EMPTY")]):
        add(f"boundary-{i}",q,fragment,kind,outcome)
    manifest = {"dataset_version": "expanded-search-recommendation-20261028-v2", "created_at": datetime.now(timezone.utc).isoformat(),
        "label_status": "AI-assisted pre-registered silver labels and constraint probes, not human/expert gold",
        "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(), "profiles": profiles,
        "recommendation_cases": cases, "search_cases": search,
        "limitations": ["intentional samples, not random population estimates", "regex relevance is a proxy; unjudged items are not proven irrelevant",
            "narrow raw-ingredient positives only; no absence-as-safety labels", "policy/output is never used to generate forbidden labels",
            "12 diet profiles are contract probes, not independently certified diet gold", "Top100 pool conditional relevance only",
            "one-character/typo cases measure capability gaps, not an agreed feature guarantee"]}
    save(out / "expanded-frozen-v2.json", manifest)
    save(out / "positive-evidence-review-v2.json", evidence_review)
    print(json.dumps({"search_cases":len(search), "recommendation_cases":len(cases),"profiles":len(profiles),
        "references":len(evidence["references"]), "positive_checks":len(evidence_review), "category_counts":dict(Counter(r["category"] for r in evidence["references"]))},ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
