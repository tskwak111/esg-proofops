"""Publication reuses its fully validated immutable source graph, not per-claim replays."""

import time
from contextlib import contextmanager

import pytest
from proofops_api import hosted_results
from proofops_api.hosted_store import HostedStore

from tests.test_hosted_analysis import fake_analysis, source_pdf
from tests.test_hosted_public import actor
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


def test_publication_loads_claim_evidence_once(settings, monkeypatch):
    services = hosted_results.services
    calls = []

    @contextmanager
    def tracked(*args):
        with services(*args) as bound:
            claims = bound[1]
            load = claims.load_evidence

            def counted(*args, **kwargs):
                calls.append(1)
                return load(*args, **kwargs)

            claims.load_evidence = counted
            yield bound

    monkeypatch.setattr(hosted_results, "services", tracked)
    store = HostedStore(settings)
    auth = actor(store)
    doc = store.upload(auth, source_pdf(), "rb2-replay-upload001", now=time.time())
    store.create_run(
        auth,
        doc["document_id"],
        [1, 2],
        "rb2-replay-run000001",
        now=time.time(),
        pipeline_profile="strict-v1",
    )
    done = store.tick(now=time.time(), analysis=fake_analysis)
    assert done["status"] in {"completed", "partial_blocked"}
    result = store.get_result(auth.tenant_id, done["run_id"])
    assert len(result["claims"]) == 2
    assert all(c["confirmed_grade"] is None for c in result["claims"])
    assert len(calls) == 1


def test_tagged_publication_replays_source_once_across_both_stores(settings, monkeypatch):
    from proofops.adapters.local.claim_store import LocalClaimStore

    load = LocalClaimStore.load_evidence
    replay = hosted_results.read_result
    evidence_calls = []
    publication_counts = []

    def tracked(*args, **kwargs):
        evidence_calls.append(1)
        return load(*args, **kwargs)

    def published(*args):
        before = len(evidence_calls)
        result = replay(*args)
        publication_counts.append(len(evidence_calls) - before)
        return result

    monkeypatch.setattr(LocalClaimStore, "load_evidence", tracked)
    monkeypatch.setattr(hosted_results, "read_result", published)
    store = HostedStore(settings)
    auth = actor(store)
    doc = store.upload(auth, source_pdf(), "fx4-replay-upload01", now=time.time())
    store.create_run(
        auth,
        doc["document_id"],
        [1, 2],
        "fx4-replay-run00001",
        now=time.time(),
        pipeline_profile="strict-v1",
    )
    done = store.tick(now=time.time(), analysis=fake_analysis)
    assert len(store.get_result(auth.tenant_id, done["run_id"])["claims"]) == 2
    assert publication_counts == [1]
