"""New-run opt-ins through real gates and worker; no provider dispatch."""

import json
from argparse import Namespace
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

import pytest
from proofops.application.preflight import check_local_upstage_tagger
from proofops.application.runs import RunRejected
from proofops.application.tagging.relations import OCCURRENCE_PROFILE, OCCURRENCE_SYSTEM_PROMPT
from proofops.domain.provenance import canonical_hash

from evaluation import local_upstage_pilot as pilot
from tests.integration.test_live_tagging_runtime_config import (
    AUTH,
    _draft_pack,
    _live_service,
    _register,
    _tagger_binding,
)
from tests.integration.test_relation_runtime_config import _relation
from tests.integration.test_upstage_tagger_preflight import configured

SCHEMA = Path("prompts/source_relations_occurrence_v2.schema.json").read_text()


def occurrence(settings):
    return replace(
        settings,
        model_profile=OCCURRENCE_PROFILE,
        system_prompt=OCCURRENCE_SYSTEM_PROMPT,
        schema_json=SCHEMA,
    )


@pytest.mark.parametrize("fault", [None, "prompt", "schema", "grant", "revoked"])
def test_occurrence_preflight_requires_exact_contract_and_grant(fault):
    args = configured()
    settings = occurrence(args["settings"])
    if fault == "prompt":
        settings = replace(settings, system_prompt="changed")
    elif fault == "schema":
        settings = replace(settings, schema_json="{}")
    args["settings"] = settings
    args["binding"]["tagging_settings_sha256"] = canonical_hash(asdict(settings))
    if fault == "grant":
        args["binding"]["tagging_settings_sha256"] = "0" * 64
    elif fault == "revoked":
        args["binding"]["status"] = "revoked"
    assert check_local_upstage_tagger(**args).ready is (fault is None)


@pytest.mark.parametrize("fault", [None, "schema", "missing_grant", "policy"])
def test_new_run_pins_occurrence_and_glyph_without_relaxing_grants(tmp_path, fault):
    from proofops.adapters.local.glyph_alignment_verification import claim_source_policy

    service, body, *_ = _live_service(tmp_path)
    relation = occurrence(_relation(service))
    relation = replace(relation, binding=replace(relation.binding, binding_id=str(uuid4())))
    if fault == "schema":
        relation = replace(relation, schema_json="{}")
    if fault == "missing_grant":
        relation = replace(relation, binding=replace(relation.binding, binding_id=str(uuid4())))
    grant = _tagger_binding(relation.binding.binding_id, relation)
    if fault == "policy":
        grant["input_reservation_policy_sha256"] = "0" * 64
    if fault != "missing_grant":
        _register(service, "runtime", grant, "runtime_binding_id")
    service.relation_settings = relation
    service.claim_source_policy = claim_source_policy()
    body["rule_pack_id"] = _draft_pack(service, AUTH.tenant_id).rule_pack_id
    if fault:
        with pytest.raises(RunRejected, match="CONFIG_GATE_BLOCKED"):
            service.create(AUTH, body, str(uuid4()))
    else:
        result = service.create(AUTH, body, str(uuid4()))
        snapshot = service.store.snapshot(AUTH.tenant_id, result["run_id"])
        assert snapshot["relation_settings"] == asdict(relation)
        assert snapshot["relation_settings_hash"] == canonical_hash(asdict(relation))
        assert snapshot["claim_source_policy"] == claim_source_policy()


def test_pilot_selects_new_profiles_explicitly():
    from proofops.adapters.local.glyph_alignment_verification import claim_source_policy

    result = pilot.live_tagging_settings(18, relations=True, relation_profile="occurrence-v2")
    assert result["relation_settings"]["model_profile"] == OCCURRENCE_PROFILE
    assert result["relation_settings"]["system_prompt"] == OCCURRENCE_SYSTEM_PROMPT
    assert json.loads(result["relation_settings"]["schema_json"]) == json.loads(SCHEMA)
    assert pilot.claim_source_policy_for(Namespace(claim_source_profile="glyph-alignment-v1")) == (
        claim_source_policy()
    )
    with pytest.raises(ValueError):
        pilot.live_tagging_settings(18, relation_profile="occurrence-v2")


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--relation-profile", "occurrence-v2"),
        ("--claim-source-profile", "glyph-alignment-v1"),
    ],
)
@pytest.mark.parametrize("resume", [False, True])
def test_existing_pilot_cannot_add_profiles(tmp_path, monkeypatch, capsys, flag, value, resume):
    import sys

    state = tmp_path / "old"
    state.mkdir()
    manifest = state / "pilot.json"
    original = json.dumps({"source_path": "/tmp/example.pdf"})
    manifest.write_text(original)
    argv = ["pilot", "--state", str(state), flag, value]
    if resume:
        argv.append("--resume")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit):
        pilot.main()
    assert "profile" in capsys.readouterr().err
    assert manifest.read_text() == original
    assert not (state / "settings.json").exists()


