"""Regression guards for reviewed real evidence, never a fabricated consensus."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from proofops.domain.rules.engine import EvidenceReview

from evaluation import local_review as review
from evaluation.local_analysis_pipeline import MANIFEST_HASH, SOURCE_HASH
from evaluation.local_review_dart import compare_reviewed

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def original():
    path = ROOT / ".local/copy-pipeline-verified/response.json"
    if not path.exists() or review.load_review() is None:
        pytest.skip("local reviewed source artifacts unavailable")
    return json.loads(path.read_text("utf-8"))["body"]


def test_review_rejects_different_document_and_changed_candidate(original):
    claim = original["claims"][0]
    before = deepcopy(claim)
    assert not review.apply_review(claim, "0" * 64, MANIFEST_HASH)
    assert not review.apply_review(claim, SOURCE_HASH, "0" * 64)
    assert claim == before
    claim["quote"] += " altered"
    assert not review.apply_review(claim, SOURCE_HASH, MANIFEST_HASH)


def test_review_tampering_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "review.json"
    path.write_text('{"approved":true}')
    monkeypatch.setattr(review, "REVIEW_PATH", path)
    assert review.load_review() is None


def test_browser_integer_serialization_does_not_invalidate_same_geometry(original):
    claim = original["claims"][0]
    before = review.digest(review.candidate(claim))
    claim["parser_source"]["bbox"] = [float(v) for v in claim["parser_source"]["bbox"]]
    assert review.digest(review.candidate(claim)) == before
    claim["parser_source"]["bbox"][0] += 0.001
    assert review.digest(review.candidate(claim)) != before


def test_reviewed_fields_and_unknowns_are_not_fabricated_absence(original):
    for index, c in enumerate(original["claims"]):
        assert review.apply_review(c, SOURCE_HASH, MANIFEST_HASH)
        assert c["decision"]["evidence_grade"] is None
        assert all(e["state"] != "absent" for e in c["elements"])
        for e in c["elements"]:
            if index not in (0, 2, 21) and e["name"] in (
                "method",
                "numerical_check",
                "assurance_covered",
            ):
                assert e["state"] == "unknown"
    assert original["claims"][1]["crosscheck"]["original_audit"] == "parse_conflict"
    assert original["claims"][1]["crosscheck"]["status"] != "consensus"
    assert original["claims"][7]["decision"]["grade_range"] is None
    assert original["claims"][23]["decision"]["grade_range"]["floor"] == "E1"
    assert original["claims"][25]["normalized"]["value"]["value"] == "30000"
    assert original["claims"][17]["normalized"]["denominator"]["status"] == "reviewed"


def test_attestation_requires_real_identity_time_hashes():
    with pytest.raises(ValueError):
        EvidenceReview("", "2026-10-10T00:00:00+00:00", "user request", "a" * 64, "b" * 64)
    valid = EvidenceReview("codex", "2026-10-10T00:00:00+00:00", "user request", "a" * 64, "b" * 64)
    with pytest.raises(ValueError):
        replace(valid, reviewed_at="2026-10-10")


def test_chart_review_ignores_timing_but_rejects_changed_values(original):
    v = original["vision"]
    v["pages"][0]["metrics"]["wall_seconds"] = 999
    review.review_chart(v, SOURCE_HASH)
    points = v["pages"][1]["chart_bindings"]["points"]
    assert len([p for p in points if p.get("original_series")]) == 4
    assert all(p["review_status"] == "source_reviewed" for p in points)
    changed = deepcopy(original["vision"])
    changed.pop("review_record_sha256", None)
    changed["pages"][1]["chart_bindings"]["points"][0]["value"] = "999"
    review.review_chart(changed, SOURCE_HASH)
    assert "review_record_sha256" not in changed


def test_dart_off_and_wrong_company_never_receive_review(original):
    c = original["claims"][0]
    review.apply_review(c, SOURCE_HASH, MANIFEST_HASH)
    assert compare_reviewed(c, {"status": "off"}) is None
    report = deepcopy(original["dart"])
    report["config"]["corp_code"] = "00000000"
    assert compare_reviewed(c, report) is None


def test_dart_policy_approval_is_not_automatic_match(original):
    for i in (0, 9, 28):
        c = original["claims"][i]
        review.apply_review(c, SOURCE_HASH, MANIFEST_HASH)
        result = compare_reviewed(c, original["dart"])
        assert result["policy_status"] == "approved_project_policy"
        if i == 0:
            assert result["checks"][1]["status"] == "matched"
        else:
            assert all(check["status"] != "matched" for check in result["checks"])
        assert result["checks"][2]["engine_result"]["execution_state"] == "not_run"
        assert result["checks"][3]["status"] == "not_applicable"
    assert review.load_review()["reconciliation_policy"]["c3_threshold"] is None
    assert review.load_review()["rulepack"]["tenant_id"] == review.load_review()["source_tenant_id"]


def test_changed_dart_period_source_is_rejected(original, tmp_path, monkeypatch):
    from evaluation import local_review_dart

    report = original["dart"]
    statement = Path(".local/dart-web") / report["source_sha256"] / "statements.json"
    (tmp_path / statement).parent.mkdir(parents=True)
    (tmp_path / statement).write_bytes((ROOT / statement).read_bytes())
    period_file = Path(review.load_review()["period_review"]["financial_artifact"])
    (tmp_path / period_file).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / period_file).write_bytes(b"changed period source")
    monkeypatch.setattr(local_review_dart, "ROOT", tmp_path)
    c = original["claims"][0]
    review.apply_review(c, SOURCE_HASH, MANIFEST_HASH)
    with pytest.raises(ValueError, match="DART_PERIOD_ARTIFACT_INTEGRITY_MISMATCH"):
        compare_reviewed(c, report)
