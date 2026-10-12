import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from threading import Lock

import pytest
from proofops.adapters.local.openai import OpenAIProbe
from proofops.application.analysis_profile import V2_POLICY, policy_for
from proofops.domain.provenance import canonical_hash

from tests.unit.test_openai_luna import response


def snapshot(tenant="tenant-a"):
    return dict(
        tenant_id=tenant,
        document=dict(sha256="a" * 64),
        analysis_profile_policy=deepcopy(V2_POLICY),
        analysis_profile_policy_sha256=canonical_hash(V2_POLICY),
    )


def probe(tmp_path, name, scope=None):
    p = OpenAIProbe("fake", tmp_path / (name + ".sqlite3"))
    p.response_cache_path = tmp_path / "cache.sqlite3"
    p.configure_response_policy(scope or snapshot(), role="extract")
    return p


def test_exact_reuse_zero_charge_and_three_independent_replicas(tmp_path):
    sent = []
    first = probe(tmp_path, "first")
    # Each replica must make its own real call even when the wire is identical.
    original = []
    for replica in (1, 2, 3):
        first._post = lambda body, r=replica: sent.append(body) or dict(response(), id=f"real-{r}")
        with first.response_context(role="elements", replica=replica):
            original.append(
                first.complete("Return JSON", "{}", request_id=f"a{replica}", json_mode=True)
            )
    second = probe(tmp_path, "second")
    second._post = lambda _: pytest.fail("paid duplicate")
    for replica in (1, 2, 3):
        with second.response_context(role="elements", replica=replica):
            reused = second.complete("Return JSON", "{}", request_id=f"b{replica}", json_mode=True)
        assert reused["content"] == original[replica - 1]["content"]
        assert reused["provider_request_id"] == f"real-{replica}"
        assert reused["cost_with_vat_reserve_usd"] == "0"
        assert reused["input_tokens"] == reused["output_tokens"] == 0
        assert reused["response_reuse"]["source_receipt_sha256"]
    assert len(sent) == 3 and all(b["top_p"] == 1 for b in sent)
    assert all("seed" not in b for b in sent)
    assert second.summary()["committed_usd"] == "0"
    from proofops.adapters.local.upstage import request_usage

    usage = request_usage(second.ledger, ["b1", "b2", "b3"])
    assert usage["model_response_reuses"] == 3 and usage["provider_dispatches"] == 0
    assert len(usage["model_response_reuse_origins"]) == 3
    assert Decimal(first.summary()["committed_usd"]) == Decimal("0.00005412")


@pytest.mark.parametrize(
    "change", ["tenant", "source", "role", "replica", "prompt", "input", "schema", "tokens"]
)
def test_boundary_changes_force_fresh_call(tmp_path, change):
    first = probe(tmp_path, "first")
    first._post = lambda _: response()
    with first.response_context(role="elements", replica=1):
        first.complete("JSON", "{}", request_id="a", json_mode=True)
    scope = snapshot("tenant-b" if change == "tenant" else "tenant-a")
    if change == "source":
        scope["document"]["sha256"] = "b" * 64
    second = probe(tmp_path, "second", scope)
    sent = []
    second._post = lambda b: sent.append(b) or response()
    with second.response_context(
        role="preliminary" if change == "role" else "elements",
        replica=2 if change == "replica" else 1,
    ):
        second.complete(
            "JSON!" if change == "prompt" else "JSON",
            "{ }" if change == "input" else "{}",
            request_id="b",
            json_mode=True,
            max_tokens=100 if change == "tokens" else 1024,
            schema_json='{"type":"object"}' if change == "schema" else None,
        )
    assert len(sent) == 1


def test_parallel_same_replica_single_flight(tmp_path):
    probes = [probe(tmp_path, str(i)) for i in range(4)]
    sent, lock = [], Lock()

    def post(body):
        with lock:
            sent.append(body)
        return response()

    def call(i):
        probes[i]._post = post
        with probes[i].response_context(role="elements", replica=1):
            return probes[i].complete("JSON", "{}", request_id=f"r{i}", json_mode=True)

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(call, range(4)))
    assert len(sent) == 1
    assert sum("response_reuse" in r for r in results) == 3


