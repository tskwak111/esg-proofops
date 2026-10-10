"""SY2 preserves claim axes while checking permitted evidence in its own paragraph."""

from dataclasses import asdict, replace

import pytest
from proofops.application.evidence.binding import ClaimContext, accept_binding
from proofops.application.evidence.relation_attribution import (
    POLICY,
    filter_dimensions,
    filter_evidence_dimensions,
    relation_source_rejection,
    snapshot_policy,
)
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_binding import span
from tests.acceptance.test_citations import TENANT
from tests.acceptance.test_rules import pack
from tests.integration.test_relation_attribution_guard import paragraphs


def global_case():
    graph, claim, refs = paragraphs(
        "회사A 배출량 2025 감축을 추진합니다.",
        "회사A 배출량 2025 산정방법 및 외부검증입니다.",
        pages=[1, 2],
    )
    dims = {"entity": "회사A", "metric": "배출량", "reporting_period": "2025"}
    context = ClaimContext(claim, {k: span(refs[0], v) for k, v in dims.items()})
    roles = {k: span(refs[1], v) for k, v in dims.items()}
    return graph, claim, refs, context, roles


@pytest.mark.parametrize("eid", ["G4", "G8", "P3", "P4", "M2", "M3"])
def test_global_evidence_roles_are_owned_by_evidence_not_claim(eid):
    graph, claim, refs, context, roles = global_case()
    assert filter_dimensions(claim, roles, graph, tenant_id=TENANT)[0] == dict.fromkeys(roles)
    assert (
        relation_source_rejection(
            claim,
            refs[1],
            graph,
            tenant_id=TENANT,
            policy=POLICY,
            global_elements=(eid,),
            rulepack=pack(),
        )
        is None
    )
    filtered, rejected = filter_evidence_dimensions(
        claim,
        refs[1],
        roles,
        graph,
        tenant_id=TENANT,
        policy=POLICY,
        global_elements=(eid,),
        rulepack=pack(),
    )
    assert filtered == roles and rejected == {}
    assert (
        accept_binding(
            context,
            refs[1],
            filtered,
            original=graph,
            tenant_id=TENANT,
            rulepack=pack(),
            element_id=eid,
        )
        == "accepted"
    )


@pytest.mark.parametrize("eid", ["G1", "G2", "G3", "G5", "P1", "P2", "P5", "M1", "M4"])
def test_non_global_sources_still_refused_before_dispatch(eid):
    graph, claim, refs, _, roles = global_case()
    assert (
        relation_source_rejection(
            claim,
            refs[1],
            graph,
            tenant_id=TENANT,
            policy=POLICY,
            global_elements=(eid,),
            rulepack=pack(),
        )
        == "RELATION_OTHER_PAGE"
    )


def test_evidence_roles_cannot_be_borrowed_from_another_paragraph_or_identity():
    graph, claim, refs, _, roles = global_case()
    roles["entity"] = span(refs[0], "회사A")
    filtered, rejected = filter_evidence_dimensions(
        claim,
        refs[1],
        roles,
        graph,
        tenant_id=TENANT,
        policy=POLICY,
        global_elements=("M3",),
        rulepack=pack(),
    )
    assert filtered["entity"] is None and rejected
    assert (
        relation_source_rejection(
            claim,
            replace(refs[1], raw_text_sha256="0" * 64),
            graph,
            tenant_id=TENANT,
            policy=POLICY,
            global_elements=("M3",),
            rulepack=pack(),
        )
        is not None
    )


def test_legacy_policy_keeps_historical_source_veto():
    from proofops.application.evidence.relation_attribution import LEGACY_POLICY

    graph, claim, refs, _, _ = global_case()
    assert (
        snapshot_policy(
            {
                "relation_attribution_policy": LEGACY_POLICY,
                "relation_attribution_policy_sha256": canonical_hash(LEGACY_POLICY),
            }
        )
        == LEGACY_POLICY
    )
    assert (
        relation_source_rejection(
            claim,
            refs[1],
            graph,
            tenant_id=TENANT,
            policy=LEGACY_POLICY,
            global_elements=("M3",),
            rulepack=pack(),
        )
        == "RELATION_OTHER_PAGE"
    )


def test_worker_selects_only_global_candidates_and_keeps_claim_axis_local(tmp_path, monkeypatch):
    from proofops.application.evidence.retrieval import freeze_packet

    from tests.integration.test_live_relation_worker import configured
    from tests.integration.test_relation_attribution_guard import guarded_runtime

    old, claim, graph, packet, calls, _, usage = configured(tmp_path, monkeypatch)
    raw = packet.to_dict()
    raw.pop("packet_sha256")
    for candidate in raw["evidence_candidates"]:
        candidate.update(source_scope="global_bound", allowed_elements=["M3"])
    old.snapshot.pop("input_hash")
    old.snapshot["rulepack"] = asdict(pack())
    old.snapshot["input_hash"] = canonical_hash(old.snapshot)
    runtime = guarded_runtime(old, graph, usage)
    result = runtime.relations(claim, freeze_packet(raw))
    assert len(calls) == 3
    assert result is not None
    assert all(
        r["status"] == "validated_candidate" for r in runtime.relation_records[claim.claim_id]
    )


@pytest.mark.parametrize("eid", ["G1", "G2", "G5", "P1", "P2"])
def test_global_role_evaluation_never_allows_numeric_or_year_binding(eid):
    graph, claim, refs, context, roles = global_case()
    filtered, _ = filter_evidence_dimensions(
        claim,
        refs[1],
        roles,
        graph,
        tenant_id=TENANT,
        policy=POLICY,
        global_elements=("P3",),
        rulepack=pack(),
    )
    assert filtered == roles
    assert (
        accept_binding(
            context,
            refs[1],
            filtered,
            original=graph,
            tenant_id=TENANT,
            rulepack=pack(),
            element_id=eid,
        )
        == "rejected"
    )


