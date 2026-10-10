import json
from dataclasses import asdict
from uuid import uuid4

import pytest

from evaluation import report_decisions as rd
from evaluation import report_review as rr
from tests.unit.test_report_decisions import element, setup_case


def retained(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "ROOT", tmp_path)
    text = "위원회 운영; 전 사업장; 외부기관 인증 범위 전 사업장"
    pack, source, blocks, claim = setup_case(text, "management")
    claim["elements"] = [
        element("named_means_or_concrete_state", "M1", "위원회 운영", blocks),
        element("org_boundary", "M2", "전 사업장; 외부기관", blocks),
        element("external_verification", "M3", "외부기관 인증 범위 전 사업장", blocks),
    ]
    rd.decide(claim, source, blocks, pack)
    run = uuid4().hex
    inputs = dict(
        source_sha256=source.sha256,
        blocks=blocks,
        rulepack=asdict(pack),
        inputs=[claim["decision_input"]],
    )
    result = dict(run_id=run, claims=[claim], decision_inputs_sha256=rd.digest(inputs))
    folder = tmp_path / run
    folder.mkdir()
    for name, value in (("result.json", result), ("decision-inputs.json", inputs)):
        (folder / name).write_text(json.dumps(value), encoding="utf-8")
    payload = dict(
        run_id=run,
        claim_index=0,
        result_sha256=rd.digest(result),
        reviewer="synthetic reviewer",
        note="synthetic original coverage checked",
        confirmed_names=["external_verification"],
        coverage_confirmed=True,
    )
    return result, payload


def test_review_recalculates_e3_and_preserves_original(tmp_path, monkeypatch):
    original, payload = retained(tmp_path, monkeypatch)
    before = (tmp_path / payload["run_id"] / "result.json").read_bytes()
    reviewed = rr.review(payload)
    claim = reviewed["result"]["claims"][0]
    assert claim["decision"]["evidence_grade"] == "E3"
    assert claim["decision"]["decision_revision"] == 2
    assert claim["review"]["expert_gold"] is False
    assert (tmp_path / payload["run_id"] / "result.json").read_bytes() == before
    assert original["claims"][0]["decision"]["evidence_grade"] is None


def test_review_requires_current_receipt_and_explicit_coverage(tmp_path, monkeypatch):
    _, payload = retained(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="REVISION_CONFLICT"):
        rr.review(dict(payload, result_sha256="a" * 64))
    with pytest.raises(ValueError, match="COVERAGE_REQUIRED"):
        rr.review(dict(payload, coverage_confirmed=False))
    with pytest.raises(ValueError, match="IDENTITY"):
        rr.review(dict(payload, reviewer=""))


def test_tampered_input_is_rejected(tmp_path, monkeypatch):
    _, payload = retained(tmp_path, monkeypatch)
    path = tmp_path / payload["run_id"] / "decision-inputs.json"
    inputs = json.loads(path.read_text())
    inputs["blocks"][0]["raw_text"] += "changed"
    path.write_text(json.dumps(inputs))
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        rr.review(payload)


def test_review_cannot_create_grades_or_new_fact_names(tmp_path, monkeypatch):
    _, payload = retained(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="ELEMENTS"):
        rr.review(dict(payload, confirmed_names=["invented"]))
    with pytest.raises(ValueError, match="INVALID_REVIEW_RUN"):
        rr.review(dict(payload, run_id="../outside"))
    with pytest.raises(ValueError, match="INVALID_REVIEW_FIELDS"):
        rr.review(dict(payload, evidence_grade="E3"))


def test_review_retry_is_idempotent_and_old_revision_cannot_fork(tmp_path, monkeypatch):
    _, payload = retained(tmp_path, monkeypatch)
    first = rr.review(payload)
    assert rr.review(payload) == first
    with pytest.raises(ValueError, match="REVISION_CONFLICT"):
        rr.review(dict(payload, note="different confirmation"))


def test_absence_requires_complete_search_and_cannot_erase_present(tmp_path, monkeypatch):
    result, payload = retained(tmp_path, monkeypatch)
    absent = dict(payload, confirmed_names=[], absent_names=["external_verification"])
    with pytest.raises(ValueError, match="FULL_SEARCH"):
        rr.review(absent)
    result["coverage"] = dict(document_pages=1, parsed_pages=[1])
    path = tmp_path / payload["run_id"] / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    absent.update(result_sha256=rd.digest(result), searched_pages=[1], absence_confirmed=True)
    with pytest.raises(ValueError, match="CONTRADICTS"):
        rr.review(absent)
    result["claims"][0]["elements"].append(
        dict(
            name="responsible_organization",
            element_id="M5",
            state="unknown",
            candidate_state="unknown",
        )
    )
    path.write_text(json.dumps(result), encoding="utf-8")
    absent.update(result_sha256=rd.digest(result), absent_names=["responsible_organization"])
    updated = rr.review(absent)["result"]["claims"][0]
    assert updated["elements"][-1]["state"] == "absent"
    assert updated["decision"]["evidence_grade"] is None
