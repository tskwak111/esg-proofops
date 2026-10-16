import json
from copy import deepcopy

import pytest
from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.claims import ExtractionOutputError
from proofops_agent.fxg_extraction import plan


class Probe:
    request_body = OpenAIProbe.request_body
    response_policy = {"enabled": True}
    max_request_bytes = OpenAIProbe.max_request_bytes


def wire():
    return {
        "request_id": "11111111-1111-4111-8111-111111111111",
        "untrusted_document_data": {
            "source_sentences": [{"sentence_id": "c7", "text": "We reduced emissions."}],
            "context_blocks": [
                {"context_index": i, "text": "한글" * 120, "source_ref": {"bbox": [i, 2, 3, 4]}}
                for i in range(16)
            ],
            "candidate_contexts": [{"role": "unit", "text": "tCO2e"}],
        },
    }


def test_exact_provider_limit_and_whole_context_blocks():
    original = wire()
    saved = deepcopy(original)
    chunks = plan(Probe(), "instruction " * 680, original, max_tokens=1024)
    assert len(chunks) > 1
    assert original == saved
    contexts = []
    for chunk in chunks:
        body = Probe().request_body(
            "instruction " * 680,
            json.dumps(chunk, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            request_id=chunk["request_id"],
            json_mode=True,
        )
        assert len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()) <= 16384
        data = chunk["untrusted_document_data"]
        assert data["source_sentences"] == original["untrusted_document_data"]["source_sentences"]
        contexts.extend(data["context_blocks"])
    assert contexts == original["untrusted_document_data"]["context_blocks"]
    assert plan(Probe(), "instruction " * 680, original, max_tokens=1024) == chunks


def test_candidate_boundaries_and_global_selector_parent_indexes():
    value = wire()
    data = value["untrusted_document_data"]
    data["context_blocks"] = []
    data["source_sentences"] = [
        {"sentence_id": f"c{i}", "text": "한글" * 400, "parent_context_ids": [0]} for i in range(8)
    ]
    chunks = plan(Probe(), "instruction " * 680, value, max_tokens=1024)
    assert len(chunks) > 1
    assert [e for c in chunks for e in c["untrusted_document_data"]["source_sentences"]] == data[
        "source_sentences"
    ]
    assert all(
        c["untrusted_document_data"]["candidate_contexts"] == data["candidate_contexts"]
        for c in chunks
    )


def test_fitting_wire_is_identical_and_oversized_single_block_is_unknown():
    value = wire()
    value["untrusted_document_data"]["context_blocks"] = []
    assert plan(Probe(), "system", value, max_tokens=1024) == [value]
    value["untrusted_document_data"]["source_sentences"][0]["text"] = "한" * 17000
    with pytest.raises(ExtractionOutputError, match="EXTRACTION_FXG_BLOCK_TOO_LARGE"):
        plan(Probe(), "system", value, max_tokens=1024)


class Selector(Probe):
    model = "gpt-6-luna"
    wire_policy_version = 2

    def __init__(self, bad=False):
        self.calls = []
        self.bad = bad

    def complete(self, system, user_json, **kwargs):
        self.request_body(system, user_json, **kwargs)
        data = json.loads(user_json)
        self.calls.append(data)
        ids = [e["sentence_id"] for e in data["untrusted_document_data"]["source_sentences"]]
        return {"content": json.dumps({"sentence_ids": ["c11"] if self.bad else ids})}


def extractor_case(tmp_path, *, bad=False, text=None, enabled=True):
    from dataclasses import asdict

    from proofops_agent.upstage_extraction import UpstageClaimExtractor

    from tests.integration.test_upstage_extraction import packet

    probe = Selector(bad)
    extractor = UpstageClaimExtractor(
        probe,
        tmp_path,
        extraction_source_ids=True,
        extraction_i4_identity=True,
        extraction_fxg_split=enabled,
    )
    data = packet(
        text or " ".join(f"Company {i} " + "reduces emissions " * 110 + "." for i in range(12))
    )
    data["extraction_profile"] = asdict(extractor.profile)
    return extractor, data, probe


def test_real_extractor_splits_resolves_replays_and_binds_every_child(tmp_path):
    extractor, packet, probe = extractor_case(tmp_path)
    result = extractor.extract(packet)
    assert len(result["spans"]) == 12 and len(probe.calls) > 1
    for span in result["spans"]:
        assert (
            span["quote"]
            == packet["untrusted_document_data"]["text"][span["char_start"] : span["char_end"]]
        )
    calls = len(probe.calls)
    assert extractor.extract(packet) == result
    assert len(probe.calls) == calls
    assert extractor.usage_checkpoint() == calls
    child = next(tmp_path.glob("*/*/result.json"))
    value = json.loads(child.read_text())
    value["spans"][0]["quote"] = "forged"
    child.chmod(0o600)
    child.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="EXTRACTION_FXG_RECEIPT_MISMATCH"):
        extractor.extract(packet)
    assert len(probe.calls) == calls


