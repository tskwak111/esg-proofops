"""S_APT: retained bytes, source validation order and paid-call lifecycle."""

from dataclasses import asdict, replace
from hashlib import sha256

import pytest
from proofops.application.tagging import preliminary, relations, service
from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

from tests.acceptance.test_citations import TENANT
from tests.acceptance.test_preliminary import context_corpus
from tests.acceptance.test_tagging import execute, setup


def preliminary_snapshot():
    graph, claim, _ = context_corpus()
    packet = preliminary.preliminary_request(claim, graph, tenant_id=TENANT)
    raw = dict(
        claim_id=claim.claim_id,
        track="performance",
        track_confidence=0.8,
        safe_harbor_category=None,
        dimensions=dict(entity=None, metric=None, reporting_period=None),
    )
    result = preliminary.validate_preliminary(claim, graph, raw, tenant_id=TENANT)
    prompts = {k: v for k, v in vars(preliminary).items() if k.isupper() and isinstance(v, str)}
    classification = dict(
        track=asdict(result.track),
        claim=asdict(result.context.claim),
        dimensions=dict(result.context.dimensions),
        track_confidence=result.track_confidence,
        safe_harbor_category=result.safe_harbor_category,
    )
    return canonical_hash(packet), canonical_hash(classification), canonical_hash(prompts)


def test_preliminary_packet_classification_and_prompt_pins():
    assert preliminary_snapshot() == PRELIMINARY_PINS


def test_source_checks_precede_response_mapping_reads():
    graph, claim, _ = context_corpus()

    class UnreadableResponse(dict):
        def __iter__(self):
            pytest.fail("response read before source validation")

        def __getitem__(self, key):
            pytest.fail("response read before source validation")

    with pytest.raises(DomainValidationError, match="source identity or quality mismatch"):
        preliminary.validate_preliminary(
            replace(claim, source_quality="unverified"),
            graph,
            UnreadableResponse(),
            tenant_id=TENANT,
        )
    with pytest.raises(DomainValidationError):
        relations.validate_relations(
            (replace(claim.source_refs[0], quote="wrong"),),
            graph,
            UnreadableResponse(),
            tenant_id=TENANT,
        )


def test_replica_bytes_recovery_and_cost_call_order(tmp_path, monkeypatch):
    inputs = setup(tmp_path)
    events, stored = [], []
    for name in ("reserve_budget", "record_usage", "accept_binding", "verify_source_ref"):
        original = getattr(service, name)

        def tracked(*args, _name=name, _original=original, **kwargs):
            events.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(service, name, tracked)
    for name in ("put_raw", "put_guarded"):
        original = getattr(inputs["cache"], name)

        def stored_call(request, value, _name=name, _original=original):
            events.append(_name)
            stored.append((_name, request.request_signature, sha256(value).hexdigest()))
            return _original(request, value)

        monkeypatch.setattr(inputs["cache"], name, stored_call)
    original_invoke = inputs["invoke"]

    def invoke(request):
        events.append("invoke")
        return original_invoke(request)

    inputs["invoke"] = invoke
    runs = execute(inputs)
    assert tuple(run.replicate_id for run in runs) == (1, 2, 3)
    assert canonical_hash([asdict(run) for run in runs]) == RUNS_PIN
    assert canonical_hash(stored) == STORED_PIN
    assert canonical_hash(events) == EVENTS_PIN
    assert [e for e in events if e in {"reserve_budget", "invoke", "record_usage", "put_raw"}] == [
        "reserve_budget",
        "invoke",
        "record_usage",
        "put_raw",
    ] * 3
    events.clear()
    recovered = execute(inputs)
    assert all(run.recovered for run in recovered)
    assert [run.semantic_hash for run in recovered] == [run.semantic_hash for run in runs]
    assert not {"invoke", "reserve_budget", "record_usage", "put_raw"}.intersection(events)
    assert canonical_json(
        [asdict(replace(run, recovered=False)) for run in recovered]
    ) == canonical_json([asdict(run) for run in runs])


PRELIMINARY_PINS = (
    "1def1cce875cdef1e0a5f00effe0fc904e1eb6791ca66955eea82b49c8867c0d",
    "d10b3af75ff5ec3335a0d0052851ed29841209a834cab98517fe6e5ad63f860a",
    "dc5fa11b0ac25e7eb9b6639c2124f2e153fa6ae2e2b46650a66ad4440996f5a2",
)
RUNS_PIN = "fdac739e04419a6c0ce8ec1bf0ff5bdd7fa5d8df7b4bb6df0220470e1ee6d142"
STORED_PIN = "7e02695a79382bb276d2044495c94b181ce9b790a247f8dba23e0da85bd4c45b"
EVENTS_PIN = "5947ec07adb59f3a1ec04f474f35cdbbd7328f5ed018ea71f6baeba4d9e27327"
