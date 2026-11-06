"""Frozen offline contracts for the WP-A4 extraction of tagging boundaries."""

import json
from dataclasses import asdict, replace
from hashlib import sha256
from unittest.mock import Mock

import pytest
from proofops.application.tagging.analysis_scope import read_runs
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

from tests.acceptance.test_tagging import execute, setup
from tests.integration.test_live_tagging_worker import configured as live_setup
from tests.integration.test_upstage_tagging_v4 import configured as wire_setup


def _accounting_spies(store, monkeypatch):
    spies = []
    for name in ("reserve_budget", "mark_dispatched", "record_usage"):
        spy = Mock(wraps=getattr(store, name))
        monkeypatch.setattr(store, name, spy)
        spies.append(spy)
    return spies


def test_tag_runs_bytes_identity_and_recovery(tmp_path, monkeypatch):
    inputs = setup(tmp_path)
    spies = _accounting_spies(inputs["usage_store"], monkeypatch)
    runs = execute(inputs)
    serialized = canonical_json([asdict(run) for run in runs])
    assert read_runs(json.loads(serialized)) == runs
    assert [run.replicate_id for run in runs] == [1, 2, 3]
    assert len({run.request.request_signature for run in runs}) == 3
    assert all(run.status == "needs_review" for run in runs)
    assert (
        sha256(serialized.encode()).hexdigest()
        == "fdac739e04419a6c0ce8ec1bf0ff5bdd7fa5d8df7b4bb6df0220470e1ee6d142"
    )
    assert (
        canonical_hash(inputs["invoke"].requests)
        == "3e3a46fc650b616c580f69e5eef1e6c1062fe16fd8772ea7fb5fafcdb00b8f98"
    )
    recovered = execute(inputs)
    assert len(inputs["invoke"].requests) == 3
    assert all(run.recovered for run in recovered)
    assert [run.semantic_hash for run in recovered] == [run.semantic_hash for run in runs]
    assert len(inputs["usage_store"].ledger(inputs["tenant_id"], runs[0].run_id)) == 3
    assert [spy.call_count for spy in spies] == [3, 3, 3]


def test_element_wire_and_restoration_bytes(tmp_path, monkeypatch):
    transport, probe, calls, request = wire_setup(tmp_path, monkeypatch)
    system, user, refs, authorization, schema = transport._wire_request(request)
    assert authorization.ready
    assert (
        canonical_hash([system, user, refs, schema])
        == "be2d595e9f7c98f52706b24ee62dc0efbec2a14a8ded81f00d5d08e51ee16b34"
    )
    result = transport.restore_payload(
        {
            "elements": [
                {
                    "element_id": "P2",
                    "state": "present",
                    "evidence_refs": [{"id": "e0", "quote": refs["e0"]["quote"]}],
                }
            ]
        },
        refs,
    )
    assert result["elements"][0]["evidence_refs"] == [refs["e0"]]
    assert calls == [] and probe.summary()["calls"] == 0


def test_source_receipt_bytes_and_budget_recovery(tmp_path, monkeypatch):
    runtime, claim, graph, calls, _, usage = live_setup(tmp_path, monkeypatch)
    spies = _accounting_spies(runtime.runner.store.usage, monkeypatch)
    result = runtime.preliminary(claim, graph)
    assert result is not None and result[0].track == "management"
    records = runtime.preliminary_records[claim.claim_id]
    receipts = [
        (runtime.receipts / "preliminary" / record["request_id"] / "request.json").read_bytes()
        for record in records
    ]
    assert [sha256(value).hexdigest() for value in receipts] == [
        "78849c2e32960f724006b6b2ca3295759035f34ac7820e82dfa8540d8d9f2d46",
        "9db4f25000f910d66f90ac85195c211c7d6e29707d0387623b1de348ca39c141",
        "5bb17eff722e5bfdcf3db29e1e8d6913de3f96bbcb99ab31d0e31df275a98c95",
    ]
    assert (
        canonical_hash(records)
        == "d1c43a1af7645d3bad7865778e1ac96a5aa53190d1cfc81ccbd693d6e54e8e0e"
    )
    assert len(calls) == usage["settled_calls"] == 3
    assert runtime.preliminary(claim, graph) == result
    assert receipts == [
        (runtime.receipts / "preliminary" / record["request_id"] / "request.json").read_bytes()
        for record in records
    ]
    assert len(calls) == 3
    ledger = runtime.runner.store.usage.ledger(graph.tenant_id, runtime.snapshot["run_id"])
    assert len(ledger) == 3 and all(row["usage"]["input_tokens"] == 20 for row in ledger)
    assert [spy.call_count for spy in spies] == [3, 3, 6]


@pytest.mark.parametrize("condition", ["revoked", "duplicate_provider", "invalid_response"])
def test_source_stop_contracts(tmp_path, monkeypatch, condition):
    runtime, claim, graph, calls, profiles, usage = live_setup(tmp_path, monkeypatch)
    if condition == "revoked":
        key = ("runtime", runtime.preliminary_settings.binding.binding_id)
        profiles[key] = dict(profiles[key], status="revoked")
    else:
        original = runtime.probe._post

        def post(body):
            result = original(body)
            if condition == "duplicate_provider":
                result["id"] = "same-provider-origin"
            else:
                result["choices"][0]["message"]["content"] = "{}"
            return result

        monkeypatch.setattr(runtime.probe, "_post", post)
    assert runtime.preliminary(claim, graph) is None
    expected_calls = {"revoked": 0, "duplicate_provider": 3, "invalid_response": 1}[condition]
    assert len(calls) == usage["settled_calls"] == expected_calls
    records = runtime.preliminary_records[claim.claim_id]
    assert (
        canonical_hash(records)
        == {
            "revoked": "8ed1d1719075eb7801e048603ce30f54a42e31b2f4bf8e5c33f9bbb83521bc35",
            "duplicate_provider": (
                "d1c43a1af7645d3bad7865778e1ac96a5aa53190d1cfc81ccbd693d6e54e8e0e"
            ),
            "invalid_response": "49d33e283115e6014e01e66e0d8e6e30780fe156935dd79e0c529f168e69f0b3",
        }[condition]
    )
    assert len(records) == (3 if condition == "duplicate_provider" else 1)


def test_failed_element_retains_three_replicas(tmp_path):
    inputs = setup(tmp_path)
    inputs["invoke"].fail = (1,)
    runs = execute(inputs)
    assert [run.replicate_id for run in runs] == [1, 2, 3]
    assert len(inputs["invoke"].requests) == 3
    assert runs[0].errors == ("MODEL_UNAVAILABLE",)
    assert replace(runs[0], recovered=True).semantic_hash == runs[0].semantic_hash


def test_existing_imports_alias_the_application_contracts():
    from proofops.adapters.cache import aws
    from proofops.application.ports import cache
    from proofops.application.tagging import analysis_scope, contracts, preliminary, service

    for name in ("CacheNamespace", "CacheRequest", "cache_request"):
        assert getattr(aws, name) is getattr(cache, name)
    for name in ("TaggingSettings", "RawTagResponse", "TagRun", "output_reservation_tokens"):
        assert getattr(service, name) is getattr(contracts, name)
    assert analysis_scope.read_runs is contracts.read_runs
    assert preliminary.PreliminaryClassification is contracts.PreliminaryClassification
