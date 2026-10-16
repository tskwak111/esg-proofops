"""R19-T01/T07 and DEC-93 AP-06; synthetic receipts, real admission/rules."""

import json
from dataclasses import asdict, replace

import pytest
from proofops.application.evidence.binding import ClaimContext
from proofops.application.tagging.analysis_scope import InventoryIndex
from proofops.application.tagging.element_inventory import build_inventory, selection_from_snapshot
from proofops.application.tagging.v1_activity_links import POLICY, link_inventory

from tests.acceptance.test_binding import span
from tests.acceptance.test_rules import pack
from tests.unit.test_k5_context import case

CLAIM = "가상기업은 2024년 서울공장 환경경영시스템을 운영합니다."
EVIDENCE = "가상기업은 2024년 서울공장 환경경영시스템의 내부 심사를 매월 실시하고 있습니다."


def fixture(eid="M4", *, claim_text=CLAIM, evidence_text=EVIDENCE, attrs=None, mutate=None):
    graph, claim = case([claim_text, evidence_text], (0, claim_text))
    values = attrs or dict(
        subject="가상기업", metric="환경경영시스템", site="서울공장", period="2024년"
    )
    roles = dict(subject="entity", metric="metric", site="facility", period="reporting_period")
    dims = {
        roles[k]: span(claim.source_refs[0], v) if v and v in claim_text else None
        for k, v in values.items()
    }
    context = ClaimContext(claim, dims)
    selection = selection_from_snapshot(
        dict(
            document=dict(
                version_id=graph.document_version_id, sha256=graph.source_sha256, page_count=1
            ),
            selected_pages=[1],
        ),
        graph,
        "11111111-1111-4111-8111-111111111119",
    )

    def respond(request):
        evidence = graph.blocks[1].source_ref()

        def loc(value):
            if value is None or value not in evidence.quote:
                return None
            r = span(evidence, value)
            return {k: getattr(r, k) for k in ("source_id", "char_start", "char_end")}

        raw = dict(
            complete=True,
            packet_sha256=request["packet_sha256"],
            replicate_id=request["replicate_id"],
            records=[
                dict(
                    element_id=eid,
                    state="present",
                    evidence={
                        k: getattr(evidence, k) for k in ("source_id", "char_start", "char_end")
                    },
                    attributes={k: loc(v) for k, v in values.items()},
                )
            ],
        )
        response = {
            k: request[k]
            for k in (
                "request_id",
                "request_signature",
                "packet_sha256",
                "replicate_id",
                "model_sha256",
                "prompt_sha256",
            )
        }
        response.update(
            status="succeeded",
            synthetic=True,
            provider_response_id="sim-" + request["request_id"],
            raw_response_json=json.dumps(raw),
        )
        if mutate:
            mutate(response, raw)
            response["raw_response_json"] = json.dumps(raw)
        return response

    inventory = build_inventory(graph, selection, model_sha256="a" * 64, invoke=respond)
    return context, graph, inventory


def links(context, graph, inventory):
    return link_inventory(
        context,
        InventoryIndex(inventory, graph),
        graph,
        run_id=inventory["selection"]["run_id"],
        tenant_id=graph.tenant_id,
        rulepack=pack(),
        policy=POLICY,
    )


@pytest.mark.parametrize("eid", ["M1", "M2", "M4"])
def test_explicit_activity_across_paragraphs(eid):
    context, graph, inv = fixture(eid)
    result = links(context, graph, inv)
    assert [x["element"]["element_id"] for x in result["links"]] == [eid]
    assert result["links"][0]["source_scope"] == "global_bound"
    assert result["links"][0]["replica_ids"] == [1, 2, 3]
    assert result["grade_credit"] is False
    assert links(context, graph, inv) == result