def test_uncertain_and_tampered_receipt_cannot_be_reused(tmp_path):
    first = probe(tmp_path, "first")
    first._post = lambda _: (_ for _ in ()).throw(TimeoutError())
    with pytest.raises(ValueError, match="^PROVIDER_PROCESSING_FAILED$"):
        first.complete("JSON", "{}", request_id="a", json_mode=True)
    second = probe(tmp_path, "second")
    second._post = lambda _: pytest.fail("uncertain duplicate")
    with pytest.raises(ValueError, match="PROCESSING_UNCERTAIN"):
        second.complete("JSON", "{}", request_id="b", json_mode=True)
    other = probe(tmp_path, "other")
    other._post = lambda _: response()
    other.complete("other JSON", "{}", request_id="c", json_mode=True)
    origin_path = next(other.response_cache_path.with_suffix(".origins").glob("*.json"))
    origin_path.write_text("{}")
    with pytest.raises(ValueError, match="MODEL_RESPONSE_CACHE_INVALID"):
        second.complete("other JSON", "{}", request_id="d", json_mode=True)


def test_historical_policy_and_wire_remain_unchanged(tmp_path):
    old = "54a118c81f4a0c32fd83f07a32fea51b734d6de2de4884e31bd4fb675b29c67d"
    assert canonical_hash(policy_for("finals-unattended-v2", pinned_hash=old)) == old
    p = OpenAIProbe("fake", tmp_path / "old.sqlite3")
    p.configure_response_policy(
        dict(analysis_profile_policy=policy_for("finals-unattended-v2", pinned_hash=old)),
        role="extract",
    )
    assert "top_p" not in p.request_body("JSON", "{}", request_id="a")
    with pytest.raises(ValueError, match="MODEL_RESPONSE_POLICY_MISMATCH"):
        p.configure_response_policy(
            snapshot() | dict(analysis_profile_policy_sha256="wrong"), role="extract"
        )


def test_cache_origin_is_bound_to_key_and_replica_is_mandatory(tmp_path):
    from proofops.adapters.local.model_response_cache import ModelResponseCache

    p = probe(tmp_path, "origin")
    p._post = lambda _: response()
    result = p.complete("JSON", "{}", request_id="source", json_mode=True)
    cache = ModelResponseCache(p.response_cache_path)
    with sqlite3.connect(cache.path) as db:
        row = db.execute(
            "SELECT ledger,request_id,payload,sha256 FROM model_responses_v1"
        ).fetchone()
    with pytest.raises(ValueError, match="MODEL_RESPONSE_CACHE_INVALID"):
        cache._verified("b" * 64, row)
    assert result["response_request"]["replica"] == 0
    p.configure_response_policy(snapshot(), role="preliminary")
    with pytest.raises(ValueError, match="MODEL_RESPONSE_REPLICA_REQUIRED"):
        p.complete("JSON", "{}", request_id="missing-replica", json_mode=True)


def test_publication_failure_keeps_paid_response_dispatch_fence(tmp_path, monkeypatch):
    from proofops.adapters.local.model_response_cache import ModelResponseCache

    p = probe(tmp_path, "paid")
    p._post = lambda _: response()
    monkeypatch.setattr(ModelResponseCache, "publish", lambda *a: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        p.complete("JSON", "{}", request_id="paid", json_mode=True)
    assert p.summary()["unsettled_calls"] == 0
    with sqlite3.connect(p.response_cache_path) as db:
        assert (
            db.execute("SELECT count(*) FROM model_responses_v1 WHERE payload IS NULL").fetchone()[
                0
            ]
            == 1
        )


def test_reuse_origin_survives_worker_state_cleanup(tmp_path):
    first = probe(tmp_path, "temporary-worker")
    first._post = lambda _: response()
    original = first.complete("JSON", "{}", request_id="original", json_mode=True)
    first.ledger.unlink()
    shutil.rmtree(first._responses)
    second = probe(tmp_path, "new-worker")
    second._post = lambda _: pytest.fail("paid after temporary worker cleanup")
    result = second.complete("JSON", "{}", request_id="reused", json_mode=True)
    assert result["content"] == original["content"]
    assert result["response_reuse"]["source_receipt_sha256"]
