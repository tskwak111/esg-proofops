"""Offline filing discovery, correction retention, immutable operator pin history."""

import hashlib
import json
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest
from proofops.adapters.dart.client import DartClient
from proofops.adapters.dart.filings import (
    list_annual_filings,
    pin_filing,
    validate_pinned_manifest,
    write_filings,
)

from evaluation.reconciliation_filings import main

CORP = "00126380"
ORIGINAL = "20250313000532"
CORRECTED = "20251210000195"


def row(receipt=ORIGINAL, name="사업보고서 (2024.12)"):
    return {"corp_code": CORP, "rcept_no": receipt, "rcept_dt": receipt[:8], "report_nm": name}


def page(rows=None, **changes):
    rows = rows if rows is not None else [row(), row(CORRECTED, "[기재정정]사업보고서 (2024.12)")]
    payload = {
        "status": "000",
        "page_no": 1,
        "page_count": 100,
        "total_count": len(rows),
        "total_page": 1,
        "list": rows,
    }
    payload.update(changes)
    return json.dumps(payload, ensure_ascii=False).encode()


def listing(bodies=None, **options):
    pending = list(bodies or [page()])
    calls = []

    def transport(url, **kwargs):
        calls.append(parse_qs(urlsplit(url).query))
        return 200, {}, pending.pop(0)

    result = list_annual_filings(
        DartClient(api_key="offline", transport=transport, max_retries=0),
        corp_code=CORP,
        bgn_de="20250101",
        as_of=options.pop("as_of", "20251231"),
        **options,
    )
    return result, calls


def pin(manifest, receipt=ORIGINAL, stamp="2026-01-01T10:00:00+09:00"):
    return pin_filing(manifest, rcept_no=receipt, operator="operator-1", pinned_at=stamp)


def test_corrections_remain_explicit_and_original_pin_is_not_latest():
    raw = page()
    result, calls = listing([raw])
    assert result["status"] == "complete"
    assert result["pinned_rcept_no"] is None
    assert result["raw_response_sha256"] == [hashlib.sha256(raw).hexdigest()]
    assert [r["kind"] for r in result["filings"]] == ["annual", "corrected_annual"]
    assert calls[0]["last_reprt_at"] == ["N"]
    assert calls[0]["pblntf_detail_ty"] == ["A001"]
    first = pin(result)
    assert validate_pinned_manifest(first)["rcept_no"] == ORIGINAL
    second = pin(first, CORRECTED, "2026-01-02T10:00:00+09:00")
    assert first["pinned_rcept_no"] == ORIGINAL
    assert len(first["pin_history"]) == 1
    assert result["pin_history"] == []
    assert second["pin_history"][1]["previous_rcept_no"] == ORIGINAL
    assert len(second["filings"]) == 2
    assert validate_pinned_manifest(second)["rcept_no"] == CORRECTED


def test_as_of_filters_future_even_when_transport_ignores_query():
    result, calls = listing(as_of="20250313")
    assert calls[0]["end_de"] == ["20250313"]
    assert [r["rcept_no"] for r in result["filings"]] == [ORIGINAL]
    with pytest.raises(ValueError):
        pin(result, CORRECTED)


def test_full_pagination_and_bounded_truncation():
    bodies = [
        page([row()], page_count=1, total_count=2, total_page=2),
        page([row(CORRECTED)], page_no=2, page_count=1, total_count=2, total_page=2),
    ]
    result, calls = listing(bodies, page_count=1)
    assert result["status"] == "complete"
    assert result["request_count"] == len(calls) == 2
    assert len(result["raw_response_sha256"]) == 2
    truncated, _ = listing(bodies, page_count=1, max_pages=1)
    assert truncated["status"] == "blocked"
    assert truncated["reason"] == "pagination_limit"
    with pytest.raises(ValueError):
        pin(truncated)


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"not json",
        b'{"status":"000","status":"013"}',
        page([], total_count=0, total_page=0),
        page(total_count=True),
        page(page_no=2),
        page(total_page=2),
        page(list={}),
        page([row(), row()]),
        page([row(name="반기보고서 (2024.06)")]),
        page([{**row(), "corp_code": "99999999"}]),
        page([{**row(), "rcept_dt": "20250230"}]),
        page([{**row(), "rcept_no": "bad"}]),
        page([{**row(), "rcept_dt": "20250314"}]),
        page([{}]),
    ],
)
def test_malformed_or_incomplete_never_becomes_not_found(raw):
    result, _ = listing([raw])
    assert result["status"] == "blocked"
    assert result["coverage"] == "incomplete"
    assert result["raw_response_sha256"] == [hashlib.sha256(raw).hexdigest()]
    with pytest.raises(ValueError):
        pin(result)


