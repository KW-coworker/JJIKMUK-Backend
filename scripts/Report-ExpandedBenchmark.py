"""Reproducible analysis of frozen JSON artifacts. Never connects to a database.

Silver labels are diagnostic proxies, not human/expert gold. Post-run adjudications
are an explicit overlay; the original observations and frozen labels stay intact.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
import math
from pathlib import Path
import statistics
import unicodedata
import xml.etree.ElementTree as ET


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value, refresh=False):
    if path.exists() and not refresh:
        raise ValueError(f"Refusing to overwrite: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def norm(value):
    return "".join(c for c in unicodedata.normalize("NFKC", value or "").lower() if c.isalnum())


def ratio(a, b):
    return a / b if b else None


def rank_metrics(ids, relevant, k=10):
    relevant = set(relevant)
    if not relevant:
        return None  # Unjudged/empty positive sets must not inflate accuracy.
    seen = set()
    gains = []
    for barcode in ids[:k]:
        gains.append(barcode in relevant and barcode not in seen)
        seen.add(barcode)
    first = next((i + 1 for i, gain in enumerate(gains) if gain), None)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return {"hit": int(first is not None), "mrr": 1 / first if first else 0,
            "ndcg": sum(g / math.log2(i + 2) for i, g in enumerate(gains)) / ideal,
            "labeled_positive_at_10": sum(gains) / k, "first_rank": first}


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else None


def presentation_errors(row):
    items = row["items"]
    errors = []
    if len({i["barcode"] for i in items}) != len(items):
        errors.append("duplicate_barcode")
    if row["result_mode"] in ("VERIFIED", "RELAXED_SAFE"):
        if any(i["safety"] != "PASS" or i["diet"] != "PASS" or i["verificationRequired"] for i in items):
            errors.append("unverified_presented_as_safe")
    if row["result_mode"] == "VERIFICATION_REQUIRED":
        if any(not i["verificationRequired"] or not i["warnings"] or not i["requiredActions"] or
               (i["safety"] != "UNKNOWN" and i["diet"] != "UNKNOWN") for i in items):
            errors.append("missing_verification_guidance")
    if row["result_mode"] == "ACTION_REQUIRED" and items:
        errors.append("items_in_abstention")
    return errors


def analyze(directory):
    definition = load(directory / "expanded-frozen-v2.json")
    evidence = load(directory / "expanded-evidence.json")
    assert hashlib.sha256((directory / "expanded-evidence.json").read_bytes()).hexdigest() == definition["evidence_sha256"]
    searches = load(directory / "search-results.json")
    runs = load(directory / "recommendation-results.json")
    regression = load(directory / "original-regression-report.json")
    cases = {c["case_id"]: c for c in definition["recommendation_cases"]}
    search_defs = {c["case_id"]: c for c in definition["search_cases"]}
    products = {p["barcode"]: p for p in evidence["candidates"]}
    refs = {r["product"]["barcode"]: r for r in evidence["references"]}
    products.update({b: r["product"] for b, r in refs.items()})
    assert len(cases) == 1050 and len(searches) == len(search_defs) == 143
    assert len({(r["case_id"], r["pool_size"], r["old_regression"]) for r in runs}) == len(runs)

    # Review after alarm inspection: the source text is buckwheat flour, not an
    # independent positive for the separate WHEAT ID. Do not relabel it SAFE.
    reviewed = {
        "8803077000001": "메밀가루",
        "8809742430012": "곡류가공품, 볶은메밀가루, 전분가공품, 면류첨가알칼리제, 볶은쌀가루, 정제소금, 정제수, 전분가공품",
    }
    adjudications = []
    for c in cases.values():
        if c["profile"] not in ("wheat", "multi"):
            continue
        for barcode in sorted(set(reviewed).intersection(c["forbidden_barcodes"])):
            p = products[barcode]
            if p["raw_materials"] != reviewed[barcode]:
                continue  # A changed ingredient list invalidates this review.
            adjudications.append({"case_id": c["case_id"], "barcode": barcode, "product_name": p["product_name"],
                "raw_materials": p["raw_materials"], "original_label": "forbidden", "reviewed_label": "UNJUDGED",
                "reason": "메밀가루 안의 '밀가루' 부분 문자열을 WHEAT 양성으로 잘못 잡은 평가 라벨 오류. 안전 확정으로 바꾸는 것이 아니라 이 양성 근거만 제외한다.",
                "review_timing": "post-run; original frozen labels and raw alarms retained"})
    excluded_labels = {(a["case_id"], a["barcode"]) for a in adjudications}

    search_details = []
    for row in searches:
        c = search_defs[row["case_id"]]
        hits = [i + 1 for i, p in enumerate(row["products"]) if any(
            norm(f) in norm(p.get("productName")) or norm(f) in norm(p.get("cleanProductName")) for f in c["fragments"])]
        positive = c["expected_outcome"] == "MATCH"
        failure = None
        if row["error"]:
            failure = "QUERY_ERROR"
        elif not positive:
            failure = "NEGATIVE_RETURNED_RESULTS" if row["products"] else None
        elif not hits:
            failure = {"brand_plus_name": "COMPOUND_QUERY_MISS", "single_character_typo": "TYPO_CAPABILITY_GAP",
                       "latin": "LATIN_CATALOG_OR_ALIAS_GAP"}.get(c["kind"], "EMPTY_OR_TOP10_LABEL_MISS")
        search_details.append({"case_id": row["case_id"], "query": row["query"], "kind": row["kind"],
            "positive": positive, "result_count": len(row["products"]), "error": row["error"],
            "hit": bool(hits), "first_rank": hits[0] if hits else None, "failure": failure,
            "latency_ms": row["latency_micros"] / 1000, "reused": row["normalization_equivalent_reused"],
            "top3": [{"barcode": p["barcode"], "name": p.get("productName")} for p in row["products"][:3]]})
    by_kind = []
    for kind in dict.fromkeys(r["kind"] for r in search_details):
        rows = [r for r in search_details if r["kind"] == kind]
        positives = [r for r in rows if r["positive"]]
        by_kind.append({"kind": kind, "cases": len(rows), "nonempty": sum(r["result_count"] > 0 for r in rows),
            "positive_cases": len(positives), "hits": sum(r["hit"] for r in positives),
            "negative_correct": sum(not r["positive"] and not r["failure"] for r in rows),
            "errors": sum(bool(r["error"]) for r in rows)})
    measured = [r for r in search_details if not r["reused"]]
    nonempty_normalized = [r for r in measured if norm(r["query"]) and not r["error"]]
    latencies = [r["latency_ms"] for r in nonempty_normalized]
    pairs = defaultdict(list)
    for row in searches:
        if pair := search_defs[row["case_id"]]["pair_group"]:
            pairs[pair].append(row)
    pair_results = [{"group": key, "nonempty": all(v["products"] for v in rows),
                     "same_order": len({tuple(p["barcode"] for p in v["products"]) for v in rows}) == 1}
                    for key, rows in pairs.items() if len(rows) > 1]

    base = [r for r in runs if not r["old_regression"] and r["pool_size"] == 100]
    recommendation_details = []
    for r in base:
        c = cases[r["case_id"]]
        ids = [i["barcode"] for i in r["items"]]
        groups = [products[b].get("product_group_key") or "ungrouped:" + b for b in ids]
        misses = [b for b in r["raw_positive_not_blocked"] if (r["case_id"], b) not in excluded_labels]
        forbidden = [b for b in r["forbidden_returned"] if (r["case_id"], b) not in excluded_labels]
        metric = rank_metrics(ids, c["relevant_barcodes"]) if c["ranking_judged"] else None
        reasons = []
        if forbidden or misses:
            reasons.append("POSITIVE_EVIDENCE_SAFETY_ALARM")
        if r["result_mode"] == "ACTION_REQUIRED":
            reasons.append("NO_RETURNABLE_CANDIDATE")
        if r["result_mode"] == "VERIFICATION_REQUIRED":
            reasons.append("INSUFFICIENT_VERIFICATION_DATA")
        if r["result_mode"] == "RELAXED_SAFE":
            reasons.append("NO_CANDIDATE_ABOVE_SIMILARITY_THRESHOLD")
        if metric and not metric["hit"]:
            reasons.append("SILVER_POSITIVE_MISSED_IN_TOP10")
        if not c["relevant_barcodes"] and c["profile"] == "general":
            reasons.append("NO_LABELED_FUNCTION_MATCH_IN_TOP100")
        if len(set(groups)) < len(groups):
            reasons.append("DUPLICATE_PRODUCT_GROUP_IN_RESULTS")
        recommendation_details.append({"case_id": r["case_id"], "reference_barcode": r["reference_barcode"],
            "reference_name": refs[r["reference_barcode"]]["product"]["product_name"], "category": c["category"],
            "profile": r["profile"], "result_mode": r["result_mode"], "returned": len(ids),
            "ranking_proxy": metric, "ranking_judged": c["ranking_judged"],
            "reference_review": c["reference_review"], "positive_candidates": len(c["relevant_barcodes"]),
            "failure_types": reasons, "excluded": r["excluded"], "forbidden_raw": r["forbidden_returned"],
            "forbidden_after_label_review": forbidden, "positive_not_blocked_after_review": misses,
            "presentation_errors": presentation_errors(r), "duplicate_group_extra_items": len(groups) - len(set(groups)),
            "top3": [{"barcode": i["barcode"], "name": i["name"], "food_type": products[i["barcode"]]["food_type"],
                "safety": i["safety"], "diet": i["diet"], "tier": i["tier"], "original_rank": i["originalRank"]} for i in r["items"][:3]]})
    ranked = [r["ranking_proxy"] for r in recommendation_details if r["ranking_proxy"] is not None]
    profile_rows = []
    for profile in definition["profiles"]:
        rows = [r for r in recommendation_details if r["profile"] == profile]
        positive_products = {b for c in cases.values() if c["profile"] == profile for b in c["forbidden_barcodes"]
                             if (c["case_id"], b) not in excluded_labels}
        profile_rows.append({"profile": profile, "cases": len(rows), "modes": dict(Counter(r["result_mode"] for r in rows)),
            "distinct_positive_evidence_products": len(positive_products),
            "empty_cases": sum(r["returned"] == 0 for r in rows)})
    pool_rows = []
    for size in (20, 50, 100):
        subset = [r for r in runs if not r["old_regression"] and r["profile"] in ("general", "milk", "soy", "vegan") and r["pool_size"] == size]
        pool_rows.append({"pool_size": size, "cases": len(subset), "modes": dict(Counter(r["result_mode"] for r in subset)),
            "returned": sum(len(r["items"]) for r in subset), "empty_cases": sum(not r["items"] for r in subset),
            "verified_or_relaxed_cases": sum(r["result_mode"] in ("VERIFIED", "RELAXED_SAFE") for r in subset),
            "raw_forbidden_returned": sum(len(r["forbidden_returned"]) for r in subset)})
    strict_policy_violations = sum(i["safety"] == "DANGER" or i["diet"] == "MISMATCH" for r in base for i in r["items"])
    total_items = sum(len(r["items"]) for r in base)
    allergen_profiles = [p for p, v in definition["profiles"].items() if v["allergies"] == p and not v["specialDiet"]]
    empty_rows = [r for r in base if not r["items"]]
    db_diagnostics = load(directory / "search-catalog-diagnostics.json") if (directory / "search-catalog-diagnostics.json").exists() else None
    test_totals = Counter()
    backend = Path(__file__).resolve().parents[1]
    for path in (backend / "build/test-results/test").glob("TEST-*.xml"):
        suite = ET.parse(path).getroot()
        test_totals.update({k: int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")})
    summary = {"scope": {"search_cases": len(searches), "search_unique_normalized_executions": len(measured),
            "recommendation_unique_cases": len(base), "all_recommendation_replays_including_pool_and_regression": len(runs),
            "profiles": len(definition["profiles"]), "references": len(refs), "candidate_products": len(evidence["candidates"]),
            "categories": len({r["category"] for r in refs.values()}), "database_writes": 0},
        "search": {"by_kind": by_kind, "errors": sum(bool(r["error"]) for r in search_details),
            "catalog_spelling_diagnostics": db_diagnostics,
            "positive_cases": sum(r["positive"] for r in search_details),
            "positive_hits": sum(r["positive"] and r["hit"] for r in search_details),
            "negative_cases": sum(not r["positive"] for r in search_details),
            "negative_correct": sum(not r["positive"] and not r["failure"] for r in search_details),
            "failure_counts": dict(Counter(r["failure"] for r in search_details if r["failure"])),
            "spacing_pairs": pair_results, "timing_scope": "single sequential local repository pass, normalized duplicates reused; not HTTP or load test",
            "timed_nonempty_normalized_executions": len(latencies), "median_ms": statistics.median(latencies),
            "p95_ms": percentile(latencies, .95), "max_ms": max(latencies)},
        "recommendation": {"modes": dict(Counter(r["result_mode"] for r in base)), "returned_items": total_items,
            "empty_case_causes": {"all_100_danger": sum(r["excluded"]["danger"] == 100 for r in empty_rows),
                                  "all_100_diet_mismatch": sum(r["excluded"]["dietMismatch"] == 100 for r in empty_rows)},
            "candidate_allergy_evidence": dict(Counter(p["allergy_evidence_level"] for p in evidence["candidates"])),
            "candidate_dietary_origin": dict(Counter(p["dietary_data_origin"] for p in evidence["candidates"])),
            "candidate_missing_raw": sum(not p["raw_materials"] for p in evidence["candidates"]),
            "allergens_with_no_positive_examples": [p["profile"] for p in profile_rows if p["profile"] in allergen_profiles and not p["distinct_positive_evidence_products"]],
            "raw_label_alarms": sum(len(r["forbidden_returned"]) for r in base), "reviewed_label_rows_removed": len(adjudications),
            "reviewed_positive_alarms": sum(len(r["forbidden_after_label_review"]) for r in recommendation_details),
            "known_policy_violation_items": strict_policy_violations,
            "presentation_violation_cases": sum(bool(r["presentation_errors"]) for r in recommendation_details),
            "ranking_proxy_cases": len(ranked), "ranking_proxy_hit_count": sum(m["hit"] for m in ranked),
            "ranking_proxy_hit_at_10": statistics.mean(m["hit"] for m in ranked),
            "ranking_proxy_ndcg_at_10": statistics.mean(m["ndcg"] for m in ranked),
            "ranking_proxy_mrr": statistics.mean(m["mrr"] for m in ranked),
            "failure_counts_nonexclusive": dict(Counter(v for r in recommendation_details for v in r["failure_types"])),
            "profiles": profile_rows, "pool_comparison": pool_rows},
        "original_regression": {k: v for k, v in regression.items() if k != "results"},
        "verification": {"latest_default_gradle_suite": dict(test_totals), "recorded_execution":
                         load(directory / "execution-verification.json") if (directory / "execution-verification.json").exists() else None},
        "provenance": {str(path.relative_to(backend)): hashlib.sha256(path.read_bytes()).hexdigest() for path in [
            backend / "src/test/kotlin/org/jjikmuk/backend/evaluation/ExpandedOfflineBenchmarkTest.kt",
            backend / "src/main/kotlin/org/jjikmuk/backend/domain/recommendation/RecommendationPolicy.kt",
            backend / "src/main/kotlin/org/jjikmuk/backend/domain/recommendation/RecommendationService.kt",
            backend / "src/main/kotlin/org/jjikmuk/backend/domain/allergy/AllergySafetyService.kt",
            backend / "src/main/kotlin/org/jjikmuk/backend/domain/product/DistinctProductSearchRepository.kt"]},
        "limitations": definition["limitations"] + ["No real user/history data; synthetic profiles and cold start only",
            "Only barcode alternative recommendation service; home-feed pagination/family/HTTP flows not re-evaluated",
            "Search positives are normalized-name containment checks, not user relevance gold",
            "Original 10-query design expanded; spicy-shrimp spacing variant differs, no prior search performance delta claimed",
            "Post-run wheat/buckwheat label adjudications are visible; uncorrected alarms also retained",
            "Positive-label absence does not establish safety; 3675 returned items are repeated exposures, not distinct foods"]}
    return summary, search_details, recommendation_details, adjudications


def render(summary, search, recommendations, adjudications):
    esc = lambda x: html.escape(str(x))
    def table(headers, rows):
        return "<div class='scroll'><table><thead><tr>" + "".join(f"<th>{esc(h)}</th>" for h in headers) + "</tr></thead><tbody>" + "".join(
            "<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>" for row in rows) + "</tbody></table></div>"
    r = summary["recommendation"]
    s = summary["search"]
    body = "<h1>검색·추천 확장 평가와 실패 분석</h1><p>2026-10-28 · 로컬 MySQL 읽기 전용 + 고정 데이터 추천 재생</p>"
    body += "<aside>평가 범위를 넓힌 진단 보고서이다. 자동 생성한 silver 라벨을 사용하므로 서비스 전체 정확도 또는 의학적 안전성 인증으로 해석할 수 없다. 운영 DB·CSV·추천 정책은 변경하지 않았다.</aside>"
    body += "<h2>1. 평가 범위</h2>" + table(["항목", "범위"], summary["scope"].items())
    body += "<p>25개 기준 상품 × 42개 조건 = 1,050개. 별도로 100개 조건의 후보 수 20/50/100 비교와 기존 회귀 20개를 실행했다. 13개 분류의 의도적 표본이며 무작위 모집단 표본이 아니다.</p>"
    body += "<h2>2. 검색</h2>" + table(["입력 유형", "사례", "결과 있음", "기대 이름 일치", "양성 사례", "음성 정답", "오류"],
        [[v[k] for k in ("kind", "cases", "nonempty", "hits", "positive_cases", "negative_correct", "errors")] for v in s["by_kind"]])
    body += f"<p>LOCATE/key 모드, FULLTEXT 인덱스 없음. 정규화가 같은 입력은 재사용하므로 143개 판단이 독립적인 143회 SQL 측정은 아니다. 빈 정규화 입력을 제외한 {s['timed_nonempty_normalized_executions']}회: 중앙값 {s['median_ms']:.0f}ms / p95 {s['p95_ms']:.0f}ms / 최대 {s['max_ms']:.0f}ms. 로컬 순차 실행 1회이며 부하·동시성·HTTP 지연을 측정하지 않았다.</p>"
    body += "<p>제조사+상품명을 하나의 문자열로 검색하면 각 필드의 LOCATE에 동시에 들어가 복합 검색이 잘 되지 않는다. 제조사 필드에 공장명·주소·전화번호가 포함된 사례도 있다. 오타·영문은 별도의 기능 공백이며 현재 구현의 지원 보장을 전제한 회귀 실패는 아니다.</p>"
    body += "<p>오타 25개 중 1개의 이름 일치는 오타 교정 성공이 아니다. '떡→욤' 입력이 '욤 꿀호떡'을 찾아 우연히 라벨과 겹친 사례다. 1글자 입력의 부분 문자열 성공을 유용한 검색으로 단정하지 않는다.</p>"
    if s["catalog_spelling_diagnostics"]:
        counts = s["catalog_spelling_diagnostics"]["counts"][0]
        body += f"<p>영문 별칭 진단: product_name의 POCKY 표기 {counts['pocky_name_rows']}건, clean_product_name {counts['pocky_clean_rows']}건, 한글 포키 표기 {counts['korean_pocky_rows']}건. 이번 영문 빈 결과는 영문 데이터/별칭 공백으로 구분한다.</p>"
    body += "<details><summary>검색 실패 전체 보기</summary>" + table(["ID", "검색어", "분류", "상위 3개"],
        [[v["case_id"], v["query"], v["failure"], "; ".join(p["name"] or "" for p in v["top3"])] for v in search if v["failure"]]) + "</details>"
    body += "<h2>3. 추천 결과와 안전성</h2>" + table(["모드", "조건 수", "의미"],
        [[mode, r["modes"].get(mode, 0), text] for mode, text in [("VERIFIED", "엄격 조건·기본 유사도 통과"), ("RELAXED_SAFE", "안전 조건 유지, 유사도 기준만 완화"), ("VERIFICATION_REQUIRED", "추가 확인 후보; 안전 추천과 구분"), ("ACTION_REQUIRED", "반환 가능한 후보 없음")]])
    body += f"<p>반환 노출 {r['returned_items']}건 중 기존 DANGER/MISMATCH 반환 {r['known_policy_violation_items']}건, UNKNOWN 안내 계약 위반 {r['presentation_violation_cases']}개 사례. 독립 원재료 정규식은 최초 {r['raw_label_alarms']}건을 경고했으나, 원문 대조 결과 평가기가 메밀가루를 밀가루로 잡은 라벨 오류였다. 검수 후 이 양성 근거에 의한 미차단 경고는 {r['reviewed_positive_alarms']}건이다. 이것은 미탐이 전혀 없다는 뜻이 아니다.</p>"
    body += "<details><summary>라벨 오류 수정 이력 — 원본은 보존</summary>" + table(["사례", "바코드", "상품", "원재료", "처리"],
        [[v[k] for k in ("case_id", "barcode", "product_name", "raw_materials", "reason")] for v in adjudications]) + "</details>"
    body += "<h3>조건별 결과와 양성 근거 커버리지</h3>" + table(["조건", "VERIFIED", "RELAXED_SAFE", "확인 필요", "빈 결과", "독립 양성 상품 수"],
        [[v["profile"], v["modes"].get("VERIFIED", 0), v["modes"].get("RELAXED_SAFE", 0), v["modes"].get("VERIFICATION_REQUIRED", 0), v["empty_cases"], v["distinct_positive_evidence_products"]] for v in r["profiles"]])
    body += "<p>양성 상품 수 0인 알레르기는 탐지 성능을 검증한 것으로 계산하면 안 된다. 식단 12개 조건의 수치는 계약/반환 형태 확인이지 별도로 인증한 영양·식단 정답 성능이 아니다. 제외 사유는 정책의 첫 분기에서 집계되므로 같은 상품의 모든 문제를 중복 집계한 값이 아니다.</p>"
    body += "<p>알레르기 양성 표본이 없는 항목: " + esc(", ".join(r["allergens_with_no_positive_examples"])) + ". 다음 gold 확장 우선 대상이다.</p>"
    body += table(["후보 데이터 근거 수준", "상품 수"], r["candidate_allergy_evidence"].items())
    body += f"<p>후보 2,372개 중 원재료 미입력 {r['candidate_missing_raw']}개. DECLARED_LABEL 114개이고 VERIFIED_SOURCE는 0개다. 참깨·아몬드·머스타드·셀러리는 현재 정책에서 VERIFIED_SOURCE가 필요하여 각 25개 조합 모두 확인 필요로 끝났다. 모든 후보의 식단 속성 출처는 INFERRED이며, 비건 자체의 공식 인증 정확도는 이번 평가로 확인하지 않았다.</p>"
    body += f"<p>빈 결과 15개는 오류 응답이 아니다. 후보 100개 전부 알레르기 DANGER인 조합 {r['empty_case_causes']['all_100_danger']}개, 전부 식단 MISMATCH인 조합 {r['empty_case_causes']['all_100_diet_mismatch']}개다. 두부+대두 알레르기, 포키+복수 알레르기 등이 해당한다. 안전 기준을 해제하는 대신 같은 소비 용도의 다른 재료 상품을 후보 생성 단계에 추가해야 한다.</p>"
    body += "<h2>4. 후보 수 비교</h2>" + table(["후보 수", "동일 조건", "VERIFIED", "RELAXED_SAFE", "확인 필요", "빈 결과", "반환 노출"],
        [[v["pool_size"], v["cases"], v["modes"].get("VERIFIED", 0), v["modes"].get("RELAXED_SAFE", 0), v["modes"].get("VERIFICATION_REQUIRED", 0), v["empty_cases"], v["returned"]] for v in r["pool_comparison"]])
    body += "<p>화면 표시 10개와 내부 후보 100개는 다르다. 위 결과는 general/milk/soy/vegan의 동일 100개 조합만 비교한다. 전체 1,050개와 분모를 섞지 않는다. ANN 재생성·DB 저장 성능이나 사용자 만족도 비교는 아니다.</p>"
    body += "<h2>5. 순위 및 데이터 문제</h2>"
    body += f"<p>사전 검수에서 용도가 모호한 기준 상품 5개, Top100 내 양성 라벨 없는 1개를 순위 정확도에서 제외했다. 남은 일반 조건 {r['ranking_proxy_cases']}개에서 silver Hit@10={r['ranking_proxy_hit_count']}/{r['ranking_proxy_cases']}, MRR={r['ranking_proxy_mrr']:.3f}, NDCG@10={r['ranking_proxy_ndcg_at_10']:.3f}. 이름 정규식으로 만든 대체 용도 대리지표이므로 절대 정확도로 인용하지 않는다.</p>"
    body += table(["기준 상품", "순위 포함", "양성 후보", "Top3 실제 결과", "검수/실패"],
        [[v["reference_name"], v["ranking_judged"], v["positive_candidates"], "; ".join(p["name"] or "" for p in v["top3"]), v["reference_review"] or ", ".join(v["failure_types"])] for v in recommendations if v["profile"] == "general"])
    body += "<p>원본 상품 정보 대조에서 명확한 Top1 용도 혼동을 확인했다: 꽈배기 아이스크림 → 꽈배기(식품유형: 어묵), 이마트후레쉬초고추장(소스) → 고추장아찌무침(절임식품). 이름 공통 부분만으로 대체 가능성을 판단하면 안 된다. 닭가슴살물만두 → 닭가슴살 단품, 불명확한 King Bowl(김치) → KING쥐포/과자/소스도 별도 검수 대상이다.</p>"
    body += "<aside>순위 라벨도 완전하지 않다. 아이스크림의 2위 '상큼한딸기아이스'(빙과)는 정규식에 걸리지 않았고, 초고추장의 1위 '고추장아찌무침'은 반대로 양성으로 집계됐다. 멀티단백질다이어트의 반환 쉐이크는 같은 식품유형이지만 이름 정규식 양성이 없다. 따라서 proxy의 18/19를 실제 성공률, 양성 0개를 실제 대체 상품 부재라고 주장하지 않는다. 후보/정답을 사람 검수하는 것이 우선이다.</aside>"
    body += "<h2>6. 기존 20개 회귀</h2>" + table(["지표", "이번 결과"], [[k, v] for k, v in summary["original_regression"].items() if k in ("hitRateAtK", "ndcgAtK", "outcomeMatchRate", "correctAbstentionRate", "hardConstraintViolationRate", "presentationViolationCount")])
    body += "<p>기존 v5.1과 동일한 20개/정답/후보를 유지했다. 원래 수집한 상품 필드와 후보 문자열이 현재 로컬 DB와 동일함을 확인하고 누락된 점수 필드만 보충했다. 주요 품질 지표는 v5.1과 동일하다. 두 실행의 지연은 환경이 달라 성능 개선/악화로 비교하지 않는다.</p>"
    tests = summary["verification"]["latest_default_gradle_suite"]
    body += f"<p>검증: 최신 기본 테스트 XML {tests.get('tests', 0)}개 중 성공 {tests.get('tests', 0)-tests.get('skipped', 0)-tests.get('failures', 0)-tests.get('errors', 0)}개 / 건너뜀 {tests.get('skipped', 0)}개 / 실패 {tests.get('failures', 0)}개.</p>"
    if summary["verification"]["recorded_execution"]:
        body += "<p>2026-10-28 실행 기록(execution-verification.json): 별도 opt-in 평가 테스트 2개, 집계 단위 테스트 6개 성공. bootJar 빌드 성공.</p>"
    body += "<h2>7. 다음 작업 우선순위</h2><ol><li>검색: 제조사·상품명 토큰을 나눠 조합하고 exact/prefix를 우선한다. 주소·연락처를 브랜드 키워드와 분리한다.</li><li>검색 성능: 복제 스테이징에서 ngram FULLTEXT 구축 전후, 동일 검색셋과 반복/동시성 조건으로 측정한다. 운영 인덱스는 이번 작업에서 변경하지 않았다.</li><li>추천: 완제품/재료/믹스/맛 표기를 분리한 용도별 후보 생성과 상품 그룹 단위 다양성·중복 제거를 실험한다.</li><li>안전 데이터: UNKNOWN이 많은 출처·표시 범위를 보강한다. 빈 결과를 줄이기 위해 알레르기 조건을 해제하지 않는다.</li><li>평가: 양성 표본이 없는 항목을 추가하고, 실패/성공을 함께 층화 추출해 사람 검수 gold를 만든다. 이 평가셋은 진단/개발용으로 사용하고 별도 holdout을 확보한다.</li></ol>"
    body += "<h2>8. 한계와 재현 자료</h2><ul>" + "".join(f"<li>{esc(x)}</li>" for x in summary["limitations"]) + "</ul>"
    body += "<p>summary.json · search-analysis.json · recommendation-analysis.json · label-adjudications.json · expanded-frozen-v2.json · search-results.json · recommendation-results.json · original-regression-report.json</p>"
    return "<!doctype html><html lang='ko'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>검색·추천 확장 평가</title><style>body{font-family:Arial,'Malgun Gothic',sans-serif;max-width:1200px;margin:auto;padding:32px;color:#193b32;background:#f8fbf9;line-height:1.65}h1,h2{color:#126344}h2{margin-top:40px}aside{background:#fff2ce;padding:18px;border-radius:12px}table{border-collapse:collapse;width:100%;font-size:14px;background:white}th,td{border:1px solid #d4e3db;padding:9px;text-align:left;vertical-align:top}th{background:#e5f3eb}td{overflow-wrap:anywhere}.scroll{overflow-x:auto}details{margin:18px 0}summary{cursor:pointer;font-weight:bold}p{max-width:1120px}</style>" + body + "</html>"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--refresh-derived", action="store_true", help="Only regenerate the fixed derived report files; never frozen inputs/results")
    args = parser.parse_args()
    summary, search, recs, adjudications = analyze(args.directory)
    for name, value in [("summary.json", summary), ("search-analysis.json", search), ("recommendation-analysis.json", recs), ("label-adjudications.json", adjudications)]:
        save(args.directory / name, value, args.refresh_derived)
    report = args.directory / "report.html"
    if report.exists() and not args.refresh_derived:
        raise ValueError("Report already exists")
    report.write_text(render(summary, search, recs, adjudications), encoding="utf-8")
    print(json.dumps({"report": str(report), "scope": summary["scope"], "search": summary["search"]["failure_counts"],
        "recommendation": {k: v for k, v in summary["recommendation"].items() if k not in ("profiles",)}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