def test_global_roles_do_not_approve_mismatched_or_missing_axes():
    graph, claim, refs, context, roles = global_case()
    missing = dict(roles, entity=None)
    assert (
        accept_binding(
            context,
            refs[1],
            missing,
            original=graph,
            tenant_id=TENANT,
            rulepack=pack(),
            element_id="M3",
        )
        == "undetermined"
    )
    context = replace(context, dimensions=dict(context.dimensions, metric=span(refs[0], "감축을")))
    assert (
        accept_binding(
            context,
            refs[1],
            roles,
            original=graph,
            tenant_id=TENANT,
            rulepack=pack(),
            element_id="M3",
        )
        == "rejected"
    )


def test_dec23_report_scope_remains_refused_for_m2():
    from proofops.domain.rulepacks import pack_content_hash, snapshot_from_validated

    graph, claim, refs = paragraphs(
        "회사A 배출량 2025 감축을 추진합니다.",
        "보고 범위는 회사A의 모든 사업장입니다.",
        pages=[1, 2],
    )
    original = pack()
    manifest = {k: v for k, v in asdict(original).items() if k != "content"}
    files = {p: original.file_content(p) for p in original.files}
    next(e for e in files["rubric/elements.yaml"]["elements"] if e["id"] == "M2")[
        "binding_policy"
    ] = "ACTIVITY_SCOPE_V2"
    manifest["sha256"] = pack_content_hash(manifest, files)
    rulepack = snapshot_from_validated(manifest, files)
    assert (
        relation_source_rejection(
            claim,
            refs[1],
            graph,
            tenant_id=TENANT,
            policy=POLICY,
            global_elements=("M2",),
            rulepack=rulepack,
        )
        == "RELATION_OTHER_PAGE"
    )


def test_new_v2_run_replays_without_calls_and_never_publishes_unknown_as_absent(
    tmp_path, monkeypatch
):
    from tests.integration.test_live_tagging_pipeline import _pipeline_setup

    ctx = _pipeline_setup(tmp_path, monkeypatch, relation_stage=True)
    runner, tenant, run_id = ctx["tag_runner"], ctx["tenant"], ctx["run_id"]
    assert snapshot_policy(ctx["service"].store.snapshot(tenant, run_id)) == POLICY
    assert runner.run_once(tenant_id=tenant, run_id=run_id) == "needs_review"
    checkpoint = runner.tags.load_snapshot(tenant, run_id)
    for item in checkpoint["claims"]:
        assert item["decision"] is None
        assert any(r["status"] == "validated_candidate" for r in item["relation_records"])
        inputs = runner.tags.load_inputs(tenant, run_id, item["claim_id"])
        assert all(
            e.state not in ("absent", "not_applicable")
            for r in inputs.tag_runs
            if r.guarded
            for e in r.guarded.elements
        )
    count = len(ctx["calls"])
    assert runner.run_once(tenant_id=tenant, run_id=run_id) == "needs_review"
    assert len(ctx["calls"]) == count


def test_real_tagging_guard_restores_cross_page_method_without_promoting_p4(tmp_path):
    from proofops.application.evidence.binding import local_relation_tags
    from proofops.application.evidence.retrieval import freeze_track_packet, retrieve_evidence
    from proofops.application.tagging.service import tag_replicates
    from proofops.application.tagging.tracks import TrackCandidate

    from tests.acceptance.test_retrieval import SyntheticSearch
    from tests.acceptance.test_tagging import SyntheticResponder, setup

    graph, claim, refs, context, roles = global_case()
    args = setup(tmp_path)
    track = TrackCandidate(claim, "performance", None)
    rulepack = pack()
    packet = retrieve_evidence(
        claim,
        graph,
        SyntheticSearch(graph),
        tenant_id=TENANT,
        run_id=args["packet"].to_dict()["run_id"],
        index_generation="synthetic-v1",
        rulepack=rulepack,
        document_context={},
        token_counter=lambda text: 0,
    )
    packet = freeze_track_packet(packet, track=track, rulepack=rulepack)
    elements = [
        dict(
            element_id=f"P{i}",
            state="present" if i in (3, 4) else "unknown",
            evidence_refs=[asdict(refs[1])] if i in (3, 4) else [],
            normalized_value=None,
            credited_from=refs[1].source_id if i in (3, 4) else None,
            reason_code=None,
        )
        for i in range(1, 7)
    ]
    args.update(
        packet=packet,
        context=context,
        track=track,
        original=graph,
        rulepack=rulepack,
        invoke=SyntheticResponder(
            refs[1], changes={r: {"root": {"elements": elements}} for r in (1, 2, 3)}
        ),
    )
    for policy, expected in (("sy1", "unknown"), ("sy2", "present")):
        filtered = (
            filter_dimensions(claim, roles, graph, tenant_id=TENANT)[0]
            if policy == "sy1"
            else filter_evidence_dimensions(
                claim,
                refs[1],
                roles,
                graph,
                tenant_id=TENANT,
                policy=POLICY,
                global_elements=("P3", "P4"),
                rulepack=rulepack,
            )[0]
        )
        args["relation_tags"] = {refs[1].source_id: filtered, **local_relation_tags(context)}
        runs = tag_replicates(**args)
        assert len(runs) == 3
        for run in runs:
            assert run.guarded is not None
            states = {e.element_id: e.state for e in run.guarded.elements}
            assert states["P3"] == expected
            assert states["P4"] == "unknown"  # dedicated assurance service is still required
