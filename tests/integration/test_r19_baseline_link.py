"""Synthetic receipts, real inventory replay / source guards / tagging / rules."""

import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.tagging.element_inventory import build_inventory, selection_from_snapshot
from proofops.application.tagging.qt1_baseline import augment_packet, baseline_links
from proofops.domain.values import SourceRef

from tests.acceptance.test_binding import span
from tests.acceptance.test_citations import RUN
from tests.unit.test_k5_context import case

GOAL = (
    "가상기업은 본사 Scope 1 & 2 온실가스 배출량(tCO2eq)을 "
    "2030년까지 2020년 수준으로 유지하겠습니다."
)
BASE = "가상기업 본사 Scope 1 & 2 온실가스 배출량은 2020년 100 tCO2eq입니다."


def fixture(*, goal=GOAL, baseline=BASE, selected=(1, 2), state="present", extra=None):
    graph, claim = case([goal, baseline, *([extra] if extra else [])], (0, goal))
    blocks = [graph.blocks[0]]
    for b in graph.blocks[1:]:
        c = b.candidates[0]
        c = replace(c, source=replace(c.source, physical_page=2))
        blocks.append(replace(b, candidates=(c,)))
    graph = replace(
        graph,
        blocks=tuple(blocks),
        candidates=tuple(
            replace(batch, blocks=tuple(b.candidates[0] for b in blocks))
            for batch in graph.candidates
        ),
    )
    focal = claim.source_refs[0]
    dimensions = {
        k: span(focal, value)
        for k, value in dict(
            entity="가상기업",
            metric="온실가스 배출량",
            facility="본사",
            scope="Scope 1 & 2",
            reporting_period="2030년",
        ).items()
        if value in goal
    }
    context = ClaimContext(claim, dimensions)
    selection = selection_from_snapshot(
        dict(
            document=dict(
                version_id=graph.document_version_id, sha256=graph.source_sha256, page_count=2
            ),
            selected_pages=list(selected),
        ),
        graph,
        RUN,
    )

    def responder(request):
        records = []
        for source in request["untrusted_document_data"]["spans"]:
            ref = source["source_ref"]
            if ref["source_id"] == focal.source_id:
                continue

            def attr(text):
                if text not in ref["quote"]:
                    return None
                r = asdict(span(SourceRef(**ref), text))
                return {k: r[k] for k in ("source_id", "char_start", "char_end")}

            records.append(
                dict(
                    element_id="G3",
                    state=state,
                    evidence={k: ref[k] for k in ("source_id", "char_start", "char_end")},
                    attributes=dict(
                        subject=attr("가상기업"),
                        metric=attr("온실가스 배출량"),
                        site=attr("본사"),
                        period=attr("2020년"),
                    ),
                )
            )
        return dict(
            **{
                k: request[k]
                for k in (
                    "request_id",
                    "request_signature",
                    "packet_sha256",
                    "replicate_id",
                    "model_sha256",
                    "prompt_sha256",
                )
            },
            provider_response_id="synthetic-" + request["request_id"],
            synthetic=True,
            status="succeeded",
            raw_response_json=json.dumps(
                dict(
                    complete=True,
                    records=records,
                    packet_sha256=request["packet_sha256"],
                    replicate_id=request["replicate_id"],
                )
            ),
        )

    inventory = build_inventory(graph, selection, model_sha256="a" * 64, invoke=responder)
    return graph, context, inventory


def receipt(graph, context, inventory):
    return baseline_links(context, inventory, graph, run_id=RUN, tenant_id=graph.tenant_id)


def test_cross_page_verified_baseline_keeps_roles_and_replays():
    g, c, inv = fixture()
    found = receipt(g, c, inv)
    assert len(found["links"]) == 1
    link = found["links"][0]
    assert link["value"]["quote"] == "100" and link["unit"]["quote"] == "tCO2eq"
    assert link["period"]["quote"] == "2020" and link["period"]["page_num"] == 2
    assert link["elements"] == ["G2", "G3"] and link["meaning"] == "maintenance_at_baseline"
    assert "2030" not in json.dumps(link) and "0%" not in json.dumps(link)
    assert receipt(g, c, inv) == found
    forged = deepcopy(inv)
    forged["candidates"][0]["votes"]["1"]["state"] = (
        "present" if inv["candidates"][0]["votes"]["1"]["state"] != "present" else "unknown"
    )
    with pytest.raises(ValueError, match="REPLAY_MISMATCH"):
        receipt(g, c, forged)


@pytest.mark.parametrize(
    "changed",
    [
        BASE.replace("2020", "2019"),
        BASE.replace("tCO2eq", "MWh"),
        BASE.replace("Scope 1 & 2", "Scope 1"),
        BASE.replace("본사", "그룹"),
        BASE.replace("가상기업", "다른기업"),
        BASE.replace("온실가스 배출량", "전력 사용량"),
        BASE.replace("2020", "2050"),
        BASE.replace("100", "-"),
        BASE.replace("입니다", "으로 전망됩니다"),
    ],
)
def test_mismatched_baselines_never_produce_links(changed):
    g, c, inv = fixture(baseline=changed)
    assert not receipt(g, c, inv)["links"]


@pytest.mark.parametrize("state", ["unknown", "unreadable", "conflict", "not_applicable"])
def test_nonpresent_inventory_stays_held(state):
    g, c, inv = fixture(state=state)
    assert not receipt(g, c, inv)["links"]