@pytest.mark.parametrize("fault", [None, "revoked", "schema", "disagree", "foreign_id"])
def test_occurrence_worker_keeps_three_replicas_and_fail_closed(tmp_path, monkeypatch, fault):
    from proofops.application.registry import artifact_sha256
    from proofops.application.tagging.relations import OCCURRENCE_SCHEMA
    from proofops_agent.upstage_relations import UpstageOccurrenceRelationsTransport
    from proofops_worker.live_tagging import LiveTaggingRuntime

    from tests.integration.test_live_relation_worker import configured as worker_setup

    old, claim, graph, packet, calls, profiles, usage = worker_setup(tmp_path, monkeypatch)
    settings = occurrence(old.relation_settings)
    if fault == "schema":
        settings = replace(settings, schema_json="{}")
    grant = dict(
        old.snapshot["relation_runtime"], tagging_settings_sha256=canonical_hash(asdict(settings))
    )
    profiles["runtime", settings.binding.binding_id] = grant
    snapshot = {k: v for k, v in old.snapshot.items() if k != "input_hash"}
    snapshot.update(
        relation_settings=asdict(settings),
        relation_settings_hash=canonical_hash(asdict(settings)),
        relation_runtime=grant,
        relation_runtime_artifact_hash=artifact_sha256(grant),
    )
    snapshot["input_hash"] = canonical_hash(snapshot)
    if fault == "schema":
        with pytest.raises(ValueError, match="TAGGING_PROFILE_MISMATCH"):
            LiveTaggingRuntime(
                old.runner,
                snapshot,
                graph,
                old.lease,
                usage,
                probe=old.preliminary_transport._probe,
                ledger=old.ledger,
                receipts=old.receipts,
            )
        assert calls == []
        return
    runtime = LiveTaggingRuntime(
        old.runner,
        snapshot,
        graph,
        old.lease,
        usage,
        probe=old.preliminary_transport._probe,
        ledger=old.ledger,
        receipts=old.receipts,
    )
    assert isinstance(runtime.relation_transport, UpstageOccurrenceRelationsTransport)
    if fault == "revoked":
        profiles["runtime", settings.binding.binding_id] = dict(grant, status="revoked")
    selected = {}

    def post(body):
        calls.append(body)
        envelope = json.loads(body["messages"][1]["content"])
        assert envelope["schema"] == OCCURRENCE_SCHEMA
        rows = []
        for source in envelope["untrusted_document_data"]["sources"]:
            candidate = source["occurrences"][0]
            selected[source["source_id"]] = candidate["quote"]
            value = candidate["span_id"]
            if fault == "foreign_id":
                value = "0" * 64
            elif fault == "disagree" and len(calls) == 2:
                value = None
            rows.append(
                dict(
                    source_index=source["source_index"],
                    dimensions=dict(entity=value, metric=None, reporting_period=None),
                )
            )
        return dict(
            id=f"occurrence-{len(calls)}",
            model=settings.model_id,
            usage=dict(prompt_tokens=20, completion_tokens=10),
            choices=[
                dict(finish_reason="stop", message=dict(content=json.dumps(dict(relations=rows))))
            ],
        )

    monkeypatch.setattr(runtime.relation_transport._probe, "_post", post)
    result = runtime.relations(claim, packet)
    if fault in {"revoked", "schema", "foreign_id"}:
        assert result is None
        if fault in {"revoked", "schema"}:
            assert calls == []
    else:
        assert len(calls) == usage["settled_calls"] == 3
        for source_id, roles in result.items():
            if fault == "disagree":
                assert all(ref is None for ref in roles.values())
            else:
                assert roles["entity"].quote == selected[source_id]
                assert roles["entity"].verification_state == "verified"
        assert len({row["request_id"] for row in runtime.relation_records[claim.claim_id]}) == 3
        assert runtime.relations(claim, packet) == result
        assert len(calls) == 3


def test_offline_pilot_pins_new_profiles_and_resume_preserves_snapshot(tmp_path, monkeypatch):
    import socket
    import sqlite3
    import sys

    from pypdf import PdfWriter

    def deny(*args, **kwargs):
        raise AssertionError("offline test must never connect")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(pilot.os, "environ", pilot.os.environ.copy())
    pdf = tmp_path / "sample.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf.open("wb") as stream:
        writer.write(stream)
    state = tmp_path / "new"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pilot",
            "--pdf",
            str(pdf),
            "--state",
            str(state),
            "--report-year",
            "2025",
            "--period-start",
            "2024-01-01",
            "--period-end",
            "2024-12-31",
            "--llm-provider",
            "openrouter",
            "--live-tagging",
            "--live-relations",
            "--relation-profile",
            "occurrence-v2",
            "--verify-claim-spans",
            "--claim-source-profile",
            "glyph-alignment-v1",
        ],
    )
    assert pilot.main() == 0
    original_settings = (state / "settings.json").read_bytes()
    manifest = json.loads((state / "pilot.json").read_text())
    assert manifest["relation_profile"] == "occurrence-v2"
    assert manifest["claim_source_profile"] == "glyph-alignment-v1"
    with sqlite3.connect(state / "state.sqlite3") as db:
        original_snapshot = db.execute("SELECT payload FROM run_snapshots").fetchone()[0]
    snapshot = json.loads(original_snapshot)
    assert snapshot["relation_settings"]["model_profile"] == OCCURRENCE_PROFILE
    assert snapshot["claim_source_policy"]["profile"] == "glyph-alignment-v1"
    monkeypatch.setattr(sys, "argv", ["pilot", "--state", str(state), "--resume"])
    assert pilot.main() == 0
    assert (state / "settings.json").read_bytes() == original_settings
    with sqlite3.connect(state / "state.sqlite3") as db:
        assert db.execute("SELECT payload FROM run_snapshots").fetchone()[0] == original_snapshot
