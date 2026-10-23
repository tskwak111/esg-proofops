"""Freeze extraction continuation, fencing, accounting and checkpoint boundaries."""

import json
from types import SimpleNamespace

import pytest
from proofops.application.claims import ExtractionOutputError
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json
from proofops_worker import extract_runner as module

from tests.acceptance.test_upload import TENANT
from tests.integration.test_local_extract_runner import extract_message
from tests.integration.test_real_extract_runner import inject_graph, real_setup


def packet(source_id):
    return {
        "untrusted_document_data": {
            "source_id": source_id,
            "kind": "paragraph",
            "text": "carbon emissions fell.",
        }
    }


def test_continuation_replay_bytes_and_failed_receipt():
    value = packet("prior")
    payload = {"spans": []}
    raw = canonical_json(payload)
    live = SimpleNamespace(extract=lambda _: pytest.fail("replay dispatched"))
    receipt = {"packet_sha256": canonical_hash(value), "raw_response_json": raw}
    continuing = module._ContinuingExtractor(live, None, {"prior": receipt}, set(), 1)
    assert canonical_json(continuing.extract(value)).encode() == b'{"spans":[]}'
    assert continuing.calls == 0 and continuing.replayed == {"prior"}
    failed = module._ContinuingExtractor(live, None, {}, set(), 1, prior_failed={"prior": receipt})
    with pytest.raises(ExtractionOutputError, match="^PREVIOUS_EXTRACTION_FAILED$"):
        failed.extract(value)
    assert failed.calls == 0


def test_continuation_stop_latches_without_retry():
    calls = []

    def invoke(value):
        calls.append(value)
        raise ValueError("BUDGET_EXHAUSTED")

    continuing = module._ContinuingExtractor(
        SimpleNamespace(extract=invoke), None, {}, {"a", "b"}, 2
    )
    first = continuing.extract(packet("a"))
    second = continuing.extract(packet("b"))
    expected = (
        b'{"spans":[{"char_end":22,"char_start":0,"kind":"unknown",'
        b'"quote":"carbon emissions fell.","reason":"extraction_budget_stop","topic_ids":[]}]}'
    )
    assert canonical_json(first).encode() == expected
    assert canonical_json(second).encode() == expected
    assert len(calls) == continuing.calls == 1
    assert (continuing.stop_code, continuing.stop_source) == ("BUDGET_EXHAUSTED", "a")


def test_fence_precedes_authorization_and_budget(monkeypatch):
    events = []
    runner = SimpleNamespace(
        extractor=SimpleNamespace(_fxg_split=True),
        clock=lambda: 10,
        store=SimpleNamespace(
            jobs=SimpleNamespace(
                can_call=lambda *a, **k: events.append("can_call") or True,
                heartbeat=lambda *a, **k: events.append("heartbeat"),
            )
        ),
    )
    monkeypatch.setattr(module, "fresh_execution_enabled", lambda: False)
    monkeypatch.setattr(
        module,
        "check_local_upstage_binding",
        lambda **k: events.append("authorize") or SimpleNamespace(ready=True),
    )
    guard = module.fxg_dispatch_guard(
        runner,
        None,
        {},
        {"runtime": {}, "consent": {}, "run_id": "run"},
        SimpleNamespace(tenant_id=TENANT, source_sha256="a" * 64),
        SimpleNamespace(model_sha256="b" * 64),
        1,
    )
    guard()
    with pytest.raises(ValueError, match="^BUDGET_EXHAUSTED$"):
        guard()
    assert events == ["can_call", "heartbeat", "authorize"]


def test_provider_settlement_precedes_checkpoint_and_duplicate_is_immutable(tmp_path, monkeypatch):
    service, run_id, runner, now, probe = real_setup(tmp_path, monkeypatch, limit=1)
    inject_graph(monkeypatch, service, run_id, ["paragraph", "paragraph"])
    message = extract_message(service, run_id, now[0])
    events = []
    for target, name in [
        (probe._client, "_reserve"),
        (probe._client, "_post"),
        (probe._client, "_settle"),
        (service.store.jobs, "commit_job"),
    ]:
        original = getattr(target, name)

        def recorded(*args, _name=name, _original=original, **kwargs):
            events.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(target, name, recorded)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    assert events == ["_reserve", "_post", "_settle", "commit_job"]
    checkpoint = service.store.jobs.read_checkpoint(message)
    assert checkpoint == canonical_json(json.loads(checkpoint)).encode()
    digest = canonical_hash(json.loads(checkpoint))
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "pending_downstream"
    assert service.store.jobs.read_checkpoint(message) == checkpoint
    assert canonical_hash(json.loads(checkpoint)) == digest
    assert len(probe.calls) == service.cost(TENANT, run_id)["attempt_count"] == 1
