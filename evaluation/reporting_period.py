"""Free reporting-period proposals from native text; never claim evidence admission.

Offsets are Python Unicode code points in the exact PDFium page text. SourceRefs
are inspection-only locators, with no invented geometry or canonical graph IDs.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from hashlib import sha256

from proofops.domain.provenance import canonical_hash

VERSION = "native-reporting-period-v1"
FIELDS = ("report_year", "period_start", "period_end")
WARNING = "보고기간 추정 실패(기본값 사용)"
ANCHOR = re.compile(
    r"보고\s*기간(?!\s*(?:동안|중|내|외))|reporting\s+period|(?m:^\s*기간\s*[:：]?\s*$)", re.I
)
EXCEPTION = re.compile(
    r"일부(?!터)|예외|적시성|시의성|주요\s*성과에\s*한해|상반기|하반기|최근\s*\d|\d\s*개년|이전\s*\d|보고\s*기간\s*외|some|except|certain|previous",
    re.I,
)
STOP = re.compile(
    r"\n\s*(?:보고\s*(?:범위|경계|기준|원칙|주기|검증)|보고서\s*(?:검증|작성)|미래\s*예측|문의처|작성\s*기준|보고\s*주기|보고서\s*발간|발행\s*주기|Cover\s*Story|Appendix|예측정보|Reporting\s+(?:scope|boundary|standards))",
    re.I,
)
YEAR = r"(?:19|20)\d{2}"
DATE = (
    rf"(?P<y>{YEAR})\s*(?:년\s*|[./-]\s*)(?P<m>\d{{1,2}})"
    r"\s*(?:월\s*|[./-]\s*)(?P<d>\d{1,2})\s*일?"
)
RANGE = re.compile(
    DATE
    + r"\s*(?:부터|에서|[~∼–—-]|to|through)\s*"
    + rf"(?:(?P<ey>{YEAR})\s*(?:년\s*|[./-]\s*))?(?P<em>\d{{1,2}})"
    r"\s*(?:월\s*|[./-]\s*)(?P<ed>\d{1,2})\s*일?",
    re.I,
)
MONTH_RANGE = re.compile(
    rf"(?P<y>{YEAR})\s*년\s*(?P<m>\d{{1,2}})\s*월\s*(?:부터|[~∼–-])\s*(?:(?P<ey>{YEAR})\s*년\s*)?(?P<em>\d{{1,2}})\s*월\s*까지"
)
FISCAL = re.compile(
    rf"(?P<y>{YEAR})\s*년?\s*(?:회계\s*연도|회계\s*년도)|(?:fiscal\s+year|FY)\s*(?P<fy>{YEAR})",
    re.I,
)
ENGLISH = re.compile(
    rf"January\s+1,?\s+(?P<y>{YEAR})\s*(?:to|through|[–-])\s*December\s+31,?\s+(?P<ey>{YEAR})", re.I
)


def validate_period(value):
    if not isinstance(value, dict):
        raise ValueError("REPORTING_SCOPE_INVALID")
    year = value.get("report_year")
    if type(year) is not int or not 1900 <= year <= 2100:
        raise ValueError("REPORTING_SCOPE_INVALID")
    try:
        start, end = (date.fromisoformat(value[k]) for k in ("period_start", "period_end"))
    except (ValueError, TypeError, KeyError):
        raise ValueError("REPORTING_SCOPE_INVALID") from None
    if start > end or not 1900 <= start.year <= end.year <= 2100:
        raise ValueError("REPORTING_SCOPE_INVALID")
    return dict(report_year=year, period_start=start.isoformat(), period_end=end.isoformat())


def _periods(text):
    result = []
    for pattern, kind in (
        (RANGE, "date_range"),
        (MONTH_RANGE, "month_range"),
        (ENGLISH, "date_range"),
        (FISCAL, "fiscal_year_calendar"),
    ):
        for match in pattern.finditer(text):
            g = match.groupdict()
            y = int(g.get("y") or g.get("fy"))
            ey = int(g.get("ey") or y)
            try:
                if kind == "fiscal_year_calendar" or pattern is ENGLISH:
                    start, end = date(y, 1, 1), date(ey, 12, 31)
                elif kind == "month_range":
                    start = date(y, int(g["m"]), 1)
                    end = date(ey, int(g["em"]), calendar.monthrange(ey, int(g["em"]))[1])
                else:
                    start, end = (
                        date(y, int(g["m"]), int(g["d"])),
                        date(ey, int(g["em"]), int(g["ed"])),
                    )
                value = validate_period(
                    dict(report_year=ey, period_start=start.isoformat(), period_end=end.isoformat())
                )
            except ValueError:
                continue
            result.append((value, kind))
        if result:  # Explicit dates take precedence over a fiscal-year summary.
            break
    return result


def detect_reporting_period(texts, page_count, source_sha256):
    candidates, exceptions, seen = [], [], set()
    inspected = sorted(
        set(range(1, min(12, page_count) + 1)) | set(range(max(1, page_count - 11), page_count + 1))
    )
    for page in inspected:
        text = texts.get(page, "")
        for anchor in ANCHOR.finditer(text):
            # Only headings/declarations about the report, not assurance boilerplate.
            line_start = text.rfind("\n", 0, anchor.start()) + 1
            prefix = text[line_start : anchor.start()].strip()
            if prefix and not re.search(r"본\s*보고서|이\s*보고서|보고서의|보고서\s*개요", prefix):
                continue
            end = min(len(text), anchor.end() + 1100)
            stop = STOP.search(text, anchor.end(), end)
            if stop:
                end = stop.start()
            # Sentence boundaries exclude decimal date punctuation and preserve offsets.
            for sentence in re.finditer(
                r".+?(?:[.!?](?=\s|$)|$)", text[anchor.start() : end], re.S
            ):
                start, finish = anchor.start() + sentence.start(), anchor.start() + sentence.end()
                quote = text[start:finish]
                if not quote.strip() or (page, start, finish) in seen:
                    continue
                seen.add((page, start, finish))
                ref = dict(
                    source_sha256=source_sha256,
                    document_version_id=source_sha256,
                    artifact_hash=sha256(text.encode()).hexdigest(),
                    block_id=f"native-page-{page}",
                    physical_page=page,
                    char_start=start,
                    char_end=finish,
                    quote=quote,
                    quote_hash=sha256(quote.encode()).hexdigest(),
                    bbox=None,
                    origin="pdfium_native_text",
                    verification_state="inspection_only",
                )
                # A central range before an exception clause remains valid, while its
                # complete sentence is retained as the exception/source locator.
                exception = EXCEPTION.search(quote)
                central = quote[: exception.start()] if exception else quote
                relevant = bool(
                    ANCHOR.search(quote) or re.search(r"재무\s*성과|사업\s*성과|경영\s*성과", quote)
                ) and not re.search(
                    r"최초\s*발간|발행일|발간일|이전\s*보고서|검증방법|검증\s*기간", quote
                )
                values = _periods(central) if relevant else []
                if exception:
                    exceptions.append(dict(source_ref=ref))
                for value, basis in values:
                    candidates.append(dict(**value, basis=basis, source_ref=ref))
                if (
                    not values
                    and relevant
                    and re.search(rf"{YEAR}\s*(?:년\s*\d{{1,2}}\s*월|[./-]\d{{1,2}}[./-])", quote)
                    and not exception
                ):
                    candidates.append(
                        dict(
                            report_year=None,
                            period_start=None,
                            period_end=None,
                            basis="incomplete_or_unresolved",
                            source_ref=ref,
                        )
                    )
    complete = {tuple(c[k] for k in FIELDS) for c in candidates if c["period_start"]}
    unresolved = any(c["basis"] == "incomplete_or_unresolved" for c in candidates)
    status = (
        "detected"
        if len(complete) == 1 and not unresolved
        else "ambiguous"
        if candidates
        else "not_found"
    )
    selected = dict(zip(FIELDS, next(iter(complete)))) if status == "detected" else None
    native_pages = {
        str(page): texts[page]
        for page in sorted(
            {item["source_ref"]["physical_page"] for item in candidates + exceptions}
        )
    }
    return dict(
        native_pages=native_pages,
        version=VERSION,
        status=status,
        selected=selected,
        candidates=candidates,
        exceptions=exceptions,
        inspected_pages=inspected,
        source_sha256=source_sha256,
    )


def resolve_reporting_scope(detection, defaults=None):
    value = detection.get("selected")
    origin = "detected" if value is not None else "operator_default"
    if value is None:
        try:
            value = validate_period(defaults)
        except ValueError:
            value = dict.fromkeys(FIELDS)
    return dict(
        **value,
        origin=origin,
        detection_status=detection["status"],
        warning=None if origin == "detected" else WARNING,
        detection_sha256=canonical_hash(detection),
    )


def validate_detection(detection, source_sha256):
    """Validate native page text/spans without granting claim-evidence acceptance."""
    if detection["source_sha256"] != source_sha256:
        raise ValueError("reporting period source mismatch")
    for item in detection["candidates"] + detection["exceptions"]:
        ref = item["source_ref"]
        text = detection["native_pages"][str(ref["physical_page"])]
        start, end = ref["char_start"], ref["char_end"]
        if (
            ref["source_sha256"] != source_sha256
            or ref["verification_state"] != "inspection_only"
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(text)
            or text[start:end] != ref["quote"]
            or sha256(text.encode()).hexdigest() != ref["artifact_hash"]
            or sha256(ref["quote"].encode()).hexdigest() != ref["quote_hash"]
        ):
            raise ValueError("reporting period source ref invalid")