def test_explicit_no_data_is_scoped_not_found():
    result, _ = listing([b'{"status":"013"}'])
    assert result["status"] == "not_found"
    assert result["reason"] == "no_data_in_window"
    assert result["pinned_rcept_no"] is None


def test_contradictory_no_data_is_blocked():
    result, _ = listing([b'{"status":"013","total_count":1}'])
    assert result["status"] == "blocked"


def test_no_eligible_receipts_is_scoped_not_found():
    result, _ = listing(as_of="20250101")
    assert result["status"] == "not_found"
    assert result["reason"] == "no_annual_filings_in_window"


@pytest.mark.parametrize(
    "second",
    [b'{"status":"013"}', page([row()], page_count=1, page_no=2, total_page=2, total_count=2)],
)
def test_mid_pagination_empty_or_duplicate_is_incomplete(second):
    result, _ = listing(
        [page([row()], page_count=1, total_count=2, total_page=2), second], page_count=1
    )
    assert result["status"] == "blocked"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.update(pinned_rcept_no=CORRECTED),
        lambda m: m["filings"][0].update(report_period="2023.12"),
        lambda m: m["pin_history"][0].update(previous_manifest_sha256="0" * 64),
        lambda m: m["pin_history"][0].update(operator=""),
        lambda m: m["raw_response_sha256"].append("1" * 64),
        lambda m: m.update(as_of="20260101"),
    ],
)
def test_pin_validator_rejects_inconsistent_edits(mutate):
    result, _ = listing()
    pinned = pin(result)
    mutate(pinned)
    with pytest.raises(ValueError):
        validate_pinned_manifest(pinned)


def test_snapshot_exclusive_write_and_cli_offline_pin(tmp_path, monkeypatch):
    result, _ = listing()
    original = deepcopy(result)
    source, target = tmp_path / "listing.json", tmp_path / "pin.json"
    write_filings(source, result)
    with pytest.raises(FileExistsError):
        write_filings(source, pin(result))
    monkeypatch.delenv("DART_API_KEY", raising=False)
    args = [
        "pin",
        "--input",
        str(source),
        "--output",
        str(target),
        "--rcept-no",
        ORIGINAL,
        "--operator",
        "alice",
        "--pinned-at",
        "2026-01-01T00:00:00Z",
    ]
    assert main(args) == 0
    assert validate_pinned_manifest(json.loads(target.read_text("utf-8")))["rcept_no"] == ORIGINAL
    assert json.loads(source.read_text("utf-8")) == original
    assert main(args) == 2


def test_cli_listing_requires_explicit_network_permission(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("network client must not be constructed")

    monkeypatch.setattr("evaluation.reconciliation_filings.DartClient", forbidden)
    assert (
        main(
            [
                "list",
                "--corp-code",
                CORP,
                "--bgn-de",
                "20250101",
                "--as-of",
                "20251231",
                "--output",
                str(tmp_path / "new.json"),
            ]
        )
        == 2
    )


def test_invalid_dates_precede_transport():
    with pytest.raises(ValueError):
        listing(as_of="20250230")


def test_pin_requires_timezone_and_monotonic_history():
    result, _ = listing()
    with pytest.raises(ValueError):
        pin(result, stamp="2026-01-01T00:00:00")
    with pytest.raises(ValueError):
        pin(pin(result), stamp="2025-01-01T00:00:00Z")
