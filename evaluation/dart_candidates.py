"""Produce traceable C3/C4 input drafts without approving scope or accounting policy."""

import re


def candidates(claim, report):
    quote = claim["quote"]
    normalized = claim.get("normalized", {})

    def field(name):
        value = normalized.get(name, {})
        return value if value.get("value") is not None and value.get("citation") else None

    source = dict(
        page=claim.get("page"),
        quote=quote,
        parser_source=claim.get("parser_source"),
        approved=False,
    )
    financial = dict(
        receipt=report.get("receipt"),
        source_sha256=report.get("source_sha256"),
        fs_div=report.get("config", {}).get("fs_div"),
        year=report.get("config", {}).get("year"),
    )
    money = re.search(r"\d[\d,.]*\s*(?:천|만|억|조)?\s*(?:원|KRW|USD|달러)", quote)
    result = {}
    if money and re.search(r"투자|설비|자본적|CAPEX", quote, re.I):
        rows = report.get("capex_candidates", [])
        amount, unit = field("value"), field("unit")
        if not (
            amount
            and unit
            and unit["value"] in ("원", "KRW", "USD", "달러")
            and money.group() in amount["citation"].get("quote", "")
        ):
            amount = None
        result["C3"] = dict(
            status="candidate_only",
            claim_source=source,
            financial_source=financial,
            amount=amount,
            unit=unit if amount else None,
            year=field("year"),
            monetary_span=money.group(),
            capex_rows=rows,
            context=dict(
                currency="KRW" if re.search(r"원|KRW", money.group()) else "USD",
                target_period_start=None,
                target_period_end=None,
                capex_period_start=None,
                capex_period_end=None,
                capex_account_ids=[r["account_id"] for r in rows if r.get("account_id")],
                commitment_source_id=None,
                funding_plan_source_id=None,
            ),
            required=[
                "기간 연결",
                "기업 범위 승인",
                "CAPEX 계정 선택",
                "투자 약정·자금조달 근거",
                "정책 승인",
            ],
        )
    if re.search(r"매출|revenue", quote, re.I) and "%" in quote:
        ratio, unit = field("value"), field("unit")
        if not (ratio and unit and unit["value"] == "%"):
            ratio = None
        result["C4"] = dict(
            status="candidate_only",
            claim_source=source,
            financial_source=financial,
            ratio=ratio,
            denominator=field("denominator"),
            revenue_rows=report.get("revenue_candidates", []),
            context=dict(
                classification_name=None, definition_source_ids=[], calculation_source_ids=[]
            ),
            required=[
                "매출 분류 정의",
                "분자 금액·산식 근거",
                "분모 계정 선택",
                "기간·기업 범위 승인",
                "정책 승인",
            ],
        )
    return result
