"""Real 1.1 reconciliation dispatch for the exact, source-reviewed NAVER cases."""

import json
from datetime import date
from hashlib import sha256

from proofops.domain.reconciliation.engine import evaluate

from evaluation.local_review import REVIEW_SHA256, ROOT, digest, load_review


def compare_reviewed(claim, report):
    review = load_review()
    if not review or claim.get("review", {}).get("record_sha256") != REVIEW_SHA256:
        return None
    config = report.get("config", {})
    if report.get("status") != "retrieved" or (
        config.get("corp_code"),
        config.get("year"),
        config.get("rcept_no"),
    ) != ("00266961", "2024", "20250318000645"):
        return None
    raw_path = ROOT / ".local/dart-web" / report["source_sha256"] / "statements.json"
    raw = raw_path.read_bytes()
    if sha256(raw).hexdigest() != report["source_sha256"]:
        raise ValueError("DART_ARTIFACT_INTEGRITY_MISMATCH")
    data = json.loads(raw)
    rows = data.get("list", [])
    if not rows or any(
        r.get("corp_code") != "00266961"
        or r.get("bsns_year") != "2024"
        or r.get("rcept_no") != "20250318000645"
        for r in rows
    ):
        raise ValueError("DART_SOURCE_IDENTITY_MISMATCH")
    claim_id = claim["review"]["candidate_sha256"]
    index = review["claims"][claim_id]["index"]
    # Facility-specific p100 and the pair of data centers p105 are narrower than
    # a complete separate or consolidated financial statement entity boundary.
    facility_scope = index <= 20 or index == 23
    checks = []
    packets = []
    for item in ("C1", "C2", "C3", "C4"):
        if item in ("C3", "C4"):
            checks.append(
                dict(
                    item=item,
                    status="not_applicable",
                    reason="검토한 주장은 통화 금액 투자 약정이 아님"
                    if item == "C3"
                    else "환경 수량·전력 비율·공시 범위 목표이며 분류 매출 비중 실적이 아님",
                    engine_result=dict(
                        execution_state="not_run",
                        status="not_applicable",
                        reason_codes=["reviewed_trigger_not_applicable"],
                        dispatcher="source-reviewed-1",
                        review_sha256=REVIEW_SHA256,
                    ),
                )
            )
            continue
        applicable = not (
            item in ("C3", "C4")
            or (item == "C2" and claim["track"] == "goal")
            or (item == "C1" and facility_scope)
        )
        packet = dict(
            schema_version="1.1",
            synthetic=False,
            identity=dict(
                tenant_id=review["rulepack"]["tenant_id"],
                company_id="NAVER-00266961",
                claim_id=claim_id,
                package_id=REVIEW_SHA256,
                period_start=None,
                period_end=None,
                sustainability_document_version=review["identity"]["document_version_id"],
                financial_document_version=report["source_sha256"],
                dart_corp_code=config["corp_code"],
                financial_fiscal_year=2024,
                consolidation="separate" if config["fs_div"] == "OFS" else "consolidated",
                financial_period_start=None,
                financial_period_end=None,
                sr_published_at=None,
                financial_published_at="2025-03-18",
                rcept_no=config["rcept_no"],
                as_of_date=date.today().isoformat(),
            ),
            item=item,
            sources=[
                dict(
                    source_id="sr-claim",
                    document_id=review["identity"]["document_version_id"],
                    artifact_sha256=review["source_sha256"],
                    locator=f"physical_page={claim['page']};source={claim['parser_source']['key']}",
                    quote=claim["quote"],
                ),
                dict(
                    source_id="dart-statements",
                    document_id=report["source_sha256"],
                    artifact_sha256=report["source_sha256"],
                    locator="JSON list; request fs_div=" + config["fs_div"],
                    quote=json.dumps(rows[0], ensure_ascii=False),
                ),
            ],
            sustainability=dict(
                raw=claim["quote"], normalized=None, kind="unknown", unit=None, source_id="sr-claim"
            ),
            financial=dict(
                raw="NAVER FY2024 " + config["fs_div"],
                normalized=None,
                kind="unknown",
                unit=None,
                source_id="dart-statements",
            ),
            comparability="unknown" if applicable else "not_comparable",
            explanation=dict(source_id=None, search_complete=False),
            c3_context=None,
            c4_context=None,
            claim=dict(
                track=claim["track"],
                quote=claim["quote"],
                source_id="sr-claim",
                trigger_elements=[],
                fiscal_year=2024,
            ),
            search=dict(
                state="incomplete",
                coverage_policy_id=review["reconciliation_policy"]["coverage_policy_id"],
                required_document_ids=[
                    review["identity"]["document_version_id"],
                    report["source_sha256"],
                ],
                reviewed_source_ids=["sr-claim", "dart-statements"],
                failed_document_ids=[],
                receipt_id=None,
            ),
        )
        period = review.get("period_review")
        period_bound = item == "C2" and period and index in period["claim_indices"]
        if period_bound:
            period_raw = (ROOT / period["financial_artifact"]).read_bytes()
            if sha256(period_raw).hexdigest() != period["financial_sha256"]:
                raise ValueError("DART_PERIOD_ARTIFACT_INTEGRITY_MISMATCH")
            packet["identity"].update(
                period_start=period["start"],
                period_end=period["end"],
                financial_period_start=period["start"],
                financial_period_end=period["end"],
            )
            packet["sources"].extend(
                [
                    dict(
                        source_id="sr-period",
                        document_id=review["identity"]["document_version_id"],
                        artifact_sha256=review["source_sha256"],
                        locator="physical_page=213; reduction assurance",
                        quote=period["sr_quote"],
                    ),
                    dict(
                        source_id="dart-period",
                        document_id=period["financial_sha256"],
                        artifact_sha256=period["financial_sha256"],
                        locator=period["financial_url"],
                        quote=period["financial_quote"],
                    ),
                ]
            )
            normalized_period = period["start"] + "/" + period["end"]
            packet["sustainability"] = dict(
                raw=period["sr_quote"],
                normalized=normalized_period,
                kind="period",
                unit="date",
                source_id="sr-period",
            )
            packet["financial"] = dict(
                raw=period["financial_quote"],
                normalized=normalized_period,
                kind="period",
                unit="date",
                source_id="dart-period",
            )
            packet["comparability"] = "comparable"
        result = evaluate(packet, review["reconciliation_policy"])
        reason = {
            "C1": "시설·데이터센터 범위는 전체 재무제표 범위와 직접 비교 불가"
            if facility_scope
            else "법인 집합과 정확한 기간의 원문 연결 미완료",
            "C2": "미래 목표를 2024년 실적과 불일치로 판단하지 않음"
            if claim["track"] == "goal"
            else "연도는 확인했으나 양쪽 시작·종료일 원문 연결 미완료",
            "C3": "검토한 주장은 통화 금액 투자 약정이 아님",
            "C4": "환경 수량·전력 비율·공시 대상 범위 목표이며 분류 매출 비중 실적이 아님",
        }[item]
        if period_bound:
            reason = "213쪽 감축사업 기간과 DART 사업보고서 표지의 시작·종료일 일치"
        checks.append(
            dict(
                item=item,
                status=result["status"] or "review_required",
                reason=reason,
                engine_result=result,
            )
        )
        packets.append(packet)
    directory = ROOT / ".local/final-review/reconciliation" / digest(packets)
    directory.mkdir(parents=True, exist_ok=True)
    artifact = dict(packets=packets, policy=review["reconciliation_policy"], results=checks)
    target = directory / "evaluation.json"
    encoded = json.dumps(artifact, ensure_ascii=False, indent=2)
    if target.exists() and target.read_text("utf-8") != encoded:
        raise ValueError("RECONCILIATION_REPLAY_CONFLICT")
    if not target.exists():
        target.write_text(encoded, encoding="utf-8")
    return dict(
        status="reviewed",
        checks=checks,
        policy_status="approved_project_policy",
        final_status="completed"
        if all(
            c["status"] == "not_applicable" or c["engine_result"]["execution_state"] == "completed"
            for c in checks
        )
        else "blocked_source_binding",
        review_record_sha256=REVIEW_SHA256,
    )