def test_outside_selection_and_competing_value_never_become_absence_or_majority():
    g, c, inv = fixture(selected=(1,))
    result = receipt(g, c, inv)
    assert result["links"] == [] and result["outside_selection"] == "not_run"
    g, c, inv = fixture(extra=BASE.replace("100", "110"))
    assert receipt(g, c, inv)["links"] == []
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        baseline_links(
            c, inv, g, run_id="00000000-0000-0000-0000-000000000001", tenant_id=g.tenant_id
        )


@pytest.mark.parametrize(
    "goal",
    [
        GOAL.replace("본사", "본사를 포함한 그룹"),
        GOAL.replace("tCO2eq", "MtCO2eq"),
        GOAL.replace("tCO2eq", "tCO2eq/매출"),
        GOAL.replace("tCO2eq", "천tCO2eq"),
    ],
)
def test_target_qualifiers_and_unit_scale_cannot_disappear(goal):
    g, c, inv = fixture(goal=goal)
    assert not receipt(g, c, inv)["links"]


def test_fresh_three_replica_tagging_credit_and_rule_scope(tmp_path):
    from proofops.application.analysis_profile import QT1_V25_POLICY
    from proofops.application.budget import TokenUsage
    from proofops.application.tagging.consensus import form_consensus
    from proofops.application.tagging.service import RawTagResponse
    from proofops.application.tagging.tracks import TrackCandidate
    from proofops.domain.rules.engine import RuleContext, evaluate
    from proofops.domain.rules.qt1_baseline import SOURCE_SCOPE

    from tests.acceptance.test_tagging import execute, setup

    g, context, inv = fixture()
    claim = context.claim
    inputs = setup(tmp_path)
    data = inputs["packet"].to_dict()
    data.pop("packet_sha256")
    from proofops.domain.provenance import canonical_hash

    data.update(
        claim_id=claim.claim_id,
        atomic_quote=claim.quote,
        claim_source_refs=[asdict(r) for r in claim.source_refs],
        graph_sha256=canonical_hash(asdict(g)),
        track="goal",
        safe_harbor_category=None,
        allowed_elements=[f"G{i}" for i in range(1, 9)],
        evidence_candidates=[],
        search_coverage={},
        qt2_contextual_elements_policy=QT1_V25_POLICY["qt2_contextual_elements_policy"],
    )
    from proofops.application.evidence.span_citations import verify_source_ref

    data["claim_source_refs"] = [
        asdict(verify_source_ref(r, g, tenant_id=g.tenant_id)) for r in claim.source_refs
    ]
    link_receipt = receipt(g, context, inv)
    packet = freeze_packet(augment_packet(data, link_receipt))
    selected = [link_receipt["links"][0][k] for k in ("value", "unit", "period")]

    def invoke(request):
        elements = [
            dict(
                element_id=f"G{i}",
                state="present" if i in (2, 3) else "unknown",
                evidence_refs=selected if i in (2, 3) else [],
                normalized_value="100" if i in (2, 3) else None,
                credited_from=None,
                reason_code=None,
            )
            for i in range(1, 9)
        ]
        return RawTagResponse(
            json.dumps(
                dict(
                    claim_id=claim.claim_id,
                    packet_sha256=packet.packet_sha256,
                    replicate_id=request["replicate_id"],
                    track="goal",
                    safe_harbor_category=None,
                    elements=elements,
                    superlative_quote=None,
                    warnings=[],
                )
            ),
            TokenUsage(10, 5, 0, 0, 1, "succeeded", f"synthetic-final-{request['replicate_id']}"),
            True,
        )

    inputs.update(
        packet=packet,
        context=context,
        track=TrackCandidate(claim, "goal", None),
        original=g,
        relation_tags={},
        invoke=invoke,
        qt1_baseline_inventory=inv,
        semantic_policy=QT1_V25_POLICY["semantic_admission"],
    )
    runs = execute(inputs)
    assert all(r.status == "needs_review" for r in runs), [(r.status, r.errors) for r in runs]
    for run in runs:
        assert {e.element_id for e in run.guarded.elements if e.state == "present"} == {"G2", "G3"}
        assert dict(run.source_scopes)["G2"] == SOURCE_SCOPE
    result = form_consensus(
        runs,
        packet=packet,
        rulepack=inputs["rulepack"],
        tenant_id=g.tenant_id,
        tag_revision=1,
        profile="grade-relevant-unanimity-v3",
    )
    tags = result.confirmed_tags
    assert tags is not None
    assert {f.source_scope for f in tags.facts if f.state == "present"} == {SOURCE_SCOPE}
    rule_context = RuleContext(
        g.tenant_id,
        g.document_version_id,
        claim.claim_id,
        packet.packet_sha256,
        local_synthetic=True,
    )
    decision = evaluate(tags, rule_context, inputs["rulepack"])
    assert decision.evidence_grade is None  # G1/G4 remain unknown; no false confirmation
    assert (
        evaluate(
            replace(tags, safe_harbor_category="forward_looking"), rule_context, inputs["rulepack"]
        ).evidence_grade
        is None
    )
    with pytest.raises(ValueError, match="INVENTORY_REQUIRED"):
        execute(inputs | dict(qt1_baseline_inventory=None))
