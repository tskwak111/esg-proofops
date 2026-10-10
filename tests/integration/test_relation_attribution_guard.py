"""SY1: refuse unsupported role ownership, without turning unknown into absent."""

from dataclasses import replace

import pytest
from proofops.application.evidence.relation_attribution import (
    POLICY,
    filter_dimensions,
    role_rejection,
    snapshot_policy,
)
from proofops.application.ingest.graph_fusion import CandidateBatch, CandidateBlock, fuse_candidates
from proofops.domain.documents import NativeSource, PageGeometry
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_binding import corpus, span
from tests.acceptance.test_citations import MANIFEST, RUN, TENANT, VERSION


def paragraphs(*texts, pages=None):
    candidates = tuple(
        CandidateBlock(
            "paragraph",
            NativeSource(
                VERSION,
                MANIFEST,
                RUN,
                str(i),
                (pages or [1] * len(texts))[i],
                None,
                (10, 10 + i * 100, 500, 90 + i * 100),
                "pdf_bottom_left_points",
                text,
                0,
                len(text),
            ),
            PageGeometry(600, 800, 0, (0, 0, 600, 800)),
        )
        for i, text in enumerate(texts)
    )
    batch = CandidateBatch(
        TENANT,
        VERSION,
        MANIFEST,
        "a" * 64,
        RUN,
        "synthetic",
        "1",
        "synthetic",
        "b" * 64,
        candidates,
        synthetic=True,
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    graph = replace(graph, blocks=tuple(replace(b, quality="verified") for b in graph.blocks))
    refs = tuple(
        next(b for b in graph.blocks if b.sources[0].source_native_id == str(i)).source_ref()
        for i in range(len(texts))
    )
    _, template, _ = corpus()
    claim = replace(template, quote=refs[0].quote, source_refs=(refs[0],))
    return graph, claim, refs


@pytest.mark.parametrize("pages", [[1, 2], [1, 1]])
def test_unrelated_page_or_block_is_unknown(pages):
    graph, claim, refs = paragraphs(
        "기아는 감축 계획을 수립합니다.", "기아는 EV6를 출시했습니다.", pages=pages
    )
    roles = {"entity": span(refs[1], "기아"), "product": None}
    filtered, rejected = filter_dimensions(claim, roles, graph, tenant_id=TENANT)
    assert filtered == {"entity": None, "product": None}
    assert rejected["entity"] == (
        "RELATION_OTHER_PAGE" if pages[1] == 2 else "RELATION_OTHER_BLOCK"
    )
    assert roles["entity"] is not None  # old revision input stays immutable


def test_same_paragraph_retained_but_next_paragraph_refused():
    text = (
        "기아는 감축 계획을 수립합니다. 적용 범위는 국내 공장 전체입니다."
        "\n\n다른 제품은 EV6 모델입니다."
    )
    graph, claim, refs = paragraphs(text)
    claim_ref = span(refs[0], "기아는 감축 계획을 수립합니다.")
    claim = replace(claim, quote=claim_ref.quote, source_refs=(claim_ref,))
    roles = {"facility": span(refs[0], "국내 공장"), "product": span(refs[0], "EV6")}
    filtered, rejected = filter_dimensions(claim, roles, graph, tenant_id=TENANT)
    assert filtered["facility"] == roles["facility"]
    assert filtered["product"] is None
    assert rejected == {"product": "RELATION_OTHER_PARAGRAPH"}


def test_verified_same_table_headers_remain_candidates():
    from tests.acceptance.test_preliminary_table_sources import table_corpus

    graph, claim, block = table_corpus(second_page=True)
    roles = {
        "metric": block("r1_metric-atom").source_ref(),
        "reporting_period": block("h_2025-atom").source_ref(),
    }
    filtered, rejected = filter_dimensions(claim, roles, graph, tenant_id=TENANT)
    assert filtered == roles and rejected == {}
    for name in ("r2_metric-atom", "h_2024-atom", "other_metric-atom"):
        filtered, rejected = filter_dimensions(
            claim, {"metric": block(name).source_ref()}, graph, tenant_id=TENANT
        )
        assert filtered == {"metric": None} and rejected


@pytest.mark.parametrize("valid_group", [False, True])
def test_explicit_verified_literal_group_only(valid_group):
    from proofops.application.ingest.graph_fusion import CanonicalEdge

    left, right = "기아는 감축 계획을 수립합니다.", "적용 범위는 국내 공장 전체입니다."
    graph, claim, refs = paragraphs(left, right, right + "\n" + left)
    parent = next(b for b in graph.blocks if b.source_id == refs[2].source_id)
    candidate = replace(parent.candidates[0], context=(POLICY["block_group_marker"],))
    parent = replace(
        parent, candidates=(candidate,), quality="verified" if valid_group else "unverified"
    )
    graph = replace(
        graph,
        blocks=tuple(parent if b.source_id == parent.source_id else b for b in graph.blocks),
        edges=tuple(CanonicalEdge(parent.source_id, r.source_id, "derived_from") for r in refs[:2]),
    )
    roles = {"facility": span(refs[1], "국내 공장")}
    filtered, rejected = filter_dimensions(claim, roles, graph, tenant_id=TENANT)
    assert filtered == (roles if valid_group else {"facility": None})
    assert bool(rejected) is not valid_group


@pytest.mark.parametrize(
    "text,quote", [("탄소가격을 산정합니다.", "탄소"), ("비탄소 소재", "탄소"), ("RE1000", "RE100")]
)
def test_token_substrings_are_refused(text, quote):
    assert (
        role_rejection(text, text.index(quote), text.index(quote) + len(quote), "material")
        == "RELATION_TOKEN_FRAGMENT"
    )


@pytest.mark.parametrize(
    "quote,role",
    [("기아", "entity"), ("재활용 플라스틱", "material"), ("EV6", "product"), ("RE100", "metric")],
)
def test_literal_tokens_and_korean_particles_remain_candidates(quote, role):
    text = quote + "는 계획에 포함됩니다."
    assert role_rejection(text, 0, len(quote), role) is None


@pytest.mark.parametrize("role", ["product", "material"])
@pytest.mark.parametrize("quote", ["RE100", "SBTi", "ISO 14001"])
def test_initiative_or_certification_cannot_be_product_or_material(quote, role):
    assert role_rejection(quote, 0, len(quote), role) == "RELATION_INITIATIVE_ROLE"


def test_forged_source_and_unverified_block_stay_unknown():
    graph, claim, refs = paragraphs("기아는 RE100 이행을 추진합니다.")
    roles = {"entity": replace(span(refs[0], "기아"), raw_text_sha256="0" * 64)}
    filtered, _ = filter_dimensions(claim, roles, graph, tenant_id=TENANT)
    assert filtered == {"entity": None}
    graph = replace(graph, blocks=tuple(replace(b, quality="unverified") for b in graph.blocks))
    filtered, _ = filter_dimensions(
        claim, {"entity": span(refs[0], "기아")}, graph, tenant_id=TENANT
    )
    assert filtered == {"entity": None}


def test_policy_pin_is_explicit_and_legacy_snapshot_unchanged():
    assert snapshot_policy({}) is None
    snapshot = {
        "relation_attribution_policy": POLICY,
        "relation_attribution_policy_sha256": canonical_hash(POLICY),
    }
    assert snapshot_policy(snapshot) == POLICY
    for bad in [
        snapshot | {"relation_attribution_policy_sha256": "0" * 64},
        {"relation_attribution_policy": POLICY},
    ]:
        with pytest.raises(ValueError, match="RELATION_ATTRIBUTION_POLICY_MISMATCH"):
            snapshot_policy(bad)


def guarded_runtime(runtime, graph, usage):
    from proofops_worker.live_tagging import LiveTaggingRuntime

    snapshot = {k: v for k, v in runtime.snapshot.items() if k != "input_hash"}
    snapshot.update(
        relation_attribution_policy=POLICY,
        relation_attribution_policy_sha256=canonical_hash(POLICY),
    )
    snapshot["input_hash"] = canonical_hash(snapshot)
    return LiveTaggingRuntime(
        runtime.runner,
        snapshot,
        graph,
        runtime.lease,
        usage,
        probe=runtime.preliminary_transport._probe,
        ledger=runtime.ledger,
        receipts=runtime.receipts,
    )


def test_worker_refuses_remote_candidates_before_spending(tmp_path, monkeypatch):
    from tests.integration.test_live_relation_worker import configured

    old, claim, graph, packet, calls, _, usage = configured(tmp_path, monkeypatch)
    runtime = guarded_runtime(old, graph, usage)
    roles = runtime.relations(claim, packet)
    assert roles and all(v is None for values in roles.values() for v in values.values())
    assert calls == []
    assert runtime.relation_records[claim.claim_id]
    assert all(
        r["status"] == "attribution_rejected" for r in runtime.relation_records[claim.claim_id]
    )


def test_guarded_catalog_omits_fragments_and_initiative_product_roles():
    from proofops.application.ingest.span_alignment import SourceIdentity
    from proofops.application.tagging.relations import bounded_occurrence_sources

    text = "탄소가격을 검토합니다. RE100은 목표이며 EV6는 제품입니다."
    identity = SourceIdentity(TENANT, VERSION, RUN, MANIFEST, "a" * 64, "b" * 64, 1)
    packets, _ = bounded_occurrence_sources(
        ((identity, text),),
        claim_text=text,
        dimensions={"material": "탄소", "product": "RE100"},
        attribution_guard=True,
    )
    occurrences = packets[0]["occurrences"]
    assert not any(c["quote"] == "탄소" for c in occurrences)
    assert not any(
        c["quote"] == "RE100" and set(c["roles"]) & {"product", "material"} for c in occurrences
    )


def test_new_run_pins_guard_and_publishes_unknown_without_relation_calls(tmp_path, monkeypatch):
    from tests.integration.test_live_tagging_pipeline import _pipeline_setup

    ctx = _pipeline_setup(tmp_path, monkeypatch, relation_stage=True)
    runner, tenant, run_id = ctx["tag_runner"], ctx["tenant"], ctx["run_id"]
    assert snapshot_policy(ctx["service"].store.snapshot(tenant, run_id)) == POLICY
    assert runner.run_once(tenant_id=tenant, run_id=run_id) == "needs_review"
    checkpoint = runner.tags.load_snapshot(tenant, run_id)
    assert checkpoint["relation_attribution_policy_sha256"] == canonical_hash(POLICY)
    for item in checkpoint["claims"]:
        assert item["decision"] is None
        assert item["relation_records"]
        assert all(r["status"] == "attribution_rejected" for r in item["relation_records"])
        inputs = runner.tags.load_inputs(tenant, run_id, item["claim_id"])
        assert all(
            ref is None
            for key, roles in inputs.relation_tags.items()
            if ":" not in key
            for ref in roles.values()
        )
    assert ctx["tag_probe"].summary()["calls"] == 12  # 6 preliminary + 6 elements, no relation
    before = len(ctx["calls"])
    assert runner.run_once(tenant_id=tenant, run_id=run_id) == "needs_review"
    assert len(ctx["calls"]) == before
