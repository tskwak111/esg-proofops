"""S_APR: immutable report bytes, ordering, and validation boundaries."""

from hashlib import sha256

import pytest
from proofops.application import reporting

from tests.acceptance.test_report import CLAIMS, _tag_element, decisions, manifest


def report_inputs(extended):
    snapshot, records = manifest(), decisions()
    if extended:
        snapshot["claim_revision_refs"].reverse()
        records[CLAIMS[0]]["claim_quote"] = '=검토 <script> & "인용"'
        records[CLAIMS[0]]["tag_elements"] = [
            _tag_element("G1", "present", "2040년", "2040년 목표"),
            _tag_element("G2", "unknown", None, "미확인"),
        ]
        records[CLAIMS[1]].update(
            decision_status="blocked_evidence",
            gap_ids=[],
            grade_floor="E1",
            grade_ceiling="E3",
            grade_open_elements=["M2", "M3"],
        )
    return snapshot, records


GOLDEN = {
    (False, "json"): (8007, "58f5b956053b2b72d69ddf03eef3b2a9f2f4ba387c3dc1355ace8382ab52e05f"),
    (False, "csv"): (6641, "004d152b90c1a84d088625373d6e67a5f58e39a0b24a5a17504eafd2e45af819"),
    (False, "html"): (14162, "046f6e72afc6cda7d57443f62ca3d5dc7fe308e365607e8557ddce8724a4a99b"),
    (True, "json"): (8548, "f83daddf91befa779a81f420b1fa9c2c3358fa975890c194a9cfc22065719dd3"),
    (True, "csv"): (7264, "84dfdb2dd73aa900cb9e670f59313a0e1774f9ce03895a0b027636c52fa875c2"),
    (True, "html"): (15387, "425c127fa2d80e432a3a5794b5ec78413e110f3077d3870cf846700fddeb8503"),
}


@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("output_format", ["json", "csv", "html"])
def test_report_bytes_and_order_are_frozen(extended, output_format, tmp_path):
    snapshot, records = report_inputs(extended)
    model = reporting.build_report_model(snapshot, records)
    assert [c["claim_id"] for c in model["claims"]] == (
        list(reversed(CLAIMS)) if extended else list(CLAIMS)
    )
    content = reporting.render_report(model, output_format)
    assert (len(content), sha256(content).hexdigest()) == GOLDEN[extended, output_format]
    target = tmp_path / ("report." + output_format)
    target.write_bytes(content)
    assert target.read_bytes() == content
    assert reporting.render_report(model, output_format) == content


def test_report_validation_messages_and_order():
    with pytest.raises(ValueError, match="^report_model_v1 is required$"):
        reporting.render_report({}, "pdf")
    with pytest.raises(ValueError, match="^unsupported element evidence encoding$"):
        reporting.render_report(
            dict(schema="report_model_v1", element_evidence_encoding="bad"), "pdf"
        )
    with pytest.raises(ValueError, match="^report claims are required$"):
        reporting.render_report(dict(schema="report_model_v1"), "pdf")
    with pytest.raises(ValueError, match="^output_format must be json, csv, or html$"):
        reporting.render_report(dict(schema="report_model_v1", claims=[]), "pdf")


def test_original_report_module_remains_the_helper_patch_boundary(monkeypatch):
    model = reporting.build_report_model(*report_inputs(True))
    monkeypatch.setattr(reporting, "_csv_safe", lambda value: "patched-cell")
    rows = reporting.render_report(model, "csv").decode().splitlines()
    assert all(set(row.split(",")) == {"patched-cell"} for row in rows[1:])
    monkeypatch.setattr(reporting, "_element_label", lambda value: "patched-element")
    assert "patched-element" in reporting.render_report(model, "html").decode()
