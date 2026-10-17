"""SPE retains every source proof while sharing immutable reader inputs."""

import io
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pdfplumber
import pytest
from proofops.adapters.local import cf4_claim_source
from proofops.domain.provenance import canonical_hash

from tests.integration.test_claim_source_v3 import synthetic


def test_scope_reuses_exact_pdf_bytes_and_closes_resources():
    from proofops.adapters.local.spe_source_execution import SourceScope

    source, graph, _ = synthetic("ESG policy 10% achieved")
    with SourceScope(graph, source) as scope:
        with scope.open_pdf(io.BytesIO(source)) as first:
            pages = first.pages
        with scope.open_pdf(io.BytesIO(source)) as second:
            assert second.pages is pages
            assert second.pages[0].extract_text()
        with scope.open_pdf(io.BytesIO(source + b"\n")) as different:
            assert different.pages is not pages
    assert scope.document is None


def test_graph_digest_reuse_keeps_exact_bytes_and_rejects_mutation():
    from proofops.adapters.local.spe_source_execution import SourceScope

    source, graph, _ = synthetic("ESG policy 10% achieved")
    with SourceScope(graph, source) as scope:
        data = scope.asdict(graph)
        assert data == asdict(graph)
        assert scope.asdict(graph) is data
        assert scope.canonical_hash(data) == canonical_hash(asdict(graph))
        with pytest.raises(TypeError):
            data["blocks"][0]["quality"] = "verified"
        changed = replace(graph, source_sha256="0" * 64)
        assert scope.canonical_hash(scope.asdict(changed)) != scope.canonical_hash(data)


def test_full_cf4_source_receipt_is_identical_and_shared_modules_untouched(monkeypatch):
    from proofops.adapters.local import claim_source_verification_v4 as native
    from proofops.adapters.local.spe_source_execution import SourceScope

    monkeypatch.setattr(
        cf4_claim_source.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(fetch=lambda *a, **k: pytest.fail("unexpected OCR acquisition")),
    )
    source, graph, ref = synthetic("ESG policy 10% achieved")
    original_open, original_native = pdfplumber.open, native._native_record
    reader = cf4_claim_source.for_run("spe-test")
    expected = reader.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    with SourceScope(graph, source) as scope:
        optimized = cf4_claim_source.for_run("spe-test")
        scope.bind_reader(optimized)
        actual = optimized.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    assert actual == expected
    assert pdfplumber.open is original_open and native._native_record is original_native
    with SourceScope(graph, source) as scope:
        optimized = cf4_claim_source.for_run("spe-test")
        scope.bind_reader(optimized)
        assert (
            optimized.recompute_claim_receipt(
                actual, graph, source, (ref,), tenant_id=graph.tenant_id
            )
            == expected
        )
        with pytest.raises(ValueError):
            optimized.attest_claim_spans(
                graph, source + b"changed", (ref,), tenant_id=graph.tenant_id
            )
        with pytest.raises(ValueError):
            optimized.attest_claim_spans(graph, source, (ref,), tenant_id="other-tenant")


def test_opt_in_receipt_changes_only_outer_policy_and_rejects_rehashed_forgery(monkeypatch):
    from proofops.adapters.local import spe_claim_source as spe

    monkeypatch.setattr(
        cf4_claim_source.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(fetch=lambda *a, **k: pytest.fail("unexpected OCR acquisition")),
    )
    source, graph, ref = synthetic("ESG policy 10% achieved")
    arguments = dict(tenant_id=graph.tenant_id, run_id="spe-test")
    old = cf4_claim_source.attest_claim_spans(graph, source, (ref,), **arguments)
    new = spe.attest_claim_spans(graph, source, (ref,), **arguments)
    assert old["policy"] != new["policy"]
    assert {k: v for k, v in old.items() if k not in {"policy", "artifact_sha256"}} == {
        k: v for k, v in new.items() if k not in {"policy", "artifact_sha256"}
    }
    reader = spe.for_run("spe-test")
    assert (
        reader.recompute_claim_receipt(new, graph, source, (ref,), tenant_id=graph.tenant_id) == new
    )
    forged = deepcopy(new)
    forged["previous_receipt"]["records"][0]["status"] = "forged"
    forged["artifact_sha256"] = canonical_hash(
        {k: v for k, v in forged.items() if k != "artifact_sha256"}
    )
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        reader.recompute_claim_receipt(forged, graph, source, (ref,), tenant_id=graph.tenant_id)
    for changed in (
        replace(ref, quote="ESG policy 99% achieved"),
        replace(ref, bbox=(0.0, 0.0, 1.0, 1.0)),
    ):
        with pytest.raises(ValueError):
            reader.recompute_claim_receipt(
                new, graph, source, (changed,), tenant_id=graph.tenant_id
            )


def test_opt_in_policy_preserves_default_and_is_registered():
    from proofops.adapters.local.claim_source_policies import page_ocr_profile
    from proofops.application import analysis_profile as profiles

    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I29B_POLICY)
        )
        is profiles.FINALS_I29B_POLICY
    )
    pin = canonical_hash(profiles.SPE_POLICY)
    assert pin != canonical_hash(profiles.V2_POLICY)
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == profiles.SPE_POLICY
    assert (
        profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == profiles.SPE_POLICY
    )
    assert page_ocr_profile(profiles.SPE_POLICY["source"]).PROFILE == "spe_claim_source_v1"


