"""Compare two saved runs without changing the frozen labels or accessing any database."""
import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def select_run(document, policy):
    runs = [r for r in document["product_recommendation_evaluation_runs"] if r["policy_version"] == policy]
    if len(runs) != 1:
        raise ValueError(f"Expected exactly one saved run for {policy}, found {len(runs)}")
    run = runs[0]
    rows = [r for r in document["product_recommendation_evaluation_results"]
            if r["evaluation_run_id"] == run["evaluation_run_id"]]
    if len(rows) != len({r["case_id"] for r in rows}):
        raise ValueError("Duplicate case rows")
    return run, {r["case_id"]: r for r in rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--rerun", default="retest-v5.1")
    parser.add_argument("--test-results", type=Path, required=True)
    args = parser.parse_args()
    root, target = args.directory, args.directory / args.rerun
    manifest = load(root / "benchmark-frozen.json")
    evidence = load(root / "product-evidence.json")
    proof = load(target / "input-verification.json")
    for field, filename in (("manifest_sha256", "benchmark-frozen.json"),
                            ("evidence_sha256", "product-evidence.json")):
        if hashlib.sha256((root / filename).read_bytes()).hexdigest() != proof[field]:
            raise ValueError(f"Frozen input changed: {filename}")
    if proof["manifest_sha256"] != load(root / "seed-result.json")["manifest_sha256"]:
        raise ValueError("Baseline and rerun do not use the same manifest")
    old, before = select_run(load(root / "evaluation-results.json"), "unified-hard-constraints-evidence-v5")
    new, after = select_run(load(target / "evaluation-results.json"), "unified-hard-constraints-evidence-v5.1")
    ids = {c["case_id"] for c in manifest["cases"]}
    if set(before) != ids or set(after) != ids or proof["cases_verified"] != len(ids):
        raise ValueError("Case sets differ")
    initial = load(root / "inspection-after.json")
    final = load(target / "inspection-after.json")
    if initial["server"] != final["server"] or final["server"] != proof["server"]:
        raise ValueError("Database server identity differs")
    for table in ("products", "product_neighbor_sets", "users", "histories", "email_verifications"):
        if initial["counts"][table] != final["counts"][table]:
            raise ValueError(f"Unexpected row-count difference: {table}")
    products = {p["barcode"]: p for p in evidence["candidates"]}
    tests = dict(tests=0, failures=0, errors=0, skipped=0)
    test_files = list(args.test_results.glob("TEST-*.xml"))
    if not test_files:
        raise ValueError("Gradle test results missing")
    for path in test_files:
        suite = ET.parse(path).getroot()
        for key in tests:
            tests[key] += int(suite.attrib.get(key, 0))

    def totals(rows):
        return {
            "returned": sum(r["result_count"] for r in rows.values()),
            "violations": sum(r["hard_constraint_violations"] for r in rows.values()),
            "outcome_matches": sum(r["outcome_matched"] for r in rows.values()),
            "empty": sum(r["empty_response"] for r in rows.values()),
            "max_latency_ms": max(r["latency_micros"] for r in rows.values()) / 1000,
        }

    a, b = totals(before), totals(after)
    summary = {"baseline_run": old, "rerun": new, "baseline_totals": a, "rerun_totals": b,
               "input_verification": proof, "tests": tests, "cases": []}
    table_rows = []

    def items(row):
        return list(filter(None, (row["result_barcodes"] or "").split(",")))

    def details(row, case):
        entries = []
        for barcode in items(row):
            p = products[barcode]
            forbidden = barcode in case["forbidden_barcodes"]
            prefix = "[제외 대상] " if forbidden else ""
            entries.append(f"<li>{escape(prefix + p['product_name'])} · <code>{escape(barcode)}</code>"
                           f"<br>원재료: {escape(p['raw_materials'] or '결측')}</li>")
        return "<ol>" + "".join(entries) + "</ol>" if entries else "<p>반환 상품 없음</p>"

    for case in manifest["cases"]:
        x, y = before[case["case_id"]], after[case["case_id"]]
        if x["expected_outcome"] != case["expected_outcome"] or y["expected_outcome"] != case["expected_outcome"]:
            raise ValueError("Expected outcomes differ")
        for row in (x, y):
            if sum(v in case["forbidden_barcodes"] for v in items(row)) != row["hard_constraint_violations"]:
                raise ValueError("Forbidden-item count differs")
        changed = any(x[k] != y[k] for k in ("result_mode", "result_barcodes", "outcome_matched", "hard_constraint_violations"))
        summary["cases"].append({"case_id": case["case_id"], "changed": changed, "before": x, "after": y})
        table_rows.append(
            f"<tr class={'changed' if changed else 'unchanged'}><td>{escape(case['case_id'].removeprefix('local-pilot-20261023-'))}"
            f"<br>{escape(case['reference_name'])}<br><small>{escape(case['profile'])}</small></td>"
            f"<td>{case['expected_outcome']}</td><td>{x['result_mode']}<br>{x['result_count']}개 · 위반 {x['hard_constraint_violations']}"
            f"</td><td>{y['result_mode']}<br>{y['result_count']}개 · 위반 {y['hard_constraint_violations']}</td>"
            f"<td>{'일치' if x['outcome_matched'] else '불일치'} → {'일치' if y['outcome_matched'] else '불일치'}</td></tr>"
            f"<tr><td colspan=5><details><summary>고정 정답 근거와 전후 반환 상품</summary>"
            f"<p>{escape(case['judgment_reason'])}</p><div class=columns><section><h4>수정 전</h4>{details(x, case)}</section>"
            f"<section><h4>수정 후</h4>{details(y, case)}</section></div></details></td></tr>"
        )
    metrics = [
        ("기대 동작 일치", f"{a['outcome_matches']}/20 · {old['outcome_match_rate']:.0%}",
         f"{b['outcome_matches']}/20 · {new['outcome_match_rate']:.0%}", "모드·금지 상품·표시 계약을 포함한 사례별 판정"),
        ("하드 제약 위반", f"{a['violations']}/{a['returned']} · {old['hard_constraint_violation_rate']:.2%}",
         f"{b['violations']}/{b['returned']} · {new['hard_constraint_violation_rate']:.2%}", "일반/확인용/완화 후보 반환 모두 포함. 목표 0회"),
        ("Hit@10", f"12/13 · {old['hit_rate_at_k']:.2%}", f"13/13 · {new['hit_rate_at_k']:.2%}",
         "정상 추천 예상 사례에서 정답을 한 개 이상 반환한 비율. 개별 상품 정확도가 아님"),
        ("MRR", f"{old['mean_reciprocal_rank']:.4f}", f"{new['mean_reciprocal_rank']:.4f}", "첫 관련 상품 순위의 역수 평균"),
        ("NDCG@10", f"{old['ndcg_at_k']:.4f}", f"{new['ndcg_at_k']:.4f}", "고정된 부분 관련성 정답으로 측정한 순위 품질"),
        ("올바른 추천 보류", f"1/3 · {old['correct_abstention_rate']:.2%}", f"3/3 · {new['correct_abstention_rate']:.0%}", "위험 후보만 남은 경우 억지로 반환하지 않음"),
        ("추가 확인 사례 적합", f"4/4 · {old['verification_fallback_hit_rate']:.0%}", f"4/4 · {new['verification_fallback_hit_rate']:.0%}", "확인 필요 채널·경고·정답 유지"),
        ("전체 빈 응답", f"{a['empty']}/20 · {old['empty_response_rate']:.0%}", f"{b['empty']}/20 · {new['empty_response_rate']:.0%}", "보류 정답 3개에 맞아 증가함. 장애나 회귀가 아님"),
        ("예상 밖 빈 응답 / 표시 계약 위반", f"{old['unexpected_empty_response_rate']:.0%} / {old['presentation_violation_count']}회", f"{new['unexpected_empty_response_rate']:.0%} / {new['presentation_violation_count']}회", "추천 가능 사례 누락 및 경고 없이 UNKNOWN 표시 등을 검사"),
        ("서비스 P95", f"{old['p95_latency_micros']/1000:.3f} ms", f"{new['p95_latency_micros']/1000:.3f} ms", "20회 단일 순차 측정. HTTP/네트워크 제외; 성능 개선의 통계적 근거가 아님"),
        ("서비스 평균 / 최대", f"{old['average_latency_micros']/1000:.3f} / {a['max_latency_ms']:.3f} ms", f"{new['average_latency_micros']/1000:.3f} / {b['max_latency_ms']:.3f} ms", "JVM 초기화·DB 캐시 영향 포함"),
        ("품질 게이트", "통과" if old['passed'] else "실패", "통과" if new['passed'] else "실패", "임계값/가중치를 변경하지 않고 비교"),
    ]
    metric_html = "".join("<tr>" + "".join(f"<td>{escape(v)}</td>" for v in row) + "</tr>" for row in metrics)
    passed = tests['tests'] - tests['skipped'] - tests['failures'] - tests['errors']
    document = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>추천 오류 수정 전후 비교 · v5 → v5.1</title>
<style>body{{font:16px/1.65 system-ui,sans-serif;background:#f2f5f8;color:#172238;margin:0}}main{{max-width:1300px;margin:24px auto;padding:32px;background:white;border-radius:12px}}h1,h2{{line-height:1.3}}table{{width:100%;border-collapse:collapse;margin:18px 0}}th,td{{border:1px solid #dae2eb;padding:10px;vertical-align:top;text-align:left}}th{{background:#eef3f8}}.notice{{background:#e9f6ee;border-left:5px solid #237947;padding:18px}}.warning{{background:#fff7e6;padding:16px}}.changed{{background:#edf8f1}}code,small{{font-size:.85em;overflow-wrap:anywhere}}details{{font-size:14px}}li{{margin:9px 0}}.columns{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}.muted{{color:#5f6c7d}}@media(max-width:800px){{main{{padding:16px;margin:0}}.columns{{display:block}}.scroll{{overflow-x:auto}}}}a{{color:#185c9c}}</style></head><body><main>
<h1>추천 오류 수정 전후 비교</h1><p>2026-10-23 · v5 실행 {old['evaluation_run_id']} → v5.1 실행 {new['evaluation_run_id']} · 로컬 MySQL 전용</p>
<div class=notice><strong>기대 동작 17/20 → 20/20, 제약 위반 3/118 → 0/116.</strong><br>발견한 대두 누락과 비건 원재료 충돌을 수정했다. 평가 정답·상품·후보·사용자 조건은 유지했다. 운영 DB는 접근·수정하지 않았다.</div>
<h2>1. 변경 내용</h2><ul>
<li><strong>대두:</strong> 검정콩·검은콩·서리태·서목태·흑태·백태·메주콩을 SOY 탐지 근거에 추가했다. 모든 ‘콩’을 부분 일치시키지 않으며 땅콩·완두콩·병아리콩 등의 오탐을 회귀 테스트로 방지했다.</li>
<li><strong>비건:</strong> 젓갈·액젓·육류·유제품·계란 등 명시적 동물성 원재료를 저장 Boolean·출처·신뢰도보다 우선 검사한다. 충돌 시 <code>NOT_MET / EXPLICIT_INGREDIENT_CONFLICT</code>이며 홈·대체·확인용 후보에서 모두 제외한다.</li>
<li>코코아버터·땅콩버터 등은 동명 성분 오탐을 방지한다. 향·무첨가·식물성 대체 표현처럼 모호한 경우 <code>UNKNOWN / AMBIGUOUS_INGREDIENT_EVIDENCE</code>으로 보류한다. 공장 공동 사용 경고를 비건의 실제 원재료로 간주하지 않는다.</li>
<li>판정 응답에 <code>ingredientEvidence</code> 배열을 추가하고 정책 버전을 v5.1로 변경했다. 상품의 원래 <code>is_vegan</code> 및 원재료는 변경하지 않았다. 클라이언트는 저장 Boolean보다 <code>dietConstraints.attributes[].status</code>를 사용해야 한다.</li></ul>
<h2>2. 동일 조건 확인</h2><p>기존 고정 20개 사례(추천 13 / 확인 필요 4 / 보류 3), 기준 상품 10종, 고유 후보 963개 및 기존 TOP100 후보를 재사용했다. DB에서 현재 상품 필드·후보 세트·가상 사용자 조건·기대 정답을 고정 파일과 대조한 후 실행했다. 개인 이력이 없는 프로필, K=10, 최소 유사도 0.2와 품질 게이트는 그대로이다.</p>
<p>로컬 상품 {final['counts']['products']:,}건·후보 세트 {final['counts']['product_neighbor_sets']:,}건 유지. 이번 재평가는 로컬 평가 실행 1개와 사례별 결과 20개만 추가했으며, 기존 평가 결과와 V13 스키마를 유지했다.</p>
<p class=muted>평가셋 SHA-256: <code>{proof['manifest_sha256']}</code><br>상품 근거 SHA-256: <code>{proof['evidence_sha256']}</code></p>
<h2>3. 결과 비교</h2><div class=scroll><table><thead><tr><th>지표</th><th>수정 전 v5</th><th>수정 후 v5.1</th><th>해석</th></tr></thead><tbody>{metric_html}</tbody></table></div>
<h2>4. 실제로 달라진 세 사례</h2><ul>
<li><strong>대두 단독 및 복수 알레르기:</strong> <code>8809546050393</code> ‘검은콩 호두 아몬드 율무차’의 <code>검정콩분말</code>이 탐지된다. 이전 확인용 후보 1개가 제외되고 두 사례 모두 <code>ACTION_REQUIRED</code>로 바뀌었다. 해당 후보 100개가 모두 제한 대상이므로 보류가 정답이다.</li>
<li><strong>비건 김치:</strong> <code>8809579000297</code> ‘열무김치’의 <code>젓갈</code> 때문에 비건 저장값 true라도 제외된다. 대신 <code>8809225710501</code> ‘손맛순무물김치’가 <code>RELAXED_SAFE</code>로 반환됐다. 이는 유사도 조건을 완화한 후보이며 알레르기·식단 필수 조건을 완화했다는 의미가 아니다.</li></ul>
<h2>5. 테스트와 해석 한계</h2><ul>
<li>Gradle 테스트 {tests['tests']}개 중 {passed}개 통과, 실패 {tests['failures']}개·오류 {tests['errors']}개·선택적 대용량 CSV 테스트 {tests['skipped']}개 건너뜀. bootJar 빌드 성공. 이번 수정에 회귀 테스트 9개를 추가했다.</li>
<li>두 추천 서비스의 제외 정책은 H2 통합 테스트로 함께 검증했다. 실제 MySQL 평가 20건은 대체 추천 서비스 실행이며 HTTP/JWT·홈 페이지 전체 탐색·개인 이력 순위·동시 부하는 별도 검증 대상이다.</li>
<li>AI 보조 검수 기반 소규모 파일럿이며 전문가 gold set 또는 무작위 대표 표본이 아니다. Hit@10 100%는 모든 반환 상품이 실제로 안전하거나 정확하다는 의미가 아니다. 관련성 정답은 부분 판정이며 일부 사례는 저장 분류 계약을 검증한다.</li>
<li>명시적 비건 충돌 검사는 제한된 한국어 성분 사전이다. 미탐지=비건 인증이 아니며 누락·동의어·다국어·다른 5개 채식 유형의 원재료 모순은 추가 확장/검수가 필요하다. DB 원본 분류의 전수 정정은 하지 않았다.</li></ul>
<h2>6. 전체 20개 사례</h2><p>초록색은 반환 결과가 바뀐 사례이다. 각 행 아래에서 전후 실제 상품과 고정 정답 근거를 펼칠 수 있다.</p><div class=scroll><table><thead><tr><th>사례 / 기준 상품</th><th>기대 결과</th><th>수정 전</th><th>수정 후</th><th>동작 판정</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table></div>
<h2>7. 재현 자료</h2><ul><li><a href="../evaluation-report.html">수정 전 기준 보고서(보존)</a></li><li><a href="../benchmark-frozen.json">동일 고정 평가셋</a> / <a href="../product-evidence.json">상품·후보 근거</a></li><li><a href="input-verification.json">동일 입력 검증 결과</a></li><li><a href="evaluation-results.json">전후 실행 및 사례별 DB 결과</a> / <a href="evaluation-events.json">이번 실행 제외 사유·반환 채널 로그</a></li><li><a href="comparison.json">비교 결과 JSON</a> / <a href="inspection-after.json">로컬 DB 확인</a></li></ul>
<p class=muted>Git 커밋·push 및 운영 배포는 하지 않았다.</p></main></body></html>"""
    (target / "comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report = target / "comparison-report.html"
    report.write_text(document, encoding="utf-8")
    print(json.dumps({"report": str(report), "changed_cases": sum(c['changed'] for c in summary['cases']),
                      "tests": tests, "before": a, "after": b}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