@pytest.mark.parametrize(
    "change",
    [
        "actor",
        "activity",
        "site",
        "period",
        "missing_period",
        "future",
        "unknown",
        "conflict",
        "failed",
        "duplicate_provider",
    ],
)
def test_no_inferred_or_disagreeing_activity_links(change):
    text = EVIDENCE
    attrs = dict(subject="가상기업", metric="환경경영시스템", site="서울공장", period="2024년")
    replacements = dict(
        actor=("가상기업", "다른기업"),
        activity=("환경경영시스템", "품질경영시스템"),
        site=("서울공장", "부산공장"),
        period=("2024년", "2025년"),
    )
    if change in replacements:
        old, new = replacements[change]
        text = text.replace(old, new)
    if change == "missing_period":
        text = text.replace("2024년 ", "")
    if change == "future":
        text = text.replace("실시하고 있습니다", "실시할 예정입니다")

    def mutate(response, raw):
        if raw["replicate_id"] == 3:
            if change in ("unknown", "conflict"):
                raw["records"][0]["state"] = change
            if change == "failed":
                response["status"] = "failed"
        if change == "duplicate_provider":
            response["provider_response_id"] = "duplicate"

    context, graph, inv = fixture(evidence_text=text, attrs=attrs, mutate=mutate)
    assert links(context, graph, inv)["links"] == []


def test_legacy_qt2_remains_local():
    from proofops.application.tagging.qt2_inventory import link_inventory as legacy

    context, graph, inv = fixture()
    assert (
        legacy(
            context,
            inv,
            graph,
            run_id=inv["selection"]["run_id"],
            tenant_id=graph.tenant_id,
            rulepack=pack(),
        )["links"]
        == []
    )


def test_policy_and_inventory_tampering_rejected():
    context, graph, inv = fixture()
    with pytest.raises(ValueError, match="V1_ACTIVITY_POLICY"):
        link_inventory(
            context,
            inv,
            graph,
            run_id=inv["selection"]["run_id"],
            tenant_id=graph.tenant_id,
            rulepack=pack(),
            policy=POLICY | dict(replicas=[1]),
        )
    inv["selection"]["selected_pages"] = []
    with pytest.raises(ValueError):
        links(context, graph, inv)


