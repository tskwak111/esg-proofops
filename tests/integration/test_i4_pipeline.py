import json
from dataclasses import replace

import pytest
from proofops.application.tagging.finals_i4 import K4_ELEMENTS
from proofops.application.tagging.k4_contract import RESPONSE_POLICY

from tests.integration.test_upstage_tagging_v4 import configured


@pytest.mark.parametrize("bad", ["identity", "extra", "missing"])
def test_i4_full_transport_rejects_invalid_raw_before_server_identity(tmp_path, monkeypatch, bad):
    adapter, probe, calls, request = configured(tmp_path, monkeypatch)
    authorization = adapter._authorize(adapter._settings, request)
    settings = replace(adapter._settings, system_prompt=K4_ELEMENTS)
    adapter._settings = settings
    adapter._authorize = lambda *a: authorization
    request["system_prompt"] = settings.system_for_track("performance", None)
    user = json.loads(request["user_json"])
    user["untrusted_document_data"]["tagging_response_policy"] = RESPONSE_POLICY
    request["user_json"] = json.dumps(user)
    system, wire, _, _, schema = adapter._wire_request(request)
    assert "exactly claim_id" not in system
    assert "tagging_response_policy" not in json.loads(wire)["untrusted_document_data"]
    assert "claim_id" not in json.loads(schema)["properties"]
    payload = dict(
        track="performance",
        safe_harbor_category=None,
        superlative_quote=None,
        warnings=[],
        elements=[
            dict(
                element_id=e,
                state="unknown",
                evidence_refs=[],
                normalized_value=None,
                credited_from=None,
                reason_code=None,
            )
            for e in ("G1", "P2")
        ],
    )
    if bad == "identity":
        payload["claim_id"] = request["claim_id"]
    elif bad == "extra":
        payload["invented"] = True
    else:
        payload.pop("track")

    def post(body):
        calls.append(body)
        return dict(
            id="i4-fixture",
            model=probe.model,
            usage=dict(prompt_tokens=20, completion_tokens=10),
            choices=[dict(finish_reason="stop", message=dict(content=json.dumps(payload)))],
        )

    monkeypatch.setattr(probe, "_post", post)
    response = adapter.invoke(request)
    assert response.raw_response_json is None
    assert json.loads(response.provider_response_json)["content"] == json.dumps(payload)
    assert len(calls) == 1


def test_i4_new_local_run_and_resume_pin_matching_prompts(tmp_path, monkeypatch):
    import os
    import sqlite3
    import sys

    from proofops.application.analysis_profile import FINALS_I4_POLICY
    from proofops.application.tagging.finals_i4 import K4_PRELIMINARY, PROFILE
    from proofops.domain.provenance import canonical_hash

    from evaluation import local_upstage_pilot as pilot
    from tests.integration.test_finals_candidate_profile import create_argv

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(
        sys,
        "argv",
        create_argv(tmp_path)
        + [
            "--analysis-profile",
            "finals-unattended-v2",
            "--analysis-policy-sha256",
            canonical_hash(FINALS_I4_POLICY),
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
    assert settings["tagging_prompt_profile"] == PROFILE
    assert settings["extraction_i4_identity"] is True
    assert settings["preliminary_settings"]["system_prompt"] == K4_PRELIMINARY
    assert settings["tagging_settings"]["system_prompt"] == K4_ELEMENTS
    from proofops_api.local_runtime import load_local_runtime

    environment = dict(
        LOCAL_PARSER_PROFILE_PATH=str(state / "parser.json"),
        LOCAL_RUN_SETTINGS_PATH=str(state / "settings.json"),
        LOCAL_EXTRACTION_MODE="upstage_probe",
        LOCAL_TAGGING_MODE="upstage_local",
        LOCAL_LLM_PROVIDER="openai",
    )
    assert load_local_runtime(environment)["analysis_policy_sha256"] == canonical_hash(
        FINALS_I4_POLICY
    )
    missing = settings.copy()
    missing.pop("extraction_i4_identity")
    wrong_path = state / "missing-selection-mode.json"
    wrong_path.write_text(json.dumps(missing))
    with pytest.raises(ValueError):
        load_local_runtime(environment | dict(LOCAL_RUN_SETTINGS_PATH=str(wrong_path)))
    with sqlite3.connect(state / "state.sqlite3") as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    assert snapshot["analysis_profile_policy"] == FINALS_I4_POLICY
    assert snapshot["analysis_profile_policy_sha256"] == canonical_hash(FINALS_I4_POLICY)
    before = {p: p.read_bytes() for p in (state / "settings.json", state / "pilot.json")}
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert all(p.read_bytes() == raw for p, raw in before.items())


def test_i4_openai_receives_final_schema_before_response_cache(tmp_path, monkeypatch):
    from proofops.adapters.local.openai import MODEL, OpenAIProbe

    adapter, _, _, request = configured(tmp_path, monkeypatch)
    authorization = adapter._authorize(adapter._settings, request)
    settings = replace(adapter._settings, system_prompt=K4_ELEMENTS, model_id=MODEL)
    adapter._settings = settings
    adapter._authorize = lambda *a: authorization
    adapter._probe = OpenAIProbe("offline-not-a-key", tmp_path / "openai.sqlite3")
    request.update(model_id=MODEL, system_prompt=settings.system_for_track("performance", None))
    user = json.loads(request["user_json"])
    user["untrusted_document_data"]["tagging_response_policy"] = RESPONSE_POLICY
    request["user_json"] = json.dumps(user)
    captured = []

    def complete(*args, **kwargs):
        captured.append(kwargs.get("schema_json"))
        raise ValueError("offline-schema-probe")

    monkeypatch.setattr(adapter._probe, "complete", complete)
    adapter.invoke(request)
    assert len(captured) == 1 and captured[0] is not None
    assert "claim_id" not in json.loads(captured[0])["properties"]