def test_parser_native_and_table_reader_contract_remains_cf4(monkeypatch):
    from proofops.adapters.local import spe_claim_source as spe

    from tests.integration.test_cf4_source import Store

    store = Store(text="ESG policy 10% achieved")
    monkeypatch.setattr(cf4_claim_source.PageOCRStore, "from_env", lambda: store)
    source, graph, _ = synthetic("ESG policy 10% achieved")
    baseline, candidate = cf4_claim_source.for_run("spe-parser"), spe.for_run("spe-parser")
    for attest, replay in (
        ("attest_tables", "replay_tables"),
        ("attest_native_sources", "replay_native_sources"),
    ):
        expected = getattr(baseline, attest)(graph, source, tenant_id=graph.tenant_id)
        actual = getattr(candidate, attest)(graph, source, tenant_id=graph.tenant_id)
        assert actual == expected
        assert getattr(candidate, replay)(actual, graph, source, tenant_id=graph.tenant_id) == (
            getattr(baseline, replay)(expected, graph, source, tenant_id=graph.tenant_id)
        )


def test_coordinate_projection_reuse_requires_immutable_input():
    from proofops.adapters.local.spe_source_execution import SourceScope
    from proofops.adapters.local.table_span_source_verification import _selected_box

    source, graph, _ = synthetic("ESG policy 10% achieved")
    block = graph.blocks[0]
    with SourceScope(graph, source) as scope:
        read = scope.value(_selected_box)
        assert read(block) == _selected_box(block)
        assert read(block) is read(block)
        changed = replace(block, winner=None)
        assert read(changed) is None
        mutable = SimpleNamespace(winner=block.winner, candidates=block.candidates)
        assert read(mutable) == _selected_box(block)
        mutable.winner = None
        assert read(mutable) is None
    assert not scope.boxes


def test_spacing_origins_are_exact_and_caller_mutation_is_isolated():
    from proofops.adapters.local.native_glyph_geometry import _spacing_origins
    from proofops.adapters.local.spe_source_execution import SourceScope

    source, graph, _ = synthetic("ESG policy 10% achieved")
    with SourceScope(graph, source) as scope:
        with scope.open_pdf(io.BytesIO(source)) as document:
            page = document.pages[0]
            read = scope.value(_spacing_origins)
            expected = _spacing_origins(page)
            actual = read(page)
            assert actual == expected
            actual.clear()
            assert read(page) == expected
            assert len(scope.origins) == 1
    assert not scope.origins


@pytest.mark.parametrize("kind", ["exact", "wrong-number", "low-confidence", "neighbor"])
def test_region_corroboration_preserves_admission_and_exact_geometry(kind):
    from proofops.adapters.local.cf4_source_region import attest_regions
    from proofops.adapters.local.spe_source_execution import SourceScope

    from tests.integration.test_cf4_source import Store
    from tests.integration.test_claim_source_v4_visibility import TEXT, changed_pdf

    store = Store(
        text=TEXT.replace("1234", "1235")
        if kind == "wrong-number"
        else ("An adjacent sentence." if kind == "neighbor" else TEXT),
        confidence=0.979 if kind == "low-confidence" else 0.99,
    )
    source, graph = changed_pdf(b"0 0 m 600 800 l 0 800 l h W n")
    ref = graph.blocks[0].source_ref()
    kwargs = dict(tenant_id=graph.tenant_id, run_id="spe-region", store=store)
    expected = attest_regions(graph, source, (ref,), **kwargs)
    with SourceScope(graph, source) as scope:
        actual = scope.function(attest_regions)(graph, source, (ref,), **kwargs)
    assert actual == expected
    assert actual["records"][0]["status"] == ("verified" if kind == "exact" else "unresolved")


def test_opt_in_policy_change_before_and_during_read_fails_closed(monkeypatch):
    from proofops.adapters.local import spe_claim_source as spe

    monkeypatch.setattr(
        cf4_claim_source.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(fetch=lambda *a, **k: pytest.fail("unexpected OCR acquisition")),
    )
    source, graph, ref = synthetic("ESG policy 10% achieved")
    reader = spe.for_run("spe-test")
    policy = spe.claim_source_policy
    monkeypatch.setattr(spe, "claim_source_policy", lambda: policy() | dict(changed=True))
    with pytest.raises(ValueError, match="SPE_READER_POLICY_CHANGED"):
        reader.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    monkeypatch.setattr(spe, "claim_source_policy", policy)
    bind = spe.execution.SourceScope.bind_reader
    completed = []

    def change_after_read(scope, inner):
        bind(scope, inner)
        attest = inner.attest_claim_spans

        def changed(*args, **kwargs):
            result = attest(*args, **kwargs)
            completed.append(result)
            monkeypatch.setattr(spe, "claim_source_policy", lambda: policy() | dict(changed=True))
            return result

        inner.attest_claim_spans = changed

    monkeypatch.setattr(spe.execution.SourceScope, "bind_reader", change_after_read)
    with pytest.raises(ValueError, match="SPE_READER_POLICY_CHANGED"):
        reader.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    assert completed
