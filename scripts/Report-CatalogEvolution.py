"""Compare immutable recommendation replays and local test evidence. No network or DB access."""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    targets = [args.output / "comparison.json", args.output / "report.html"]
    if any(p.exists() for p in targets):
        raise ValueError("Refusing to overwrite a comparison record")
    old = read(args.baseline / "recommendation-results.json")
    new = read(args.replay / "recommendation-results.json")
    key = lambda r: (r["case_id"], r["pool_size"])
    assert len(old) == len(new) == 1270
    assert {key(r) for r in old} == {key(r) for r in new}
    inputs = {}
    for name in ("expanded-evidence.json", "expanded-frozen-v2.json", "original-enriched-evidence.json"):
        before, after = digest(args.baseline / name), digest(args.replay / name)
        assert before == after, name
        inputs[name] = before
    old100 = [r for r in old if not r["old_regression"] and r["pool_size"] == 100]
    new100 = [r for r in new if not r["old_regression"] and r["pool_size"] == 100]
    assert len(old100) == len(new100) == 1050
    old_by_key = {key(r): r for r in old}
    transitions = Counter(f'{old_by_key[key(r)]["result_mode"]} → {r["result_mode"]}' for r in new100)
    regression_before = read(args.baseline / "original-regression-report.json")
    regression_after = read(args.replay / "original-regression-report.json")
    metrics = ("outcomeMatchRate", "hitRateAtK", "ndcgAtK", "rankingCaseCount", "correctAbstentionRate", "hardConstraintViolationRate")
    assert all(regression_before[m] == regression_after[m] for m in metrics)

    samples = []
    for code, label in [("8801019404702", "꽈배기 아이스크림"), ("1500000064822", "이마트후레쉬초고추장"),
                        ("8801007124247", "닭가슴살물만두"), ("648436122417", "King Bowl(김치)")]:
        choose = lambda rows: next(r for r in rows if r["reference_barcode"] == code and r["profile"] == "general")
        before, after = choose(old100), choose(new100)
        samples.append({"reference": label, "barcode": code, "before": before["items"], "after": after["items"],
                        "excluded": after["excluded"], "result_mode": after["result_mode"]})

    counts = Counter()
    suites = []
    for path in sorted((root / "build/test-results/test").glob("TEST-*.xml")):
        suite = ET.parse(path).getroot()
        fields = {field: int(suite.get(field, 0)) for field in ("tests", "failures", "errors", "skipped")}
        counts.update(fields)
        suites.append({"suite": suite.get("name"), **fields})
    assert counts["tests"] >= 184 and counts["failures"] == counts["errors"] == 0, counts
    counts["passed"] = counts["tests"] - counts["skipped"]
    http = read(root / "build/integration/core-http-checks.json")
    assert all(r["expectedStatus"] == r["actualStatus"] for r in http)
    mysql = read(args.output / "mysql-migration-test.json")
    assert mysql["source_jjikmuk_writes"] == 0 and all(r["passed"] for r in mysql["results"])
    forbidden_count = lambda rows: sum(len(r["forbidden_returned"]) for r in rows)
    danger_count = lambda rows: sum(i["safety"] == "DANGER" or i["diet"] == "MISMATCH" for r in rows for i in r["items"])
    source_files = ["src/main/kotlin/org/jjikmuk/backend/domain/product/CatalogEvolution.kt",
                    "src/main/kotlin/org/jjikmuk/backend/domain/product/ProductCategoryPolicy.kt",
                    "src/main/kotlin/org/jjikmuk/backend/domain/recommendation/RecommendationService.kt",
                    "src/main/kotlin/org/jjikmuk/backend/global/config/ProductDataImportService.kt",
                    "src/main/resources/db/migration/V15__expand_product_ids_and_attribute_history.sql"]
    summary = {
        "scope": "Local code and frozen-data replay, NOT deployed or applied to the original DB",
        "policy": "unified-hard-constraints-purpose-v5.2", "category_policy": "consumer-purpose-v1",
        "input_sha256": inputs, "code_sha256": {p: digest(root / p) for p in source_files},
        "total_replays": len(new), "expanded_top100_cases": len(new100),
        "modes_before": dict(Counter(r["result_mode"] for r in old100)),
        "modes_after": dict(Counter(r["result_mode"] for r in new100)), "transitions": dict(transitions),
        "category_mismatch_exposures": sum(r["excluded"]["categoryMismatch"] for r in new100),
        "category_unknown_exposures": sum(r["excluded"]["categoryUnknown"] for r in new100),
        "danger_or_diet_mismatch_returned": {"before": danger_count(old100), "after": danger_count(new100)},
        "raw_silver_forbidden_returned": {"before": forbidden_count(old100), "after": forbidden_count(new100)},
        "raw_silver_note": "Both runs retain 2 known buckwheat/wheat label alerts. Prior UNJUDGED adjudications are not rewritten.",
        "regression": {m: {"before": regression_before[m], "after": regression_after[m]} for m in metrics},
        "samples": samples, "unit_integration_tests": dict(counts), "test_suites": suites,
        "http_checks": len(http), "mysql_fixture_tests": mysql,
        "limitations": ["No original or production DB mutation", "No full-size import or performance validation",
                        "Purpose UNKNOWN candidates remain; no global accuracy claim", "Small development set, not independent gold",
                        "No physical variant/revision identity merge", "Search benchmark not rerun; search algorithm unchanged"]
    }
    escape = lambda value: html.escape(str(value))
    modes = "".join(f"<tr><td>{escape(mode)}</td><td>{summary['modes_before'].get(mode, 0)}</td><td>{summary['modes_after'].get(mode, 0)}</td></tr>"
                    for mode in ("VERIFIED", "RELAXED_SAFE", "VERIFICATION_REQUIRED", "ACTION_REQUIRED"))
    examples = ""
    for sample in samples:
        names = lambda rows: "<ol>" + "".join(f"<li>{escape(i['name'])} <small>{escape(i['barcode'])}</small></li>" for i in rows[:5]) + "</ol>"
        examples += f"<h3>{escape(sample['reference'])} <small>{escape(sample['barcode'])}</small></h3><div class='comparison'><section><b>변경 전 Top5</b>{names(sample['before'])}</section><section><b>변경 후 Top5</b>{names(sample['after'])}</section></div>"
    document = f"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>속성 이력·상품 ID·카테고리 정책 적용 결과</title><style>
