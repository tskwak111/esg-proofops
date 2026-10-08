import json
from copy import deepcopy

import pytest

from evaluation.local_upstage_pilot import live_tagging_settings
from tests.integration.test_upstage_tagging import configured

PROFILE = "upstage-compact-element-consistency-v6"


def packet(request):
    from dataclasses import asdict

    from tests.acceptance.test_binding import corpus

    _, _, refs = corpus()
    user = json.loads(request["user_json"])
    data = user["untrusted_document_data"]
    data["claim_source_refs"] = [asdict(refs[0])]
    data["evidence_candidates"] = [
        dict(
            source_id=r.source_id,
            source_scope="local_claim",
            allowed_elements=["P1"],
            source_refs=[asdict(r)],
        )
        for r in refs[:2]
    ]
    request["user_json"] = json.dumps(user)
    return data


def test_profile_is_opt_in_and_hash_separated():
    old = live_tagging_settings(6, model_id="openai/gpt-6-luna")
    new = live_tagging_settings(6, model_id="openai/gpt-6-luna", element_consistency=True)
    assert old["tagging_settings"]["model_profile"] == "upstage-compact-source-quotes-v4"
    assert new["tagging_settings"]["model_profile"] == PROFILE
    from proofops.domain.provenance import canonical_hash

    assert canonical_hash(old["tagging_settings"]) != canonical_hash(new["tagging_settings"])


def test_consistency_wire_order_and_element_lists(tmp_path, monkeypatch):
    adapter, _, calls, request = configured(tmp_path, monkeypatch, model_profile=PROFILE)
    packet(request)
    untouched = deepcopy(request)
    _, user, refs, _, schema = adapter._wire_request(request)
    changed = json.loads(request["user_json"])
    changed["untrusted_document_data"]["evidence_candidates"].reverse()
    request2 = request | {"user_json": json.dumps(changed)}
    assert adapter._wire_request(request2)[1:3] == (user, refs)
    assert request == untouched
    data = json.loads(user)["untrusted_document_data"]
    assert data["element_evidence_ids"]["P1"]
    assert data["element_evidence_ids"]["P2"] == []
    assert json.loads(schema)["$defs"]["Element"]["allOf"]
    assert not calls


def test_consistency_preserves_literal_quote_guard(tmp_path, monkeypatch):
    adapter, _, _, request = configured(tmp_path, monkeypatch, model_profile=PROFILE)
    packet(request)
    system, _, refs, _, _ = adapter._wire_request(request)
    ref = refs["e0"]
    assert adapter._restore_ref({"id": "e0", "quote": ref["quote"]}, refs) == ref
    with pytest.raises(ValueError):
        adapter._restore_ref({"id": "e0", "quote": "invented source"}, refs)
    assert "unknown" in system and "three" in system


def test_consistency_scopes_trusted_cards_and_keeps_other_rules(tmp_path, monkeypatch):
    from dataclasses import replace

    from proofops.application.preflight import Check, Preflight
    from proofops.domain.provenance import canonical_hash

    adapter, _, _, request = configured(tmp_path, monkeypatch, model_profile=PROFILE)
    packet(request)
    marker = "This rule reference is tagging guidance, not an approval of the draft rulepack.\n"
    reference = {
        "elements": [{"id": f"P{i}", "name": f"card{i}"} for i in range(1, 7)]
        + [{"id": "M1", "name": "unused"}]
    }
    settings = replace(
        adapter._settings, system_prompt=marker + json.dumps(reference) + "\nKEEP GUARDS"
    )
    adapter._settings = settings
    request["system_prompt"] = settings.system_for_track("performance", None)
    names = (
        "runtime_approval",
        "consent_approval",
        "model_binding",
        "document_scope",
        "document_rights",
        "data_consent",
        "tagging_settings",
        "selected_document_rights",
    )
    adapter._authorize = lambda s, r: Preflight(
        True,
        tuple(Check(n, "pass", "fixture") for n in names),
        canonical_hash("fixture"),
        "2026-10-09",
    )
    system = adapter._wire_request(request)[0]
    assert "unused" not in system and "card1" in system and "card6" in system
    assert "KEEP GUARDS" in system
    assert adapter.TRANSPORT_VERSION == "compact-element-consistency-v6"


def test_q2_reservation_enforces_shared_cap_and_retains_uncertainty(tmp_path, monkeypatch):
    import sqlite3

    from evaluation import r108_perf_q2 as q2

    monkeypatch.setattr(q2, "ROOT", tmp_path)
    monkeypatch.setattr(q2, "SPEND", tmp_path / "spend.json")
    for provider in ("openrouter", "upstage"):
        path = tmp_path / ".local" / provider / "budget.sqlite3"
        path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE probe_calls (request_id TEXT, committed TEXT, receipt TEXT)")
    q2.write(q2.SPEND, {"cumulative_usd": "9.71", "limit_usd": "10"})
    with pytest.raises(ValueError, match="R108_BUDGET_EXHAUSTED"):
        q2.reserve()
    assert json.loads(q2.SPEND.read_text())["cumulative_usd"] == "9.71"
    q2.write(q2.SPEND, {"cumulative_usd": "1", "limit_usd": "10"})
    q2.reserve()
    assert json.loads(q2.SPEND.read_text())["cumulative_usd"] == "1.30"
    with pytest.raises(ValueError, match="Q2_ALREADY_RESERVED"):
        q2.reserve()
    q2.reserve({"committed_usd": "0.02", "status": "stopped", "new_unsettled_usd": "0.02"})
    data = json.loads(q2.SPEND.read_text())
    assert data["cumulative_usd"] == "1.02"
    assert data["executions"][0]["new_unsettled_usd"] == "0.02"