def scope_inputs(tmp_path, *, eid="M2", inventory_failure=None, raw_state="unknown"):
    from proofops.application.budget import TokenUsage
    from proofops.application.evidence.binding import local_relation_tags
    from proofops.application.evidence.retrieval import freeze_track_packet, retrieve_evidence
    from proofops.application.tagging.element_inventory import POLICY as SC1_POLICY
    from proofops.application.tagging.service import RawTagResponse, tag_replicates
    from proofops.application.tagging.tracks import TrackCandidate
    from proofops.domain.rules.engine import RuleContext

    from tests.acceptance.test_retrieval import SyntheticSearch
    from tests.acceptance.test_tagging import setup

    inputs = setup(tmp_path)
    context, graph, _ = fixture(eid)
    claim = context.claim
    rules = pack()
    track = TrackCandidate(claim, "management", None)
    run_id = inputs["packet"].to_dict()["run_id"]
    packet = retrieve_evidence(
        claim,
        graph,
        SyntheticSearch(graph),
        tenant_id=graph.tenant_id,
        run_id=run_id,
        index_generation="synthetic-v1",
        rulepack=rules,
        document_context={},
        token_counter=lambda _: 1,
    )
    packet = freeze_track_packet(packet, track=track, rulepack=rules)

    def tag(request):
        payload = {k: request[k] for k in ("claim_id", "packet_sha256", "replicate_id")}
        payload.update(
            track="management",
            safe_harbor_category=None,
            superlative_quote=None,
            warnings=[],
            elements=[
                dict(
                    element_id=f"M{i}",
                    state="present" if i == 1 else raw_state if i == int(eid[1]) else "unknown",
                    evidence_refs=[asdict(claim.source_refs[0])] if i == 1 else [],
                    normalized_value=None,
                    credited_from=None,
                    reason_code=None,
                )
                for i in range(1, 7)
            ],
        )
        return RawTagResponse(
            json.dumps(payload),
            TokenUsage(10, 5, 0, 0, 1, "succeeded", f"claim-sim-{request['replicate_id']}"),
            True,
        )

    inputs.update(
        packet=packet,
        context=context,
        original=graph,
        track=track,
        relation_tags=local_relation_tags(context),
        invoke=tag,
    )
    runs = tuple(replace(r, product_variant=False) for r in tag_replicates(**inputs))
    assert all(r.guarded for r in runs), [r.errors for r in runs]
    scope = selection_from_snapshot(
        dict(
            document=dict(
                version_id=graph.document_version_id, sha256=graph.source_sha256, page_count=1
            ),
            selected_pages=[1],
        ),
        graph,
        run_id,
    )
    evidence = graph.blocks[1].source_ref()
    attrs = {
        k: {
            field: getattr(span(evidence, value), field)
            for field in ("source_id", "char_start", "char_end")
        }
        for k, value in dict(
            subject="가상기업", metric="환경경영시스템", site="서울공장", period="2024년"
        ).items()
    }

    def inventory_response(request):
        records = [
            dict(
                element_id=element,
                state="present" if element == eid else "not_applicable",
                evidence={k: getattr(evidence, k) for k in ("source_id", "char_start", "char_end")},
                attributes=attrs,
            )
            for element in SC1_POLICY["terms"]
        ]
        # Complete the focal claim's own M1/M2 cues as well as the remote
        # evidence. These independent synthetic labels are retained in replay.
        if eid in ("M1", "M2") and inventory_failure != "uncovered":
            focal = context.claim.source_refs[0]
            records.append(
                dict(
                    element_id=eid,
                    state=inventory_failure
                    if inventory_failure in ("unknown", "conflict", "unreadable")
                    else "present",
                    evidence={
                        k: getattr(focal, k) for k in ("source_id", "char_start", "char_end")
                    },
                    attributes={
                        k: None
                        if inventory_failure
                        in ("unknown", "conflict", "unreadable", "present_without_roles")
                        else {
                            field: getattr(context.dimensions[role], field)
                            for field in ("source_id", "char_start", "char_end")
                        }
                        for k, role in dict(
                            subject="entity",
                            metric="metric",
                            site="facility",
                            period="reporting_period",
                        ).items()
                    },
                )
            )
        raw = dict(
            complete=True,
            records=records,
            packet_sha256=request["packet_sha256"],
            replicate_id=request["replicate_id"],
        )
        result = {
            k: request[k]
            for k in (
                "request_id",
                "request_signature",
                "packet_sha256",
                "replicate_id",
                "model_sha256",
                "prompt_sha256",
            )
        }
        result.update(
            status="succeeded",
            synthetic=True,
            provider_response_id="inventory-sim-" + request["request_id"],
        )
        if inventory_failure == "partial" and request["replicate_id"] == 3:
            raw["complete"] = False
        result["raw_response_json"] = json.dumps(raw)
        return result

    inv = build_inventory(graph, scope, model_sha256="a" * 64, invoke=inventory_response)
    return dict(
        runs=runs,
        packet=packet,
        context=context,
        graph=graph,
        rulepack=rules,
        rule_context=RuleContext(
            claim.tenant_id,
            claim.document_version_id,
            claim.claim_id,
            packet.packet_sha256,
            local_synthetic=True,
        ),
        inventory=inv,
    )


