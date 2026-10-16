"""Printed labels are source proofs, never inferred data or grade facts."""

from copy import deepcopy
from hashlib import sha256

import pytest

from tests.integration.test_claim_source_verification import inputs
from tests.integration.test_upstage_ocr_page import store


def request(source):
    return dict(
        tenant_id="11111111-1111-4111-8111-111111111111",
        run_id="ch1-test",
        document_version_id="ch1-document",
        parse_manifest_id="ch1-parse",
        source_sha256=sha256(source).hexdigest(),
        selected_pages=[1],
        regions=[
            dict(
                id="chart",
                page=1,
                kind="bar",
                bbox=None,
                observations=[
                    dict(
                        id="point",
                        basis="printed",
                        value=dict(quote="1234"),
                        unit=dict(quote="tCO2e"),
                        series=dict(quote="emissions"),
                        year=None,
                    )
                ],
            )
        ],
    )


def test_real_render_trusted_acquisition_replay_and_unknown_binding(tmp_path):
    from proofops.adapters.local.ch1_charts import recover, replay

    source, _, _ = inputs()
    req = request(source)
    ocr = store(tmp_path)
    receipt = recover(source, req, store=ocr)
    point = receipt["regions"][0]["observations"][0]
    assert point["fields"]["value"]["status"] == "verified"
    assert point["fields"]["value"]["words"][0]["bbox"] == [164, 70, 190, 82]
    assert point["fields"]["unit"]["status"] == "verified"
    assert point["fields"]["year"]["status"] == "unknown"
    assert point["binding_status"] == "unknown"
    assert point["eligible_for_scoring"] is False
    ocr.fetch = lambda *a, **k: pytest.fail("replay must never collect")
    assert replay(receipt, source, req, store=ocr) == receipt
    bad = deepcopy(receipt)
    bad["regions"][0]["observations"][0]["eligible_for_scoring"] = True
    with pytest.raises(ValueError, match="CH1_RECEIPT_MISMATCH"):
        replay(bad, source, req, store=ocr)


@pytest.mark.parametrize("change", ["digit", "unit", "estimate", "axis", "low_confidence"])
def test_no_estimated_axis_or_changed_labels_can_be_verified(tmp_path, change):
    import json

    from proofops.adapters.local.ch1_charts import recover

    from tests.integration.test_upstage_ocr_page import response

    source, _, _ = inputs()
    req = request(source)
    point = req["regions"][0]["observations"][0]
    raw = json.loads(response())
    if change == "digit":
        point["value"]["quote"] = "1235"
    if change == "unit":
        point["unit"]["quote"] = "tCO₂e"
    if change == "estimate":
        point["basis"] = "visual_estimate"
    if change == "axis":
        point["basis"] = "axis_tick"
    if change == "low_confidence":
        raw["pages"][0]["words"][3]["confidence"] = 0.979
    ocr = store(tmp_path, transport=lambda png: (json.dumps(raw).encode(), "sim"))
    result = recover(source, req, store=ocr)["regions"][0]["observations"][0]
    assert result["status"] != "verified"
    assert result["eligible_for_scoring"] is False


def test_scope_identity_and_trusted_ledger_cannot_be_rewritten(tmp_path):
    from proofops.adapters.local.ch1_charts import recover, replay

    source, _, _ = inputs()
    req = request(source)
    ocr = store(tmp_path)
    receipt = recover(source, req, store=ocr)
    for bad in [req | dict(selected_pages=[2]), req | dict(source_sha256="0" * 64)]:
        with pytest.raises(ValueError):
            recover(source, bad, store=ocr)
    with pytest.raises(ValueError):
        replay(receipt, source, req | dict(tenant_id="another-tenant"), store=ocr)
    bad = deepcopy(receipt)
    bad["page_reads"][0]["collection"]["response_hex"] = "00"
    with pytest.raises(ValueError, match="OCR_COLLECTION_UNTRUSTED"):
        replay(bad, source, req, store=ocr)


def test_missing_collection_is_unknown_and_never_refetched_on_replay():
    from proofops.adapters.local.ch1_charts import recover, replay

    from tests.integration.test_fxf_source import MissingStore

    source, _, _ = inputs()
    req = request(source)
    receipt = recover(source, req, store=MissingStore())
    point = receipt["regions"][0]["observations"][0]
    assert point["status"] == "unknown"
    assert point["fields"]["value"]["status"] == "unknown"
    assert replay(receipt, source, req, store=MissingStore()) == receipt


def test_duplicate_disconnected_out_of_region_and_malformed_labels(tmp_path):
    import json

    from proofops.adapters.local.ch1_charts import recover

    from tests.integration.test_upstage_ocr_page import response

    source, _, _ = inputs()
    req = request(source)
    raw = json.loads(response())
    duplicate = deepcopy(raw["pages"][0]["words"][3])
    duplicate["id"] = 99
    for vertex in duplicate["boundingBox"]["vertices"]:
        vertex["y"] += 100
    raw["pages"][0]["words"].append(duplicate)
    ocr = store(tmp_path, transport=lambda png: (json.dumps(raw).encode(), "sim"))
    result = recover(source, req, store=ocr)
    value = result["regions"][0]["observations"][0]["fields"]["value"]
    assert value["reason"] == "ambiguous_printed_label"
    req["regions"][0]["observations"][0]["value"]["word_ids"] = [3]
    assert (
        recover(source, req, store=ocr)["regions"][0]["observations"][0]["fields"]["value"][
            "status"
        ]
        == "verified"
    )
    req["regions"][0]["bbox"] = [1, 1, 50, 50]
    assert (
        recover(source, req, store=ocr)["regions"][0]["observations"][0]["fields"]["value"][
            "status"
        ]
        == "unknown"
    )
    req["regions"][0]["bbox"] = [0, 0, float("nan"), 100]
    with pytest.raises(ValueError, match="CH1_REGION_GEOMETRY_INVALID"):
        recover(source, req, store=ocr)


def test_exact_confidence_threshold_and_inline_year_never_truncate_digits(tmp_path):
    import json

    from proofops.adapters.local.ch1_charts import recover

    from tests.integration.test_upstage_ocr_page import response

    source, _, _ = inputs()
    req = request(source)
    raw = json.loads(response())
    raw["pages"][0]["words"][3]["confidence"] = 0.98
    ocr = store(tmp_path, transport=lambda png: (json.dumps(raw).encode(), "sim"))
    point = recover(source, req, store=ocr)["regions"][0]["observations"][0]
    assert point["fields"]["value"]["status"] == "verified"
    req["regions"][0]["observations"][0]["value"] = dict(quote="1234", span=[0, 3])
    point = recover(source, req, store=ocr)["regions"][0]["observations"][0]
    assert point["fields"]["value"]["status"] == "unknown"


def test_high_confidence_misread_does_not_verify_independent_75_percent_proposal(tmp_path):
    """Retain the fresh-2 failure: simulated OCR misread a printed 75% as 15%."""
    import json

    from proofops.adapters.local.ch1_charts import recover

    from tests.integration.test_upstage_ocr_page import response

    source, _, _ = inputs()
    req = request(source)
    req["regions"][0]["kind"] = "pie"
    req["regions"][0]["observations"][0]["value"] = dict(quote="75%")
    raw = json.loads(response())
    raw["pages"][0]["words"][3].update(text="15%", confidence=0.999)
    ocr = store(tmp_path, transport=lambda png: (json.dumps(raw).encode(), "sim-misread"))
    point = recover(source, req, store=ocr)["regions"][0]["observations"][0]
    assert point["fields"]["value"]["status"] == "unknown"
    assert not point["eligible_for_scoring"]
