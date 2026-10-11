"""Exact fresh table reuse must never import a stored or altered approval."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from proofops.adapters.local import parse_table_cache as cache
from proofops.application.analysis_profile import FINALS_I3_POLICY, S1_POLICY, policy_for
from proofops.domain.provenance import canonical_hash

from tests.integration.test_selected_cell_table_verification import (
    LAYOUT_A_CELLS,
    LAYOUT_A_WORDS,
    grid_pdf,
    table_graph,
)


@pytest.fixture
def data(monkeypatch):
    from proofops.adapters.local import selected_cell_table_verification as selected
    from proofops.adapters.local import upstage_ocr_profile_v6 as v6

    source = grid_pdf(LAYOUT_A_WORDS)
    graph = table_graph(source, LAYOUT_A_CELLS)
    calls = []

    def attest(graph, source, *, tenant_id):
        calls.append(1)
        # Actual selected-cell source/layout guards; only rendered OCR is stubbed.
        result = deepcopy(selected.attest_tables(graph, source, tenant_id=tenant_id))
        result.update(
            policy_sha256=v6.table_policy_sha256(),
            reader_policy=v6.native_policy(),
            rendered_reader_profile=v6.PROFILE,
            run_id="s1-test",
            page_collections=[],
            replay_mode="offline_collected_response_recomputation_v1",
            rendered_reader_sha256=v6.reader_policy()["reader_sha256"],
        )
        result["artifact_sha256"] = canonical_hash(
            {k: v for k, v in result.items() if k != "artifact_sha256"}
        )
        return result

    monkeypatch.setattr(
        selected,
        "_rendered_cell",
        lambda page, box: dict(status="read", text=page.crop(box).extract_text() or ""),
    )
    selected._attest_json.cache_clear()
    verifier = SimpleNamespace(
        attest_tables=attest, replay_tables=lambda *a, **k: calls.append(2) or graph
    )
    return source, graph, verifier, calls


def test_whole_fresh_table_receipt_reuses_exact_frozen_tail(data):
    from proofops.adapters.local import selected_cell_table_verification as selected

    source, graph, verifier, calls = data
    args = dict(tenant_id=graph.tenant_id)
    expected = selected.replay_tables(
        selected.attest_tables(graph, source, **args), graph, source, **args
    )
    with cache.scope(graph.tenant_id, "s1-test"):
        receipt = cache.attest(verifier, graph, source, **args)
        result = cache.replay(verifier, receipt, graph, source, **args)
        assert result == expected
        assert any(block.quality == "verified" for block in result.blocks)
        assert all(
            block.quality == "unverified" for block in result.blocks if block.kind == "table"
        )
        assert calls == [1]
        receipt["records"].clear()
        cache.replay(verifier, receipt, graph, source, **args)
        assert calls == [1, 2]


@pytest.mark.parametrize("change", ["source", "tenant", "graph", "run", "runtime"])
def test_changed_identity_never_reuses(data, monkeypatch, change):
    source, graph, verifier, calls = data
    args = dict(tenant_id=graph.tenant_id)
    with cache.scope(graph.tenant_id, "s1-test"):
        receipt = cache.attest(verifier, graph, source, **args)
        if change == "source":
            source += b"changed"
        elif change == "tenant":
            args["tenant_id"] = "foreign"
        elif change == "graph":
            graph = replace(graph, blocks=())
        elif change == "run":
            receipt["run_id"] = "foreign"
        else:
            monkeypatch.setattr(cache, "runtime_policy", lambda: {"status": "changed"})
        cache.replay(verifier, receipt, graph, source, **args)
    assert calls == [1, 2]


def test_cold_replay_and_outside_scope_never_reuses(data):
    source, graph, verifier, calls = data
    args = dict(tenant_id=graph.tenant_id)
    receipt = verifier.attest_tables(graph, source, **args)
    with cache.scope(graph.tenant_id, "s1-test"):
        cache.replay(verifier, receipt, graph, source, **args)
        cache.attest(verifier, graph, source, **args)
    cache.replay(verifier, receipt, graph, source, **args)
    assert calls == [1, 2, 1, 2]


def test_transient_read_is_not_reused(data):
    source, graph, verifier, calls = data
    original = verifier.attest_tables

    def unavailable(*a, **k):
        result = original(*a, **k)
        result["error"] = "ReaderUnavailable"
        return result

    verifier.attest_tables = unavailable
    with cache.scope(graph.tenant_id, "s1-test"):
        receipt = cache.attest(verifier, graph, source, tenant_id=graph.tenant_id)
        cache.replay(verifier, receipt, graph, source, tenant_id=graph.tenant_id)
    assert calls == [1, 2]


@pytest.mark.parametrize("change", ["reader_bytes", "budget", "compatibility"])
def test_changed_reader_or_capacity_and_compatibility_fall_back(data, monkeypatch, change):
    source, graph, verifier, calls = data
    if change == "reader_bytes":
        monkeypatch.setattr(cache, "SELECTED_SHA256", "0" * 64)
    elif change == "budget":
        monkeypatch.setattr(cache, "MAX_BYTES", 1)
    else:
        monkeypatch.setattr(cache, "read_profile", lambda: "receipt-env-drift-v1")
    with cache.scope(graph.tenant_id, "s1-test"):
        receipt = cache.attest(verifier, graph, source, tenant_id=graph.tenant_id)
        cache.replay(verifier, receipt, graph, source, tenant_id=graph.tenant_id)
    assert calls == [1, 2]


def test_nested_and_separate_scopes_never_inherit_approval(data):
    source, graph, verifier, calls = data
    args = dict(tenant_id=graph.tenant_id)
    with cache.scope(graph.tenant_id, "s1-test"):
        receipt = cache.attest(verifier, graph, source, **args)
        with cache.scope(graph.tenant_id, "s1-test"):
            cache.replay(verifier, receipt, graph, source, **args)
        cache.replay(verifier, receipt, graph, source, **args)
    with cache.scope(graph.tenant_id, "s1-test"):
        cache.replay(verifier, receipt, graph, source, **args)
    assert calls == [1, 2, 2]


def test_new_policy_is_opt_in_and_preserves_i3():
    assert (
        canonical_hash(FINALS_I3_POLICY)
        == "830ce06b7dec224b15be7a60d9813bd08038e5a229709193e6c621a9e18f92e3"
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I3_POLICY))
        == FINALS_I3_POLICY
    )
    assert policy_for("finals-unattended-v2", pinned_hash=canonical_hash(S1_POLICY)) == S1_POLICY
    assert (
        S1_POLICY["parse_replay_cache"]["implementation_sha256"]
        == sha256(Path(cache.__file__).read_bytes()).hexdigest()
    )


def test_persisted_policy_activates_scope_and_tampered_policy_fails_closed():
    snapshot = dict(
        analysis_profile_policy=S1_POLICY, analysis_profile_policy_sha256=canonical_hash(S1_POLICY)
    )
    with cache.for_snapshot(snapshot, "tenant", "run"):
        assert cache._scope.get()[:2] == ("tenant", "run")
    assert cache._scope.get() is None
    with cache.for_snapshot(
        dict(
            analysis_profile_policy=FINALS_I3_POLICY,
            analysis_profile_policy_sha256=canonical_hash(FINALS_I3_POLICY),
        ),
        "tenant",
        "run",
    ):
        assert cache._scope.get() is None
    with pytest.raises(ValueError, match="S1_PARSE_POLICY_MISMATCH"):
        with cache.for_snapshot(snapshot | dict(analysis_profile_policy={}), "tenant", "run"):
            pytest.fail("changed policy admitted")


def test_operator_s1_pin_reaches_new_immutable_run(tmp_path, monkeypatch):
    import json
    import sys

    from proofops.adapters.local.run_store import LocalSQLiteRunStore

    from evaluation import local_upstage_pilot as pilot
    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf

    monkeypatch.setattr(sys, "platform", "linux")
    pdf = tmp_path / "selected.pdf"
    pdf.write_bytes(source_pdf())
    state = tmp_path / "state"
    pin = canonical_hash(S1_POLICY)
    argv = prepare_argv(
        pdf,
        state,
        "11111111-1111-4111-8111-111111111111",
        dict(
            analysis_profile="finals-unattended-v2",
            report_year=2024,
            period_start="2024-01-01",
            period_end="2024-12-31",
        ),
        dict(pages=[10, 20], claim_pages=[10], analysis_profile_sha256=pin),
    )
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    manifest = json.loads((state / "pilot.json").read_text())
    snapshot = LocalSQLiteRunStore(state / "state.sqlite3").snapshot(
        manifest["tenant_id"], manifest["run_id"]
    )
    assert snapshot["analysis_profile_policy_sha256"] == pin
    assert snapshot["analysis_profile_policy"] == S1_POLICY
    assert manifest["analysis_policy_sha256"] == pin
    assert snapshot["input_hash"] == canonical_hash(
        {k: v for k, v in snapshot.items() if k != "input_hash"}
    )
