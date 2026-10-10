"""FX5: mismatch-only fallback, exact guards and trusted offline replay."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from proofops.adapters.local import upstage_ocr_profile_v4 as v4

from tests.acceptance.test_parsing import TENANT
from tests.integration.test_claim_source_verification import inputs
from tests.integration.test_upstage_ocr_page import response, store


def make_reader(tmp_path, monkeypatch, text="Page 1 emissions 1234 tCO2e"):
    from proofops.adapters.local import upstage_ocr_profile_v5 as v5

    monkeypatch.setattr(
        v5,
        "LocalRasterReader",
        lambda source: SimpleNamespace(
            policy={"status": "ready"},
            read=lambda *a, **k: {
                "status": "read",
                "text": "Page 1 emissions 9999 tCO2e",
                "reader": "tesseract",
            },
        ),
    )
    calls = []
    db = store(tmp_path, lambda png: (calls.append(1) or response(text), "fake"))
    r = v5.Reader(db, run_id="fx5")
    original = r._modules

    def modules(*a, **k):
        result, seen = original(*a, **k)
        result["claim_source_verification"].native_word_ink_geometry = lambda *a, **k: {}
        return result, seen

    monkeypatch.setattr(r, "_modules", modules)
    return r, db, calls


def test_mismatch_fallback_uses_one_page_and_replays_without_transport(tmp_path, monkeypatch):
    r, db, calls = make_reader(tmp_path, monkeypatch)
    source, graph, ref = inputs()
    result = r.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    record = result["records"][0]
    assert record["status"] == "verified"
    assert record["verification_reader"] == "upstage-ocr-page-v3"
    assert record["fallback_from_reason"] == "rendered_quote_unresolved"
    assert record["normalization"]["rendered_attempts"][0]["reader"] == "upstage-ocr-page-v3"
    assert len(calls) == 1
    db.transport = lambda *a: pytest.fail("offline replay sent OCR")
    assert r.recompute_claim_receipt(result, graph, source, (ref,), tenant_id=TENANT) == result
    forged = deepcopy(result)
    forged["records"][0]["verification_reader"] = "tesseract"
    with pytest.raises(ValueError):
        r.recompute_claim_receipt(forged, graph, source, (ref,), tenant_id=TENANT)


@pytest.mark.parametrize("text", ["Page 1 emissions 1235 tCO2e", "Page 1 emissions 1234 kgCO2e"])
def test_fallback_does_not_accept_number_or_unit_conflict(tmp_path, monkeypatch, text):
    r, _, _ = make_reader(tmp_path, monkeypatch, text)
    source, graph, ref = inputs()
    assert (
        r.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0]["status"]
        == "unresolved"
    )


def test_v5_dispatch_and_legacy_policy_preservation():
    from proofops.adapters.local import upstage_ocr_profile_v5 as v5
    from proofops.adapters.local.claim_source_policies import publication_reader

    assert publication_reader(v5.claim_source_policy()) is v5
    assert publication_reader(v4.claim_source_policy()) is v4


def test_non_render_failure_does_not_buy_fallback(tmp_path, monkeypatch):
    from tests.integration.test_claim_source_v3 import synthetic

    r, _, calls = make_reader(tmp_path, monkeypatch)
    source, graph, ref = synthetic("ESG policy 1 0% achieved", "ESG policy 10% achieved")
    result = r.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    assert result["records"][0]["status"] == "unresolved"
    assert "fallback_reader" not in result["records"][0]
    assert calls == []


def test_layout_veto_survives_fallback(tmp_path, monkeypatch):
    from proofops.adapters.local import upstage_ocr_profile_v5 as v5

    monkeypatch.setattr(v5.evidence, "_prose_layout", lambda *a: "different_column")
    r, _, _ = make_reader(tmp_path, monkeypatch)
    source, graph, ref = inputs()
    result = r.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0]
    assert result["status"] == "unresolved"
    assert result["reason"] == "different_column"
    assert "verification_reader" not in result


def test_failed_fallback_is_not_reposted(tmp_path, monkeypatch):
    r, db, _ = make_reader(tmp_path, monkeypatch)
    calls = []

    def failed(png):
        calls.append(1)
        raise TimeoutError("private")

    db.transport = failed
    source, graph, ref = inputs()
    for _ in range(2):
        record = r.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0]
        assert record["status"] == "unresolved"
    assert calls == [1]
    assert db.usage()["unsettled_calls"] == 1