def test_linked_m2_reaches_scoped_e2_but_never_manufactures_m3(tmp_path):
    from proofops.application.tagging.analysis_scope import analyze_scope, replay_scope
    from proofops.domain.provenance import canonical_hash

    inputs = scope_inputs(tmp_path)
    raw_hash = canonical_hash([asdict(r) for r in inputs["runs"]])
    old = analyze_scope(**inputs)
    new = analyze_scope(**inputs, v1_activity_policy=POLICY)
    assert old["sc1_confirmation"] is None
    assert new["sc1_confirmation"]["evidence_grade"] == "E2"
    assert new["sc1_confirmation"]["confirmation_basis"] == "analysis_scope"
    assert next(e for e in new["sc1_elements"] if e["element_id"] == "M2")["state"] == "present"
    assert (
        next(e for e in new["sc1_elements"] if e["element_id"] == "M3")["state"]
        == "absent_in_scope"
    )
    assert new["v1_effective_rulepack"]["sha256"] != inputs["rulepack"].sha256
    assert replay_scope(new, **inputs) == new
    assert canonical_hash([asdict(r) for r in inputs["runs"]]) == raw_hash
    assert analyze_scope(**inputs) == old


@pytest.mark.parametrize(
    "failure", ["unknown", "conflict", "unreadable", "uncovered", "present_without_roles"]
)
def test_unattributed_or_uncovered_inventory_cannot_be_bypassed(tmp_path, failure):
    from proofops.application.tagging.analysis_scope import analyze_scope

    inputs = scope_inputs(tmp_path, inventory_failure=failure)
    result = analyze_scope(**inputs, v1_activity_policy=POLICY)
    assert result["sc1_confirmation"] is None
    assert next(e for e in result["sc1_elements"] if e["element_id"] == "M2")["state"] != "present"
    assert (
        "V1_ACTIVITY_UNCOVERED_CUES"
        if failure == "uncovered"
        else "V1_ACTIVITY_INVENTORY_UNRESOLVED"
    ) in result["reasons"]


@pytest.mark.parametrize(
    "failure", ["partial", "raw_conflict", "raw_absent", "source", "public_synthetic"]
)
def test_scope_safety_holds_survive_new_links(tmp_path, failure):
    from proofops.application.tagging.analysis_scope import analyze_scope

    inputs = scope_inputs(
        tmp_path,
        inventory_failure="partial" if failure == "partial" else None,
        raw_state=failure.removeprefix("raw_") if failure.startswith("raw_") else "unknown",
    )
    if failure == "source":
        inputs["context"] = replace(
            inputs["context"], claim=replace(inputs["context"].claim, source_quality="unverified")
        )
    if failure == "public_synthetic":
        inputs["rule_context"] = replace(inputs["rule_context"], local_synthetic=False)
        inputs["rulepack"] = replace(
            inputs["rulepack"],
            status="active",
            approved_by="reviewer",
            approved_at="2026-10-15T00:00:00Z",
        )
    result = analyze_scope(**inputs, v1_activity_policy=POLICY)
    assert result["sc1_confirmation"] is None
    assert next(e for e in result["sc1_elements"] if e["element_id"] == "M2")["state"] != "present"


def test_new_profile_is_additive_and_keeps_v24_default():
    from proofops.application.analysis_profile import (
        FINALS_I24_POLICY,
        V1_ACTIVITY_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert (
        policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I24_POLICY)) == FINALS_I24_POLICY
    )
    pin = canonical_hash(V1_ACTIVITY_POLICY)
    assert policy_for(V2_PROFILE, pinned_hash=pin) == V1_ACTIVITY_POLICY
    assert publication_policy_for(V2_PROFILE, pinned_hash=pin) == V1_ACTIVITY_POLICY
    assert POLICY["profile"].startswith("v1_")