body{{font:16px/1.7 system-ui,'Malgun Gothic',sans-serif;max-width:1050px;margin:36px auto;padding:0 24px;color:#233333;background:#f7faf8}}
h1{{line-height:1.3}} h2{{margin-top:38px;border-bottom:2px solid #c2d6c7}} small{{display:block;color:#596e62}}
.note{{padding:18px;background:#fff4d9;border-left:5px solid #cc9a24}} .comparison{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
section{{background:white;padding:18px;border:1px solid #d8e3da;border-radius:10px}} table{{border-collapse:collapse;width:100%;background:white}}
th,td{{text-align:left;padding:10px;border-bottom:1px solid #d8e3da}}code{{word-break:break-all}} @media(max-width:650px){{.comparison{{grid-template-columns:1fr}}}}
</style><h1>속성 이력 · 상품 ID · 카테고리 정책</h1><p>2026-10-28 · 단계적 구현 / 동일 평가셋 재생 결과</p>
<div class="note">코드·API·V15 마이그레이션을 준비하고 격리 환경에서 검증했다. <b>운영 DB와 로컬 원본 jjikmuk DB에는 적용하지 않았다.</b> 기본키를 바꾸거나 상품을 자동 병합하지 않았다.</div>
<h2>1. 구현 범위</h2><table><tr><th>영역</th><th>이번 구현</th></tr>
<tr><td>속성 이력</td><td>기존/새 관측, 출처·확신도, 데이터 버전·변경 사유·작업자 보존. 동일 재시도 중복 방지.</td></tr>
<tr><td>내부 ID</td><td>ID 조회 3개 경로, 행동 이력 ID·관측 참조, 영구 예약 시퀀스. 표시 그룹·합성 바코드로 ID 재사용 금지.</td></tr>
<tr><td>카테고리</td><td>복수 분류 유지, 미분류 배타 처리. 알려진 소비 용도 불일치 제외, 불확실은 별도 UNKNOWN.</td></tr></table>
<h2>2. 검증</h2><ul><li>Gradle 전체 {counts['tests']}개: 성공 {counts['passed']}개, 실패 0개, 건너뜀 {counts['skipped']}개(외부 데이터/opt-in).</li>
<li>격리 localhost HTTP {len(http)}회 기대 상태 일치.</li><li>MySQL {escape(mysql['mysql_version'])} 별도 임시 스키마 2개: 신규 ID/기존 AUTO_INCREMENT, 교체·롤백 검증. 임시 스키마 제거 완료.</li>
<li>고정 추천 1,270회 별도 재생. 기존 20개 결과 모드 20/20, Hit@10 13/13, NDCG@10 0.870583 유지.</li></ul>
<h2>3. 확대 조건 1,050개 비교</h2><table><tr><th>결과 모드</th><th>전</th><th>후</th></tr>{modes}</table>
<p>알려진 용도 불일치 제외 {summary['category_mismatch_exposures']:,}회, 용도 미확정 관찰 {summary['category_unknown_exposures']:,}회. 서로 다른 상품 수가 아니라 반복된 후보-사용자 조건의 횟수다.</p>
<p>DANGER/필수 식단 MISMATCH 반환은 전후 모두 0건이다. 독립 정규식의 메밀가루/밀가루 라벨 경고 2건은 양쪽에 동일하게 남으며, 기존 UNJUDGED 검수 이력을 보존한다. 이 결과로 실제 안전성이나 전체 정확도를 보장할 수 없다.</p>
<h2>4. 대표 사례와 남은 실패</h2>{examples}
<p class="note">아이스크림→어묵, 초고추장→장아찌는 차단됐다. 하지만 만두→유형 미상의 가슴살, 아이스크림→분류 근거 부족 상품과 King Bowl 사례는 남아 있다. UNKNOWN을 억지로 확정하지 않았기 때문이다. 다음 작업은 용도 근거·정답 보강이며 위험 조건 완화가 아니다.</p>
<h2>5. 실제 적용 전 필요한 작업</h2><p>백업 → 복제 스테이징 V14/V15 검증 → ID 유일 인덱스 점검 → ID 배치 백필 → 현재 속성 baseline 수집 → 무결성 검증 → 승인된 적재/배포 순서다. 원본/운영 적용은 별도 승인 후 진행한다.</p>
<p>전체 상품 적재 성능, 프론트·AI 전환, 완전한 옵션/리뉴얼 모델은 미검증/후속 범위다. 검색 알고리즘은 이번에 변경하지 않았다. 점수 가중치와 평가 정답도 그대로 유지했다.</p>
<p>상세 값·입력 해시: <a href="comparison.json">comparison.json</a> · MySQL 검증: <a href="mysql-migration-test.json">mysql-migration-test.json</a></p></html>"""
    args.output.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    targets[1].write_text(document, encoding="utf-8")
    print(json.dumps({"tests": dict(counts), "http_checks": len(http), "modes": summary["modes_after"], "report": str(targets[1])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
