"""Read-only local DART lookup. Selection is never policy/binding approval."""

import json
import os
import re
from datetime import date
from hashlib import sha256
from pathlib import Path

from proofops.adapters.dart.client import DartClient
from proofops.adapters.dart.filings import list_annual_filings

ROOT = Path(__file__).resolve().parents[1]


def client():
    key = os.environ.get("DART_API_KEY", "")
    for path in (ROOT / ".env.dart.local", ROOT.parent / "esg-proofops-v2/.env.dart.local"):
        if key or not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "DART_API_KEY":
                key = value.strip().strip("\"'")
    if not key:
        raise ValueError("DART_API_KEY_REQUIRED")
    return DartClient(api_key=key, timeout=8, max_retries=1)


def validate(config, *, lookup=False):
    if not isinstance(config, dict):
        raise ValueError("INVALID_DART_CONFIG")
    corp = config.get("corp_code", "")
    year = config.get("year", "")
    if not isinstance(corp, str) or not re.fullmatch(r"\d{8}", corp):
        raise ValueError("INVALID_DART_CORP_CODE")
    if not isinstance(year, str) or not re.fullmatch(r"20\d{2}", year):
        raise ValueError("INVALID_DART_YEAR")
    if not 2015 <= int(year) <= date.today().year:
        raise ValueError("INVALID_DART_YEAR")
    if not lookup:
        if config.get("fs_div") not in ("CFS", "OFS"):
            raise ValueError("DART_BASIS_REQUIRED")
        if not re.fullmatch(r"\d{14}", str(config.get("rcept_no", ""))):
            raise ValueError("DART_RECEIPT_REQUIRED")
    return corp, year


def lookup(config, *, dart=None):
    corp, year = validate(config, lookup=True)
    result = list_annual_filings(
        dart or client(),
        corp_code=corp,
        bgn_de=f"{year}0101",
        as_of=date.today().strftime("%Y%m%d"),
    )
    result["filings"] = [f for f in result["filings"] if f["report_period"] == f"{year}.12"]
    result["selection_is_approval"] = False
    return result


def collect(config, *, dart=None):
    if not config or config.get("enabled") is False:
        return {"status": "off", "notice": "DART 비교 OFF · 외부 조회 없음"}
    if config.get("enabled") is not True:
        raise ValueError("INVALID_DART_CONFIG")
    corp, year = validate(config)
    dart = dart or client()
    filings = lookup(config, dart=dart)
    receipt = config["rcept_no"]
    if filings["status"] != "complete" or not any(
        f["rcept_no"] == receipt for f in filings["filings"]
    ):
        raise ValueError("DART_RECEIPT_YEAR_MISMATCH")
    response = dart.get_financial_statements(
        corp,
        year,
        fs_div=config["fs_div"],
        expected_rcept_no=receipt,
    )
    raw = response.raw_bytes
    digest = sha256(raw).hexdigest()
    directory = ROOT / ".local/dart-web" / digest
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "statements.json").write_bytes(raw)
    (directory / "filings.json").write_text(
        json.dumps(filings, ensure_ascii=False), encoding="utf-8"
    )
    rows = response.get("list", [])
    if response.get("status") != "000":
        return dict(
            status="unavailable",
            provider_status=response.get("status"),
            config=config,
            notice="선택한 기준의 재무제표를 조회하지 못했습니다.",
        )
    revenue = [r for r in rows if r.get("account_id") in ("ifrs-full_Revenue", "ifrs_Revenue")]
    capex = [
        r
        for r in rows
        if r.get("account_id")
        in (
            "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
            "ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
        )
    ]
    return dict(
        status="retrieved",
        config=config,
        receipt=receipt,
        source_sha256=digest,
        statement_rows=len(rows),
        revenue_candidates=revenue,
        capex_candidates=capex,
        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
        final_status="blocked_policy_unapproved",
        notice="실제 DART 재무제표 조회 완료 · "
        "범위 연결과 대사 정책 미승인으로 최종 대사 판정 보류",
    )


def compare(claim, report):
    """Observed year comparison is separate from exact-period/entity reconciliation."""
    if report["status"] != "retrieved":
        return dict(status=report["status"], checks=[])
    normalized = claim.get("normalized", {})
    year = normalized.get("year", {}).get("value")
    quote = claim["quote"]
    monetary = bool(re.search(r"\d[\d,.]*\s*(?:천|만|억|조)?\s*(?:원|KRW|USD|달러)", quote))
    investment = monetary and bool(re.search(r"투자|설비|자본적|CAPEX", quote, re.I))
    revenue = bool(re.search(r"매출|revenue", quote, re.I)) and "%" in quote
    observed = (
        "input_required"
        if year is None
        else (
            "same_year_observed"
            if str(year) == report["config"]["year"]
            else "different_year_observed"
        )
    )
    from evaluation.dart_candidates import candidates

    drafts = candidates(claim, report)
    return dict(
        status="review_required",
        input_candidates=drafts,
        checks=[
            dict(
                item="C1",
                status="review_required",
                reason="주장 사업장/법인과 재무제표 연결·별도 범위의 승인된 매핑 필요",
            ),
            dict(
                item="C2",
                status=observed,
                claim_year=year,
                financial_year=report["config"]["year"],
                reason="연도만 비교한 관찰값. 정확한 보고기간 연결 필요; "
                "미래 목표는 실적 불일치가 아님",
            ),
            dict(
                item="C3",
                status="input_required" if investment else "not_applicable",
                reason="금액 투자 주장은 CAPEX 근거·정책 필요"
                if investment
                else "금액 투자 주장 아님; 발전량·설비용량은 투자금액이 아님",
            ),
            dict(
                item="C4",
                status="input_required" if revenue else "not_applicable",
                reason="매출 비중 주장은 분자·분모·정책 필요"
                if revenue
                else "매출 비중 주장 아님; 재생에너지 비율과 매출 비율은 다름",
            ),
        ],
        final_status="blocked_policy_unapproved",
    )
