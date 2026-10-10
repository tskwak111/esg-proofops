"""Bounded annual filing discovery and explicit, append-only operator pin records.

Listings describe a receipt-date search window, not proof that no filing exists elsewhere.
Corrections remain separate receipts; neither ordering nor discovery selects a receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from proofops.adapters.dart.client import (
    DartAuthError,
    DartClient,
    DartError,
    DartRateLimitError,
    redact_api_key,
)

_ANNUAL = re.compile(
    r"^(?P<prefix>(?:\[[^\]]+\])*)사업보고서\s*\((?P<period>[0-9]{4}\.[0-9]{2})\)$"
)


def _date(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("date_must_be_YYYYMMDD")
    datetime.strptime(value, "%Y%m%d")
    return value


def _integer(value: Any) -> int:
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,9}", value):
        return int(value)
    raise ValueError("invalid_pagination")


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")


def list_annual_filings(
    client: DartClient,
    *,
    corp_code: str,
    bgn_de: str,
    as_of: str,
    page_count: int = 100,
    max_pages: int = 100,
) -> dict[str, Any]:
    """List annual/corrected receipts through as_of (inclusive), without choosing latest.

    Status 013 on the first page is scoped not_found; empty success, inconsistent
    pagination, malformed rows, and interrupted enumeration are blocked/incomplete.
    Raw response hashes cover exact wire bytes, including pages rejected by validation.
    """
    if not isinstance(corp_code, str) or not re.fullmatch(r"[0-9]{8}", corp_code):
        raise ValueError("invalid_corp_code")
    if _date(bgn_de) > _date(as_of):
        raise ValueError("filing_date_range_reversed")
    if (
        type(page_count) is not int
        or not 1 <= page_count <= 100
        or type(max_pages) is not int
        or not 1 <= max_pages <= 1000
    ):
        raise ValueError("invalid_pagination_bounds")
    result: dict[str, Any] = {
        "schema_version": "filings-1",
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "as_of": as_of,
        "status": "blocked",
        "coverage": "incomplete",
        "reason": None,
        "filings": [],
        "raw_response_sha256": [],
        "pinned_rcept_no": None,
        "pin_history": [],
    }
    start_count = client.request_count
    seen: set[str] = set()
    expected: tuple[int, int] | None = None
    hashed = False
    try:
        for page in range(1, max_pages + 1):
            hashed = False
            response = client.list_filings(
                corp_code,
                bgn_de,
                as_of,
                pblntf_detail_ty="A001",
                last_reprt_at="N",
                page_no=page,
                page_count=page_count,
            )
            digest = hashlib.sha256(response.raw_bytes).hexdigest()
            result["raw_response_sha256"].append(digest)
            hashed = True
            data = response.data
            if data.get("status") == "013":
                if (
                    page != 1
                    or data.get("list") not in (None, [])
                    or any(
                        _integer(data[key]) != 0
                        for key in ("total_count", "total_page")
                        if key in data
                    )
                ):
                    raise ValueError("inconsistent_no_data")
                result.update(status="not_found", coverage="complete", reason="no_data_in_window")
                break
            total = _integer(data.get("total_count"))
            pages = _integer(data.get("total_page"))
            if (
                _integer(data.get("page_no")) != page
                or _integer(data.get("page_count")) != page_count
                or total < 1
                or pages != (total + page_count - 1) // page_count
                or (expected is not None and expected != (total, pages))
            ):
                raise ValueError("inconsistent_pagination")
            expected = (total, pages)
            rows = data.get("list")
            if not isinstance(rows, list) or len(rows) != min(page_count, total - len(seen)):
                raise ValueError("missing_page_rows")
            for row in rows:
                if not isinstance(row, dict) or row.get("corp_code") != corp_code:
                    raise ValueError("filing_company_mismatch")
                receipt = row.get("rcept_no")
                if not isinstance(receipt, str) or not re.fullmatch(r"[0-9]{14}", receipt):
                    raise ValueError("invalid_filing_receipt")
                if receipt in seen:
                    raise ValueError("duplicate_filing_receipt")
                seen.add(receipt)
                received = _date(row.get("rcept_dt"))
                if receipt[:8] != received:
                    raise ValueError("filing_receipt_date_mismatch")
                name = row.get("report_nm")
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("missing_report_name")
                match = _ANNUAL.fullmatch(name.strip())
                if not match:
                    raise ValueError("unrecognized_annual_report")
                datetime.strptime(match["period"], "%Y.%m")
                if not bgn_de <= received <= as_of:
                    continue
                result["filings"].append(
                    {
                        "rcept_no": receipt,
                        "rcept_dt": received,
                        "corp_code": corp_code,
                        "report_nm": redact_api_key(name, client.api_key),
                        "report_period": match["period"],
                        "kind": "corrected_annual" if "정정" in match["prefix"] else "annual",
                        "raw_response_sha256": digest,
                    }
                )
            if page == pages:
                result.update(
                    status="complete" if result["filings"] else "not_found",
                    coverage="complete",
                    reason=None if result["filings"] else "no_annual_filings_in_window",
                )
                break
        else:
            result["reason"] = "pagination_limit"
    except DartRateLimitError:
        result["reason"] = "rate_limited"
    except DartAuthError:
        result["reason"] = "authentication_failed"
    except (DartError, ValueError, TypeError, OverflowError):
        result["reason"] = "incomplete_or_invalid_response"
    if not hashed and client.last_response_sha256:
        result["raw_response_sha256"].append(client.last_response_sha256)
    result["filings"].sort(key=lambda row: (row["rcept_dt"], row["rcept_no"]))
    result["request_count"] = client.request_count - start_count
    result["diagnostics"] = client.diagnostics
    return result


def pin_filing(
    manifest: dict[str, Any],
    *,
    rcept_no: str,
    operator: str,
    pinned_at: str,
) -> dict[str, Any]:
    """Return a fresh snapshot; retain every prior pin and receipt, never select implicitly.

    operator is an audit attribution supplied by the caller, not an authentication claim.
    Files are local operator artifacts; consumers must apply their own authorization.
    """
    _validate_listing(manifest)
    if manifest.get("pin_history") or manifest.get("pinned_rcept_no") is not None:
        validate_pinned_manifest(manifest)
    if (
        manifest.get("schema_version") != "filings-1"
        or manifest.get("status") != "complete"
        or manifest.get("coverage") != "complete"
        or not isinstance(rcept_no, str)
        or not re.fullmatch(r"[0-9]{14}", rcept_no)
        or not isinstance(operator, str)
        or not operator.strip()
    ):
        raise ValueError("pin_requires_complete_listing_and_explicit_operator_receipt")
    stamp = datetime.fromisoformat(pinned_at.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("pin_timestamp_requires_timezone")
    rows = manifest.get("filings", [])
    matching = [row for row in rows if row.get("rcept_no") == rcept_no]
    if len(matching) != 1:
        raise ValueError("receipt_not_in_listing")
    row = matching[0]
    if (
        row.get("corp_code") != manifest.get("corp_code")
        or not _date(manifest["bgn_de"]) <= _date(row["rcept_dt"]) <= _date(manifest["as_of"])
        or row["rcept_dt"] != rcept_no[:8]
        or row.get("raw_response_sha256") not in manifest.get("raw_response_sha256", [])
    ):
        raise ValueError("receipt_provenance_mismatch")
    result = deepcopy(manifest)
    history = result.get("pin_history")
    if not isinstance(history, list):
        raise ValueError("invalid_pin_history")
    if history and datetime.fromisoformat(history[-1]["pinned_at"]) > stamp:
        raise ValueError("pin_timestamp_precedes_history")
    history.append(
        {
            "rcept_no": rcept_no,
            "previous_rcept_no": manifest.get("pinned_rcept_no"),
            "operator": operator.strip(),
            "pinned_at": stamp.isoformat(),
            "previous_manifest_sha256": hashlib.sha256(_canonical(manifest)).hexdigest(),
        }
    )
    result["pinned_rcept_no"] = rcept_no
    return result


def _validate_listing(manifest: dict[str, Any]) -> None:
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "filings-1"
        or manifest.get("status") != "complete"
        or manifest.get("coverage") != "complete"
        or manifest.get("reason") is not None
        or not isinstance(manifest.get("corp_code"), str)
        or not re.fullmatch(r"[0-9]{8}", manifest["corp_code"])
    ):
        raise ValueError("invalid_complete_listing")
    begin, end = _date(manifest.get("bgn_de")), _date(manifest.get("as_of"))
    hashes = manifest.get("raw_response_sha256")
    if (
        begin > end
        or not isinstance(hashes, list)
        or not hashes
        or any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes)
    ):
        raise ValueError("invalid_listing_provenance")
    rows = manifest.get("filings")
    if not isinstance(rows, list) or not rows:
        raise ValueError("missing_filings")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid_filing")
        receipt = row.get("rcept_no")
        if (
            not isinstance(receipt, str)
            or not re.fullmatch(r"[0-9]{14}", receipt)
            or receipt in seen
            or row.get("corp_code") != manifest["corp_code"]
            or not begin <= _date(row.get("rcept_dt")) <= end
            or row["rcept_dt"] != receipt[:8]
            or row.get("raw_response_sha256") not in hashes
        ):
            raise ValueError("invalid_filing_provenance")
        seen.add(receipt)
        name = row.get("report_nm")
        match = _ANNUAL.fullmatch(name.strip()) if isinstance(name, str) else None
        if (
            not match
            or row.get("report_period") != match["period"]
            or row.get("kind") != ("corrected_annual" if "정정" in match["prefix"] else "annual")
        ):
            raise ValueError("invalid_filing_classification")
        datetime.strptime(match["period"], "%Y.%m")


def validate_pinned_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate structure and the complete hash-linked pin history; return selected row.

    Hashes detect inconsistent edits, not a malicious rewrite of an unsigned local file.
    The caller must separately authorize the operator and the file's provenance.
    """
    _validate_listing(manifest)
    history = manifest.get("pin_history")
    receipts = {row["rcept_no"]: row for row in manifest["filings"]}
    if not isinstance(history, list) or not history:
        raise ValueError("explicit_operator_pin_required")
    reconstructed = deepcopy(manifest)
    previous_stamp = None
    previous_receipt = None
    for event in history:
        if (
            not isinstance(event, dict)
            or event.get("rcept_no") not in receipts
            or event.get("previous_rcept_no") != previous_receipt
            or not isinstance(event.get("operator"), str)
            or not event["operator"].strip()
            or not isinstance(event.get("pinned_at"), str)
        ):
            raise ValueError("invalid_pin_history")
        stamp = datetime.fromisoformat(event["pinned_at"])
        if stamp.tzinfo is None or (previous_stamp is not None and stamp < previous_stamp):
            raise ValueError("invalid_pin_chronology")
        previous_stamp, previous_receipt = stamp, event["rcept_no"]
    if manifest.get("pinned_rcept_no") != previous_receipt:
        raise ValueError("pin_history_selection_mismatch")
    for event in reversed(history):
        reconstructed["pin_history"].pop()
        reconstructed["pinned_rcept_no"] = event["previous_rcept_no"]
        if hashlib.sha256(_canonical(reconstructed)).hexdigest() != event.get(
            "previous_manifest_sha256"
        ):
            raise ValueError("pin_history_integrity_mismatch")
    return deepcopy(receipts[manifest["pinned_rcept_no"]])


def write_filings(path: str | Path, manifest: dict[str, Any]) -> None:
    """Exclusive create: existing snapshots and pin histories are never overwritten."""
    payload = _canonical(manifest) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(payload)