def diagram_case(*, boundary=True, explicit=True, stage=1):
    from pathlib import Path

    from proofops.application.ingest.graph_fusion import CanonicalEdge

    data = json.loads(Path("tests/fixtures/v1_activity_links.json").read_text())
    claim_text = next(r for r in data["preserved_rows"] if r["ID"] == "D11")["검토할 인용 후보"]
    source_row = data["new_row"] if stage == 1 else data["supporting_stage3"]
    evidence_text = source_row["quote"] if boundary else data["negative"]
    graph, claim = case([claim_text, "RE100 검토 프로세스", evidence_text], (0, claim_text))
    focal, heading, evidence = [b.source_ref() for b in graph.blocks]
    if explicit:
        graph = replace(
            graph,
            edges=(
                CanonicalEdge(evidence.source_id, focal.source_id, "same_statement"),
                CanonicalEdge(evidence.source_id, heading.source_id, "section_parent"),
            ),
        )
    context = ClaimContext(
        claim,
        dict(
            entity=span(focal, "기아"),
            metric=span(focal, "검토 프로세스"),
            facility=None,
            reporting_period=None,
        ),
    )
    selection = selection_from_snapshot(
        dict(
            document=dict(
                version_id=graph.document_version_id, sha256=graph.source_sha256, page_count=1
            ),
            selected_pages=[1],
        ),
        graph,
        "11111111-1111-4111-8111-111111111119",
    )
    attrs = dict(
        subject=span(focal, "기아"),
        metric=span(heading, "검토 프로세스"),
        site=span(evidence, "전 사업장" if stage == 1 else "사업장별") if boundary else None,
        period=None,
    )

    def invoke(request):
        response = {
            k: request[k]
            for k in (
                "request_id",
                "request_signature",
                "packet_sha256",
                "replicate_id",
                "model_sha256",
                "prompt_sha256",
            )
        }

        def loc(ref):
            return (
                {k: getattr(ref, k) for k in ("source_id", "char_start", "char_end")}
                if ref
                else None
            )

        raw = dict(
            complete=True,
            packet_sha256=request["packet_sha256"],
            replicate_id=request["replicate_id"],
            records=[
                dict(
                    element_id="M2",
                    state="present",
                    evidence=loc(evidence),
                    attributes={k: loc(v) for k, v in attrs.items()},
                )
            ],
        )
        response.update(
            status="succeeded",
            synthetic=True,
            provider_response_id="sim-" + request["request_id"],
            raw_response_json=json.dumps(raw),
        )
        return response

    inv = build_inventory(graph, selection, model_sha256="a" * 64, invoke=invoke)
    return context, graph, inv


def test_d11_adds_m2_without_renaming_m1_m4():
    from pathlib import Path

    data = json.loads(Path("tests/fixtures/v1_activity_links.json").read_text())
    elements = {r["ID"]: r["요소ID"] for r in data["preserved_rows"] if "요소ID" in r}
    assert elements == {"D11-E1": "M1", "D11-E2": "M4"}
    context, graph, inv = diagram_case()
    result = links(context, graph, inv)
    assert [x["element"]["element_id"] for x in result["links"]] == ["M2"]
    link = result["links"][0]
    assert link["qualified_target"]["quote"] == "전 사업장"
    assert link["element"]["evidence_refs"][0]["quote"] == data["new_row"]["quote"]
    assert link["period_role"] == "not_stated_no_period_credit"
    assert link["claim_roles"]["facility"] is None
    assert link["claim_roles"]["reporting_period"] is None
    assert len(link["structural_edges"]) == 2


@pytest.mark.parametrize("boundary,explicit", [(False, True), (True, False)])
def test_d11_steps_or_company_without_explicit_link_never_supply_m2(boundary, explicit):
    context, graph, inv = diagram_case(boundary=boundary, explicit=explicit)
    assert links(context, graph, inv)["links"] == []


def test_d11_stage3_detail_alone_does_not_identify_actual_target():
    context, graph, inv = diagram_case(stage=3)
    assert graph.blocks[2].raw_text == "사업장별 설치부지·발전량·경제성 분석"
    assert links(context, graph, inv)["links"] == []