def test_chunk_cannot_select_valid_global_id_outside_its_own_request(tmp_path):
    extractor, packet, probe = extractor_case(tmp_path, bad=True)
    with pytest.raises(ExtractionOutputError, match="EXTRACTION_FXG_CHUNK_INVALID"):
        extractor.extract(packet)
    assert "c11" not in [
        e["sentence_id"] for e in probe.calls[0]["untrusted_document_data"]["source_sentences"]
    ]
    with pytest.raises(ExtractionOutputError, match="EXTRACTION_FXG_CHUNK_INVALID"):
        extractor.extract(packet)
    assert len(probe.calls) == 1


def test_normal_result_and_legacy_overlimit_behavior_are_unchanged(tmp_path):
    old, packet, _ = extractor_case(tmp_path / "old", text="We reduce emissions.", enabled=False)
    new, new_packet, probe = extractor_case(tmp_path / "new", text="We reduce emissions.")
    assert old.profile != new.profile
    assert new.extract(new_packet) == old.extract(packet)
    assert len(probe.calls) == 1 and not list((tmp_path / "new").rglob("fxg-split.json"))
    legacy, packet, _ = extractor_case(tmp_path / "large-old", enabled=False)
    with pytest.raises(ValueError, match="PROBE_REQUEST_TOO_LARGE"):
        legacy.extract(packet)


def test_each_paid_child_is_fenced_and_partial_replay_never_repeats_it(tmp_path):
    from proofops.application.ingest.fxg_wire import dispatch_scope

    extractor, packet, probe = extractor_case(tmp_path)
    attempts = 0

    def guard():
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            raise ValueError("BUDGET_EXHAUSTED")

    with dispatch_scope(guard), pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        extractor.extract(packet)
    assert len(probe.calls) == extractor.usage_checkpoint() == 1
    first = probe.calls[0]["request_id"]
    result = extractor.extract(packet)
    assert len(result["spans"]) == 12
    assert [c["request_id"] for c in probe.calls].count(first) == 1


def test_transport_failure_is_retained_without_duplicate_billing(tmp_path):
    extractor, packet, probe = extractor_case(tmp_path)
    calls = []

    def fail(*a, **kw):
        calls.append(kw["request_id"])
        raise TimeoutError

    probe.complete = fail
    with pytest.raises(ValueError, match="UPSTREAM_UNAVAILABLE"):
        extractor.extract(packet)
    with pytest.raises(ExtractionOutputError, match="PREVIOUS_TRANSPORT_FAILED"):
        extractor.extract(packet)
    assert len(calls) == extractor.usage_checkpoint() == 1


def test_invalid_transport_and_non_object_payload_are_unknown(tmp_path):
    for index, response in enumerate(([], {"content": "[]"})):
        extractor, packet, probe = extractor_case(tmp_path / str(index))
        probe.complete = lambda *a, **kw: response
        with pytest.raises(ExtractionOutputError, match="EXTRACTION_FXG_CHUNK_INVALID"):
            extractor.extract(packet)


def test_disagreement_across_context_parts_is_held_as_unknown(tmp_path):
    from uuid import uuid4

    from proofops.domain.provenance import canonical_hash
    from proofops_agent.fxg_extraction import extract_parts

    extractor, packet, probe = extractor_case(tmp_path, text="We reduced emissions.")
    system, user, _ = extractor._source_id_wire(
        packet, packet["untrusted_document_data"]["text"], canonical_hash(packet), None, None
    )
    parts = [user | dict(request_id=str(uuid4())) for _ in range(2)]
    responses = iter((dict(content='{"sentence_ids":["c0"]}'), dict(content='{"sentence_ids":[]}')))
    probe.complete = lambda *a, **kw: next(responses)
    result = extract_parts(extractor, packet, system, user, parts, context_graph=None)
    assert result["spans"] == []
    saved = json.loads((tmp_path / user["request_id"] / "result.json").read_text())
    assert saved["diagnostics"]["fxg_context_disagreements"] == ["c0"]


def test_worker_enforces_physical_cap_and_rechecks_authority(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from proofops_worker import extract_runner

    leases, authorizations = [], []
    monkeypatch.setattr(extract_runner, "fence_provider_call", lambda *a: leases.append("checked"))

    def authorize(**kwargs):
        authorizations.append(kwargs)
        return SimpleNamespace(ready=True)

    monkeypatch.setattr(extract_runner, "check_local_upstage_binding", authorize)
    runner = SimpleNamespace(extractor=SimpleNamespace(_fxg_split=True), clock=lambda: 1)
    snapshot = dict(runtime={}, consent={}, run_id="run")
    graph = SimpleNamespace(tenant_id="tenant", source_sha256="source")
    profile = SimpleNamespace(model_sha256="model")
    guard = extract_runner.fxg_dispatch_guard(runner, object(), {}, snapshot, graph, profile, 3)

    def call(_):
        try:
            guard()
            return "allowed"
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(call, range(8)))
    assert outcomes.count("allowed") == len(leases) == len(authorizations) == 3
    assert outcomes.count("BUDGET_EXHAUSTED") == 5
    guard = extract_runner.fxg_dispatch_guard(runner, object(), {}, snapshot, graph, profile, 3)
    monkeypatch.setattr(
        extract_runner, "check_local_upstage_binding", lambda **kw: SimpleNamespace(ready=False)
    )
    with pytest.raises(ValueError, match="LOCAL_TEST_AUTHORIZATION_INVALID"):
        guard()
