"""J7 wiring and historical J3 receipts retain immutable independent identities."""

import json
import os
import sqlite3
import sys

import pytest
from proofops.application.analysis_profile import J3_POLICY, J7_POLICY, J7_PROFILE
from proofops.domain.provenance import canonical_hash


def test_j7_pilot_free_create_and_resume_pins_options(tmp_path, monkeypatch):
    from evaluation import local_upstage_pilot as pilot
    from tests.integration.test_finals_candidate_profile import create_argv

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(
        sys,
        "argv",
        create_argv(tmp_path)
        + [
            "--analysis-profile",
            J7_PROFILE,
            "--pages",
            "1",
            "--claim-pages",
            "1",
            "--mixed-ocr-max-pages",
            "1",
        ],
    )
    assert pilot.main() == 0
    state = tmp_path / "state"
    settings = json.loads((state / "settings.json").read_text())
    manifest = json.loads((state / "pilot.json").read_text())
    assert settings["extraction_j3"] is manifest["extraction_j3"] is True
    assert settings["extraction_j7"] is manifest["extraction_j7"] is True
    assert settings["extraction_w9"] is True
    with sqlite3.connect(state / "state.sqlite3") as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    assert snapshot["analysis_profile_policy_sha256"] == canonical_hash(J7_POLICY)
    assert snapshot["analysis_profile_policy"] == J7_POLICY
    assert snapshot["analysis_profile_policy_sha256"] != canonical_hash(J3_POLICY)
    before = {name: (state / name).read_bytes() for name in ["settings.json", "pilot.json"]}
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert all((state / name).read_bytes() == raw for name, raw in before.items())
    from dataclasses import asdict

    from proofops_api.local_runtime import load_local_runtime
    from proofops_worker.composition import build_composition

    from tests.integration.test_upstage_extraction import FakeProbe

    def probe_factory(*args, **kwargs):
        probe = FakeProbe()
        probe.model = "gpt-6-luna"
        probe.wire_policy_version = 2
        return probe

    ledger = tmp_path / "mock-provider-ledger"
    ledger.touch()  # isolated fixture; both providers are test doubles
    runner = build_composition(
        stage="extract",
        provider_factories={"llm": probe_factory, "parse": lambda ledger: object()},
        provider_ledgers=(ledger, ledger),
    )
    try:
        assert runner.extractor._j7 is True
        assert asdict(runner.extractor.profile) == settings["extraction_profile"]
    finally:
        runner.uploads.close()
        runner.uploads.registry.close()
    settings.pop("extraction_j3")
    (state / "settings.json").write_text(json.dumps(settings))
    with pytest.raises(ValueError, match="J7"):
        load_local_runtime(os.environ)


def test_j7_receipts_do_not_collide_with_j3_and_recompute_parent_links(tmp_path):
    from dataclasses import asdict

    import pytest
    from proofops_agent.upstage_extraction import UpstageClaimExtractor

    from tests.integration.test_upstage_extraction import FakeProbe, packet

    text = "• 환경 목표를 승인하며, 성과를 모니터링 • 기후 목표 성과를 보수에 반영"
    source_id = packet()["untrusted_document_data"]["source_id"]
    probe = FakeProbe(json.dumps({"sentence_ids": [f"{source_id}:0"]}))
    old = UpstageClaimExtractor(
        probe,
        tmp_path,
        extraction_source_ids=True,
        extraction_table_rows=True,
        extraction_pb1=True,
        extraction_w9=True,
        extraction_j3=True,
    )
    new = UpstageClaimExtractor(
        probe,
        tmp_path,
        extraction_source_ids=True,
        extraction_table_rows=True,
        extraction_pb1=True,
        extraction_w9=True,
        extraction_j3=True,
        extraction_j7=True,
    )
    old_packet = packet(text)
    old_packet["extraction_profile"] = asdict(old.profile)
    new_packet = packet(text)
    new_packet["extraction_profile"] = asdict(new.profile)
    before = old.extract(old_packet)
    result = new.extract(new_packet)
    assert len(before["spans"]) == 2 and len(result["spans"]) == 3
    assert len(list(tmp_path.glob("*/result.json"))) == 2
    saved = {p: p.read_bytes() for p in tmp_path.glob("*/result.json")}
    assert old.extract(old_packet) == before
    assert new.extract(new_packet) == result
    assert all(p.read_bytes() == raw for p, raw in saved.items())
    assert len(probe.calls) == 2
    assert old.profile.prompt_sha256 == new.profile.prompt_sha256
    target = next(p for p in saved if json.loads(p.read_text())["profile"] == asdict(new.profile))
    forged = json.loads(target.read_text())
    forged["j7_refinements"][0]["parent_start"] = 99
    target.chmod(0o600)  # adversarial test only: stored receipts are normally read-only
    target.write_text(json.dumps(forged))
    with pytest.raises(ValueError, match="EXTRACTION_RECEIPT_EXISTS"):
        new.extract(new_packet)


def test_j7_resume_cannot_upgrade_an_existing_run(tmp_path, monkeypatch, capsys):
    from evaluation import local_upstage_pilot as pilot

    (tmp_path / "pilot.json").write_text(json.dumps({"source_path": "/tmp/r.pdf"}))
    monkeypatch.setattr(
        sys, "argv", ["pilot", "--resume", "--state", str(tmp_path), "--extraction-j7"]
    )
    with pytest.raises(SystemExit):
        pilot.main()
    assert "--resume cannot add extraction J7" in capsys.readouterr().err


def test_j7_validator_failure_preserves_selected_parent(tmp_path, monkeypatch):
    from proofops.application.ingest import j7_split
    from proofops_agent.upstage_extraction import UpstageClaimExtractor

    from tests.integration.test_upstage_extraction import FakeProbe, packet

    text = "기후 목표를 승인하며, 성과 및 목표 달성현황을 모니터링"
    data = packet(text)
    source = data["untrusted_document_data"]["source_id"]
    e = UpstageClaimExtractor(
        FakeProbe(),
        tmp_path,
        extraction_source_ids=True,
        extraction_pb1=True,
        extraction_w9=True,
        extraction_j3=True,
        extraction_j7=True,
    )

    def invalid(spans, text, **kwargs):
        return [dict(spans[0], char_end=3)], [dict(parent_start=0, parent_end=len(text))]

    monkeypatch.setattr(j7_split, "refine_selected", invalid)
    spans, diagnostics = e._resolve_payload(
        {"sentence_ids": [f"{source}:0"]}, text, source, packet=data
    )
    assert [s.quote for s in spans] == [text]
    assert diagnostics["j7_refinement_rejected"]