@pytest.mark.parametrize(
    "target",
    [
        "국내 전 생산 사업장 및 글로벌 17개 생산 사업장 중 15개 사업장",
        "직접운영 주요 사업장(배출량 95% 이상)",
    ],
)
def test_actual_qualified_boundaries_never_expand_to_all_sites(target):
    attrs = dict(subject="가상기업", metric="ISO 14001", site=target, period=None)
    claim_text = "가상기업은 ISO 14001 인증을 유지하고 있습니다."
    evidence_text = f"가상기업의 ISO 14001 인증은 {target}에 적용됩니다."
    context, graph, inv = fixture(
        "M2", claim_text=claim_text, evidence_text=evidence_text, attrs=attrs
    )
    result = links(context, graph, inv)
    assert len(result["links"]) == 1
    assert result["links"][0]["qualified_target"]["quote"] == target
    assert result["links"][0]["element"]["evidence_refs"][0]["quote"] == evidence_text
    context = replace(context, dimensions=dict(context.dimensions) | dict(scope=None))
    assert len(links(context, graph, inv)["links"]) == 1
    context, graph, inv = fixture(
        "M2",
        claim_text="가상기업은 전 사업장의 ISO 14001 인증을 유지하고 있습니다.",
        evidence_text=evidence_text,
        attrs=attrs,
    )
    context = replace(
        context,
        dimensions=dict(context.dimensions)
        | dict(facility=span(context.claim.source_refs[0], "전 사업장")),
    )
    assert links(context, graph, inv)["links"] == []


@pytest.mark.parametrize(
    "text,target",
    [
        ("가상기업의 환경경영시스템은 전사 전략과 연계합니다.", "전사"),
        ("가상기업의 환경경영시스템은 EPA, ECHA와 협의합니다.", "EPA"),
        ("보고 범위: 가상기업의 환경경영시스템은 국내 전 사업장을 포함합니다.", "국내 전 사업장"),
    ],
)
def test_r17_strategy_regulator_and_report_scope_are_not_activity_boundary(text, target):
    context, graph, inv = fixture(
        "M2",
        claim_text="가상기업은 환경경영시스템을 운영합니다.",
        evidence_text=text,
        attrs=dict(subject="가상기업", metric="환경경영시스템", site=target, period=None),
    )
    assert links(context, graph, inv)["links"] == []


def test_ap06_derived_rulepack_changes_only_m1_m4_scopes():
    from proofops.application.tagging.v1_activity_links import effective_rulepack

    original = pack()
    derived = effective_rulepack(original)
    for path in original.files:
        before, after = original.file_content(path), derived.file_content(path)
        if path != "rubric/elements.yaml":
            assert after == before | dict(version=derived.version)
        else:
            for a, b in zip(before["elements"], after["elements"], strict=True):
                if a["id"] in ("M1", "M4"):
                    assert b == a | dict(
                        source_scopes=[*a["source_scopes"], "global_bound"],
                        binding_policy=POLICY["profile"],
                    )
                else:
                    assert a == b


