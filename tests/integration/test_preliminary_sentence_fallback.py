import json
from dataclasses import asdict, replace

import pytest
from proofops.application.registry import artifact_sha256
from proofops.application.tagging import preliminary as p
from proofops.domain.provenance import canonical_hash
from proofops_worker import live_tagging

from tests.integration.test_live_tagging_worker import configured


@pytest.mark.parametrize("missing", [False, "missing", "bounded_away", "unverified"])
@pytest.mark.parametrize("fault", [None, "disagree", "foreign_quote", "revoked"])
def test_fallback_dispatches_only_verified_inputs(tmp_path, monkeypatch, missing, fault):
    old, claim, graph, calls, profiles, usage = configured(tmp_path, monkeypatch, context=True)
    settings = replace(
        old.preliminary_settings,
        model_profile=p.SENTENCE_FALLBACK_PROFILE,
        system_prompt=p.SENTENCE_FALLBACK_SYSTEM_PROMPT,
    )
    grant = old.snapshot["preliminary_runtime"] | dict(
        tagging_settings_sha256=canonical_hash(asdict(settings))
    )
    profiles["runtime", settings.binding.binding_id] = grant
    snapshot = {k: v for k, v in old.snapshot.items() if k != "input_hash"}
    snapshot.update(
        preliminary_settings=asdict(settings),
        preliminary_settings_hash=canonical_hash(asdict(settings)),
        preliminary_runtime=grant,
        preliminary_runtime_artifact_hash=artifact_sha256(grant),
    )
    snapshot["input_hash"] = canonical_hash(snapshot)
    runtime = live_tagging.LiveTaggingRuntime(
        old.runner,
        snapshot,
        graph,
        old.lease,
        usage,
        probe=old.preliminary_transport._probe,
        ledger=old.ledger,
        receipts=old.receipts,
    )
    if missing:
        original = p.preliminary_table_request

        def omit(*args, **kwargs):
            packet = original(*args, **kwargs)
            packet["untrusted_document_data"]["context_blocks"] = []
            return packet

        if missing == "bounded_away":

            def bounded_away(packet):
                packet["untrusted_document_data"]["context_blocks"] = []
                return packet

            monkeypatch.setattr(runtime.preliminary_transport, "bound_context", bounded_away)
        elif missing == "unverified":

            def unverified(*args, **kwargs):
                packet = original(*args, **kwargs)
                for block in packet["untrusted_document_data"]["context_blocks"]:
                    block["quality"] = "unverified"
                    block["source_ref"]["verification_state"] = "unverified"
                return packet

            monkeypatch.setattr(live_tagging, "preliminary_table_request", unverified)
        else:
            monkeypatch.setattr(live_tagging, "preliminary_table_request", omit)
    if fault == "revoked":
        profiles["runtime", settings.binding.binding_id] = grant | dict(status="revoked")

    def post(body):
        calls.append(body)
        output = dict(
            claim_id=claim.claim_id,
            track="management",
            safe_harbor_category=None,
            track_confidence=0.8,
            dimensions=dict(entity=None, metric=None, reporting_period=None),
        )
        if fault == "disagree" and len(calls) == 2:
            output["track"] = "performance"
        if fault == "foreign_quote":
            output["dimensions"]["entity"] = dict(source_index=0, quote="another company")
        return dict(
            id=f"q9-{len(calls)}",
            model=settings.model_id,
            usage=dict(prompt_tokens=20, completion_tokens=10),
            choices=[dict(finish_reason="stop", message=dict(content=json.dumps(output)))],
        )

    monkeypatch.setattr(runtime.preliminary_transport._probe, "_post", post)
    assert (runtime.preliminary(claim, graph) is not None) is (fault is None)
    assert len(calls) == (0 if fault == "revoked" else 1 if fault == "foreign_quote" else 3)
    if calls:
        packet = json.loads(calls[0]["messages"][1]["content"])
        if missing:
            legacy = p.preliminary_table_request(
                claim, graph, tenant_id=claim.tenant_id, role_resolution=True
            )
            assert (
                packet["untrusted_document_data"]["sources"]
                == legacy["untrusted_document_data"]["sources"]
            )
            assert packet["untrusted_document_data"]["context_blocks"] == []
            assert packet["table_policy"] == legacy["table_policy"]
            assert packet["prompt_sha256"] == canonical_hash(p.SENTENCE_FALLBACK_BASE_PROMPT)
            assert (
                calls[0]["messages"][0]["content"]
                == replace(settings, system_prompt=p.SENTENCE_FALLBACK_BASE_PROMPT).rendered_system
            )
        else:
            assert p.sentence_context_ready(claim, packet)
            assert packet["prompt_sha256"] == canonical_hash(p.SENTENCE_FALLBACK_SYSTEM_PROMPT)
        assert all(b["messages"] == calls[0]["messages"] for b in calls)


def test_pilot_fallback_is_opt_in():
    from evaluation.local_upstage_pilot import live_tagging_settings

    flags = dict(
        preliminary_context=True,
        preliminary_table_context=True,
        preliminary_table_role=True,
        preliminary_goal_role=True,
        preliminary_actor_role=True,
        preliminary_sentence_context=True,
    )
    assert (
        live_tagging_settings(9, **flags)["preliminary_settings"]["model_profile"]
        == p.SENTENCE_CONTEXT_PROFILE
    )
    assert (
        live_tagging_settings(9, **flags, preliminary_sentence_fallback=True)[
            "preliminary_settings"
        ]["model_profile"]
        == p.SENTENCE_FALLBACK_PROFILE
    )
    with pytest.raises(ValueError):
        live_tagging_settings(9, preliminary_sentence_fallback=True)


def test_resume_cannot_add_sentence_fallback(tmp_path, monkeypatch, capsys):
    import sys

    from evaluation import local_upstage_pilot as pilot

    state = tmp_path / "legacy"
    state.mkdir()
    (state / "pilot.json").write_text(json.dumps({"source_path": "/tmp/example.pdf"}))
    monkeypatch.setattr(
        sys, "argv", ["pilot", "--resume", "--state", str(state), "--preliminary-sentence-fallback"]
    )
    with pytest.raises(SystemExit):
        pilot.main()
    assert "--resume cannot add sentence fallback" in capsys.readouterr().err


def test_resume_restores_sentence_fallback():
    from evaluation.local_upstage_pilot import apply_resume_metadata
    from tests.unit.test_extraction_source_id_wiring import _args

    args = _args()
    apply_resume_metadata(
        args, {"source_path": "/tmp/example.pdf", "preliminary_sentence_fallback": True}
    )
    assert args.preliminary_sentence_fallback is True
    legacy_args = _args()
    apply_resume_metadata(legacy_args, {"source_path": "/tmp/example.pdf"})
    assert legacy_args.preliminary_sentence_fallback is False
