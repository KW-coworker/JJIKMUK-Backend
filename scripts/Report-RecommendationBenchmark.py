"""Render the saved local benchmark evidence as a self-contained, offline HTML report."""
import argparse
from html import escape
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory
    def load(name):
        return json.loads((root / name).read_text(encoding="utf-8"))
    manifest = load("benchmark-frozen.json")
    evidence = load("product-evidence.json")
    results = load("evaluation-results.json")
    inspection = load("inspection-after.json")
    events = load("evaluation-events.json")
    run = results["product_recommendation_evaluation_runs"][-1]
    rows = {r["case_id"]: r for r in results["product_recommendation_evaluation_results"]
        if r["evaluation_run_id"] == run["evaluation_run_id"]}
    products = {p["barcode"]: p for p in evidence["candidates"]}
    seed = load("seed-result.json")
    profiles = {u["email"].removeprefix("local-benchmark-20261023-").removesuffix("@example.invalid"): u["id"]
        for u in seed["synthetic_users"]}
    by_request = {(e["userId"], e["referenceBarcode"]): e for e in events}
    total_items = sum(r["result_count"] for r in rows.values())
    violations = sum(r["hard_constraint_violations"] for r in rows.values())
    max_latency = max(r["latency_micros"] for r in rows.values()) / 1000
    checks = []
    table = []
    for case in manifest["cases"]:
        r = rows[case["case_id"]]
        event = by_request[(profiles[case["profile"]], case["reference_barcode"])]
        main_count = r["result_count"] - r["fallback_result_count"]
        verdict = "통과" if r["outcome_matched"] else "실패"
        item_details = []
        for b in filter(None, r["result_barcodes"].split(',')):
            p = products[b]
            is_forbidden = b in case["forbidden_barcodes"]
            checks.append({"case_id": case["case_id"], "barcode": b, "forbidden": is_forbidden})
            flag = "[제외 대상 반환] " if is_forbidden else ""
            item_details.append(f"<li>{escape(flag+p['product_name'])} <code>{escape(b)}</code><br>"
                f"원재료: {escape(p['raw_materials'] or '정보 없음')}<br>"
                f"알레르기 근거: {escape(p['allergy_evidence_level'])}; 비건 저장값: {p['is_vegan']}; "
                f"식단 출처: {escape(p['dietary_data_origin'])}</li>")
        details = (f"<details><summary>근거 및 반환 상품 {r['result_count']}개</summary>"
            f"<p>{escape(case['judgment_reason'])}</p><pre>{escape(json.dumps(event['exclusions'], ensure_ascii=False, indent=2))}</pre>"
            f"<ol>{''.join(item_details)}</ol></details>")
        table.append(f"<tr class={'ok' if r['outcome_matched'] else 'fail'}><td>{escape(case['case_id'].removeprefix('local-pilot-20261023-'))}"
            f"<br>{escape(case['reference_name'])}<br><code>{case['reference_barcode']}</code></td>"
            f"<td>{escape(case['profile'])}</td><td>{case['expected_outcome']}</td><td>{r['result_mode']}</td>"
            f"<td>{main_count} / {r['fallback_result_count']}</td><td>{verdict}<br>위반 {r['hard_constraint_violations']}회</td></tr>"
            f"<tr><td colspan=6>{details}</td></tr>")
    assert len(rows) == len(manifest["cases"]) == 20
    assert violations == sum(c["forbidden"] for c in checks)
    body = f"""<!doctype html><html lang="ko"><meta charset="utf-8"><title>로컬 추천 평가 결과 · 2026-10-23</title>
<style>body{{font:16px/1.65 system-ui,sans-serif;color:#172033;background:#f5f7fa;margin:0}}main{{max-width:1250px;margin:30px auto;background:white;padding:36px;border-radius:12px}}h1,h2{{line-height:1.3}}table{{width:100%;border-collapse:collapse;margin:16px 0}}th,td{{text-align:left;border:1px solid #dbe1eb;padding:10px;vertical-align:top}}th{{background:#edf1f7}}code{{font-size:.85em;overflow-wrap:anywhere}}.fail{{background:#fff0ed}}.ok{{background:#f4fbf6}}.warning{{border-left:5px solid #bc3523;background:#fff0ed;padding:18px}}li{{margin:10px 0}}details{{font-size:14px}}pre{{background:#f5f7fa;padding:10px}}.muted{{color:#5c6677}}</style><main>
<h1>V13 로컬 적용 및 실제 상품 추천 평가</h1><p>2026-10-23 · 실행 ID {run['evaluation_run_id']} · 정책 <code>{run['policy_version']}</code></p>
<p class="warning"><strong>평가 실행 완료 / 품질 게이트 실패.</strong> 제외해야 하는 상품이 3회(서로 다른 상품 2종) 반환됐다. 랭킹 지표가 높아도 안전 조건 실패를 상쇄할 수 없다. 운영 DB 수정·접속, 정책 자동 완화, 평가 정답 사후 변경은 하지 않았다.</p>
<h2>1. 적용 범위</h2><ul><li>대상: 이 PC의 MySQL 8.0.44, 127.0.0.1:3306/jjikmuk. 호스트와 서버 UUID를 실행 전에 대조했다.</li>
<li>관련 6개 테이블 백업 후 Flyway V9 → V10 → V11 → V12 → V13 적용 성공. 첫 검증 시도는 pending 오류로 DB 변경 전 중단됐고, migrate의 기본 검증 절차로 재실행했다.</li>
<li>상품 {inspection['counts']['products']:,}건, 이웃 후보 세트 {inspection['counts']['product_neighbor_sets']:,}건 유지. 상품·원재료·이미지 URL·추천 후보를 변경하지 않았다.</li>
<li>기존 사용자 3명 유지. 재현용 가상 프로필 7개(ID 5~11), 평가 사례 20개, 평가 실행 1개 및 사례별 결과 20개 추가. 가상 계정은 example.invalid 이메일과 로그인 불가용 비밀번호를 사용했다.</li>
<li>백업: <code>backup/pre-migration-private-backup.sql</code> — 전체 상품 DB 덤프가 아닌 변경 대상 테이블 백업. 계정 정보가 포함되어 Windows 사용자/관리자/SYSTEM으로 접근을 제한했다. Git 업로드 금지.</li></ul>
<h2>2. 평가셋과 측정 방식</h2><p>상품 10종 × 조건 조합 20개. 정상 추천 예상 13개, 추가 확인 예상 4개, 추천 보류 예상 3개. 사용자 이력이 없는 가상 프로필을 사용하고, 실제 DB 상품 및 기존 TOP100 후보를 조회했다. K=10, 최소 유사도 0.2이며 정답을 실행 전에 고정했다.</p>
<p class="muted">전문가가 검수한 의료적 gold set이나 전체 상품 대표 표본이 아니다. 원재료·출처·분류의 사실 정확도까지 보장하는 지표로 해석하면 안 된다. 식단 일부 사례는 기존 저장 분류 계약을 점검한다. 관련성 정답은 부분 판정이다.</p>
<table><tr><th>지표</th><th>측정값</th><th>해석</th></tr>
<tr><td>기대 동작 일치</td><td>17/20 · {run['outcome_match_rate']:.1%}</td><td>모드·금지 상품·표시 계약 포함. 목표 100%에 미달.</td></tr>
<tr><td>Hit@10</td><td>12/13 · {run['hit_rate_at_k']:.2%}</td><td>정상 추천 예상 사례에서 검토 정답이 한 개 이상 포함된 비율. 전체 반환 상품 정확도가 아님.</td></tr>
<tr><td>NDCG@10</td><td>{run['ndcg_at_k']:.4f}</td><td>부분 관련성 정답 기준 순위 품질, 0~1 척도.</td></tr>
<tr><td>하드 제약 위반</td><td>{violations}/{total_items}회 · {run['hard_constraint_violation_rate']:.2%}</td><td>일반 추천과 확인용 후보 모두 포함. 허용 기준 0회.</td></tr>
<tr><td>올바른 추천 보류</td><td>1/3 · {run['correct_abstention_rate']:.2%}</td><td>대두 제한 2개 사례에서 후보가 잘못 살아남음.</td></tr>
<tr><td>추가 확인 사례 적합</td><td>4/4 · {run['verification_fallback_hit_rate']:.0%}</td><td>기대한 모드와 관련 확인용 후보가 반환됨.</td></tr>
<tr><td>예상치 못한 빈 결과 / 표시 계약 위반</td><td>0 / 0</td><td>금지 성분 탐지의 정확성을 보장한다는 의미는 아님.</td></tr>
<tr><td>응답 서비스 실행 시간</td><td>평균 {run['average_latency_micros']/1000:.1f} ms / P95 {run['p95_latency_micros']/1000:.1f} ms / 최대 {max_latency:.1f} ms</td><td>20회 단일 순차 실행. DB/JPA 호출 포함, HTTP·직렬화·네트워크 제외. 부하 테스트나 SLA가 아님.</td></tr></table>
<h2>3. 확인된 문제와 다음 수정 대상</h2><ol>
<li><strong>대두 동의어 누락.</strong> <code>8809546050393</code> ‘검은콩 호두 아몬드 율무차’의 원재료에는 ‘검정콩분말’이 있다. 하지만 SOY 키워드 목록에 검정콩/검은콩이 없고, 짧은 ‘콩’은 단어 경계 규칙을 적용하므로 DANGER가 아닌 UNKNOWN이 된다. 대두 단독·복수 알레르기 2개 사례에서 <code>fallbackItems</code>로 반환됐다. 안심 상품으로 표시되지는 않았지만 명시적 충돌 상품은 확인용에서도 제외해야 한다.</li>
<li><strong>식단 저장값과 원재료의 충돌.</strong> <code>8809579000297</code> ‘열무김치’는 원재료에 ‘젓갈’이 있지만 <code>is_vegan=true</code>, 출처 INFERRED, 신뢰도 0.7이다. 현재 정책은 출처/신뢰도/원재료 존재를 검사한 뒤 Boolean을 신뢰하며, 원재료와의 모순을 검사하지 않는다. 비건 사용자에게 일반 추천으로 반환됐다. 저장값보다 명시적 반대 근거를 우선하는 판정과 데이터 정정이 필요하다.</li>
<li><strong>후보 생성 품질.</strong> 신라면 후보에 김·커피 등 사용 용도가 다른 상품이 있다. 이번 제한 없는 신라면 요청은 유사도 0.2 미달 99건을 제외해 실제로는 SHIN RAMYUN 1건만 반환했다. 후보 오염과 최종 결과 오염은 구별해야 하며, 후보를 늘릴 때 카테고리/사용 용도 검증이 필요하다.</li></ol>
<h2>4. 이번에 확인된 정상 동작</h2><p>누룽지+저당 사례에서는 100개 후보 중 근거가 있는 충족 상품 50개, 명시적 불충족 4개, 영양 근거 부족 UNKNOWN 46개로 분리됐다. UNKNOWN 46개는 일반 추천에 들어가지 않았고 충족 상품 10개를 반환했다. 포키+저당 사례는 100개 모두 불충족이어서 정상적으로 추천 보류했다. 다만 이 결과는 저장된 영양 분류와 출처가 사실인지까지 검증한 것은 아니다.</p>
<h2>5. 사례별 결과</h2><p>상품 수는 ‘일반 추천 / 확인·완화 후보’이다. 아래 근거를 펼치면 실제 반환 상품과 원재료를 볼 수 있다.</p>
<table><thead><tr><th>사례 / 기준 상품</th><th>프로필</th><th>예상</th><th>실제 모드</th><th>상품 수</th><th>판정</th></tr></thead><tbody>{''.join(table)}</tbody></table>
<h2>6. 테스트 및 한계</h2><ul><li>Gradle 테스트 재실행: 116개 중 112개 통과, 실패·오류 0개, 대용량 CSV 선택 테스트 4개 제외. 단위 테스트 통과와 실제 데이터 품질 게이트 통과는 별개다.</li>
<li>이번 작업은 대체 추천 서비스 평가이며 홈 맞춤 추천 API, JWT/HTTP 경로, 개인 이력 기반 선호 순위, 가족 프로필 API, 다중 동시접속은 평가하지 않았다.</li>
<li>독립 전문가/두 번째 검수자 확인 및 다양한 상품군 확장 후 최종 성능을 다시 측정해야 한다.</li></ul>
<h2>7. 재현 자료</h2><ul><li><a href="benchmark-frozen.json">고정 평가셋</a></li><li><a href="product-evidence.json">평가에 사용한 상품/후보 원본 조회 결과</a></li><li><a href="evaluation-results.json">DB 평가 지표·사례 결과</a></li><li><a href="evaluation-events.json">반환 채널·제외 사유·소요 시간</a></li><li><a href="inspection-after.json">마이그레이션 및 행 수 확인</a></li></ul>
<p class="muted">평가셋 SHA-256: {seed['manifest_sha256']}<br>수정 작업은 로컬 범위이며 운영 반영·Git 커밋·push는 수행하지 않았다.</p></main></html>"""
    output = root / "evaluation-report.html"
    output.write_text(body, encoding="utf-8")
    print(json.dumps({"report": str(output), "cases": len(rows), "items": total_items, "violations": violations}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