def test_worker_opt_in_checkpoint_replays_v1_receipt(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import V1_ACTIVITY_POLICY
    from proofops.application.runs import RunService
    from proofops.domain.provenance import canonical_hash

    from tests.integration.test_local_tag_runner import TENANT, verified_setup
    from tests.integration.test_sc1_scope import responder

    init = RunService.__init__

    def selected(self, *args, **kwargs):
        kwargs.update(
            pipeline_profile="finals-unattended-v2",
            analysis_policy_sha256=canonical_hash(V1_ACTIVITY_POLICY),
        )
        init(self, *args, **kwargs)

    monkeypatch.setattr(RunService, "__init__", selected)
    service, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    calls = []

    def provider(graph, scope):
        calls.append(scope)
        return build_inventory(graph, scope, model_sha256="a" * 64, invoke=responder)

    runner.sc1_inventory_provider = provider
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "completed"
    saved = runner.tags.load_snapshot(TENANT, run_id)
    assert len(calls) == 1
    receipts = [r["sc1_scope_receipt"] for r in saved["claims"] if "sc1_scope_receipt" in r]
    assert receipts and all(r["policy"]["v1_activity_links"] == POLICY for r in receipts)
    assert runner.tags.load_snapshot(TENANT, run_id) == saved


@pytest.mark.parametrize("eid", ["M1", "M4"])
def test_ap06_positive_facts_reach_the_rule_engine(tmp_path, eid):
    from proofops.application.tagging.analysis_scope import analyze_scope

    inputs = scope_inputs(tmp_path, eid=eid)
    result = analyze_scope(**inputs, v1_activity_policy=POLICY)
    assert next(e for e in result["sc1_elements"] if e["element_id"] == eid)["state"] == "present"
    assert result["v1_projection"]["grade_range"]["floor"] == "E1"
    assert result["v1_effective_rulepack"]["rule_pack_id"] != inputs["rulepack"].rule_pack_id


@pytest.mark.parametrize("eid", ["M3", "G2", "G3", "P1", "P2"])
def test_numeric_and_assurance_elements_have_no_v1_route(eid):
    context, graph, inv = fixture(eid)
    assert links(context, graph, inv)["links"] == []


def test_cross_tenant_run_and_graph_are_rejected():
    context, graph, inv = fixture()
    for kw in [
        dict(tenant_id="11111111-1111-4111-8111-111111111119"),
        dict(run_id="11111111-1111-4111-8111-111111111118"),
    ]:
        options = (
            dict(
                run_id=inv["selection"]["run_id"],
                tenant_id=graph.tenant_id,
                rulepack=pack(),
                policy=POLICY,
            )
            | kw
        )
        with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
            link_inventory(context, inv, graph, **options)
    index = InventoryIndex(inv, graph)
    with pytest.raises(ValueError, match="GRAPH_MISMATCH"):
        link_inventory(
            context,
            index,
            replace(graph, edges=()),
            run_id=inv["selection"]["run_id"],
            tenant_id=graph.tenant_id,
            rulepack=pack(),
            policy=POLICY,
        )


def test_wrong_profile_pin_and_lowered_threshold_are_rejected(tmp_path):
    from proofops.application.tagging.analysis_scope import analyze_scope
    from proofops.application.tagging.v1_activity_links import policy_from_profile

    with pytest.raises(ValueError, match="PIN_MISMATCH"):
        policy_from_profile(dict(v1_activity_links=POLICY, v1_activity_links_sha256="f" * 64))
    with pytest.raises(ValueError, match="THREE_REPLICAS"):
        analyze_scope(**scope_inputs(tmp_path), required_present_votes=2, v1_activity_policy=POLICY)


def test_lg_p36_verified_passage_contract_preserves_15_of_17():
    claim_text = (
        "LG화학의 환경경영시스템(Environmental Management System, EMS)은 ISO 14001\n"
        "인증을 통해 제3자 검증을 받고 있으며, 내부 감사를 통해 "
        "운영 적정성을 정기적으로 점검하고 있습니다."
    )
    boundary = (
        "ISO 14001 인증은 국내 전 생산 사업장에 적용되고 있으며, 글로벌 사업장의 경우 총 17개 생산 "
        "사업장 중 15개 사업장에서 인증을 완료하였습니다."
    )
    target = "국내 전 생산 사업장"
    context, graph, inv = fixture(
        "M2",
        claim_text=claim_text,
        evidence_text=claim_text + " " + boundary,
        attrs=dict(
            subject="LG화학",
            metric="환경경영시스템(Environmental Management System, EMS)",
            site=target,
            period=None,
        ),
    )
    result = links(context, graph, inv)
    assert len(result["links"]) == 1
    assert (
        "17개 생산 사업장 중 15개 사업장"
        in result["links"][0]["element"]["evidence_refs"][0]["quote"]
    )
    assert result["links"][0]["claim_roles"]["reporting_period"] is None
    from proofops.application.tagging.qt2_inventory import link_inventory as legacy

    assert (
        legacy(
            context,
            inv,
            graph,
            run_id=inv["selection"]["run_id"],
            tenant_id=graph.tenant_id,
            rulepack=pack(),
        )["links"]
        == []
    )
