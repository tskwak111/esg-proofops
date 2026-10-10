"""DEC-23: synthetic source guards plus immutable legacy policy replay."""

from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from proofops.adapters.local.missing_evidence import validated_present_refs
from proofops.application.evidence.binding import ClaimContext, accept_binding
from proofops.application.evidence.report_level import (
    ACTIVITY_SCOPE_V2,
    REPORT_SCOPE_V1,
    check_report_level,
    report_level_policies,
)
from proofops.domain.rulepacks import pack_content_hash, snapshot_from_validated

from tests.acceptance.test_binding import corpus, span, tags
from tests.acceptance.test_rules import pack
from tests.unit.test_report_level_evidence import CLAIM, PAGES, SCOPE


def scope_pack(policy):
    original = pack()
    files = {p: original.file_content(p) for p in original.files}
    m2 = next(e for e in files["rubric/elements.yaml"]["elements"] if e["id"] == "M2")
    if policy is None:
        m2.pop("binding_policy", None)
    else:
        m2["binding_policy"] = policy
    data = asdict(original)
    data["sha256"] = pack_content_hash(data, files)
    return snapshot_from_validated(data, files)


@pytest.mark.parametrize(
    "heading,quote",
    [
        (
            "보고 범위 및 경계",
            "환경 및 사회 관련 정보는 연결재무제표의 일부로 "
            "국내 본사와 해외 판매법인을 포함하고 있습니다.",
        ),
        (
            "보고 경계",
            "국내 전 사업장과 중국 생산 사업장의 "
            "지속가능경영 활동과 성과를 대상으로 하고 있습니다.",
        ),
    ],
)
def test_report_scope_is_rejected_by_new_policy_and_generic_binding(heading, quote):
    graph, claim, refs = corpus()
    block = next(b for b in graph.blocks if b.source_id == refs[1].source_id)
    candidate = block.candidates[block.winner]
    text = heading + "\n" + quote
    changed = replace(
        block,
        candidates=(
            replace(candidate, source=replace(candidate.source, raw_text=text, char_end=len(text))),
        ),
    )
    graph = replace(graph, blocks=tuple(changed if b == block else b for b in graph.blocks))
    ref = changed.source_ref()
    assert (
        check_report_level(
            "M2",
            ACTIVITY_SCOPE_V2,
            (ref,),
            claim_refs=claim.source_refs,
            claim_quote=claim.quote,
            page_texts={ref.page_num: [text]},
            credited_from=ref.source_id,
        )
        is False
    )
    assert (
        accept_binding(
            ClaimContext(claim, tags(refs[0])),
            ref,
            {},
            original=graph,
            tenant_id=claim.tenant_id,
            rulepack=scope_pack(ACTIVITY_SCOPE_V2),
            element_id="M2",
        )
        == "rejected"
    )
    inputs = SimpleNamespace(
        validate=lambda: None,
        context=ClaimContext(claim, tags(refs[0])),
        relation_tags={},
        rulepack=scope_pack(ACTIVITY_SCOPE_V2),
    )
    element = dict(
        element_id="M2",
        state="present",
        evidence_refs=[asdict(ref)],
        reason_code=REPORT_SCOPE_V1,
        credited_from=ref.source_id,
    )
    assert validated_present_refs([element], inputs, claim, graph) == {}


def test_local_activity_scope_and_global_method_still_bind():
    graph, claim, refs = corpus()
    # Real local literal guard; no report-wide scope prose.
    assert (
        accept_binding(
            ClaimContext(claim, tags(refs[0])),
            span(refs[0], "공장A"),
            tags(refs[0]),
            original=graph,
            tenant_id=claim.tenant_id,
            rulepack=scope_pack(ACTIVITY_SCOPE_V2),
            element_id="M2",
        )
        == "accepted"
    )
    # Same semantic roles elsewhere: method P3 stays global.
    assert (
        accept_binding(
            ClaimContext(claim, tags(refs[0])),
            refs[1],
            tags(refs[1]),
            original=graph,
            tenant_id=claim.tenant_id,
            rulepack=scope_pack(ACTIVITY_SCOPE_V2),
            element_id="P3",
        )
        == "accepted"
    )


def test_legacy_checker_and_pack_hash_remain_distinct():
    old, new = scope_pack(None), scope_pack(ACTIVITY_SCOPE_V2)
    assert old.sha256 != new.sha256
    assert report_level_policies(old)["M2"] == REPORT_SCOPE_V1
    assert report_level_policies(new)["M2"] == ACTIVITY_SCOPE_V2
    assert check_report_level(
        "M2",
        REPORT_SCOPE_V1,
        (SCOPE,),
        claim_refs=CLAIM,
        claim_quote=CLAIM[0].quote,
        page_texts=PAGES,
        credited_from=SCOPE.source_id,
    )
    assert (
        pack().file_content("rubric/elements.yaml")["elements"][0]
        == new.file_content("rubric/elements.yaml")["elements"][0]
    )


def test_same_paragraph_company_wide_activity_scope_is_accepted():
    from tests.acceptance.test_claims import discover, graph_of

    text = "회사A는 2025년 환경경영체계를 운영합니다. 이 활동은 전사 공장 전체에 적용됩니다."
    graph = graph_of(text)
    graph = replace(graph, blocks=tuple(replace(b, quality="verified") for b in graph.blocks))
    claim = discover(graph).claims[0]
    whole = graph.blocks[0].source_ref()
    quote = text.split(".")[0] + "."
    claim = replace(
        claim, quote=quote, source_refs=(span(whole, quote),), source_quality="verified"
    )
    roles = {
        "entity": span(whole, "회사A"),
        "metric": span(whole, "환경경영체계"),
        "reporting_period": span(whole, "2025"),
    }
    assert (
        accept_binding(
            ClaimContext(claim, roles),
            span(whole, "전사 공장 전체"),
            roles,
            original=graph,
            tenant_id=claim.tenant_id,
            rulepack=scope_pack(ACTIVITY_SCOPE_V2),
            element_id="M2",
        )
        == "accepted"
    )


def test_review_new_scope_policy_rejects_present_without_writing_revision(tmp_path):
    from uuid import uuid4

    from proofops.application.reviews import ReviewRejected

    from tests.acceptance.test_citations import RUN, TENANT
    from tests.acceptance.test_report_level_verification import (
        _management_body,
        _unknown,
        report_workspace,
    )
    from tests.integration.test_ai_delegated_review import _actor

    ws, (*_, scope) = report_workspace(tmp_path, m2=True)
    service, review = ws[1], ws[3]
    before = service.store.history(TENANT, RUN, review["claim_id"])
    body = _management_body(_unknown("M3"))
    body["elements"][1] = dict(
        element_id="M2",
        state="present",
        evidence_refs=[asdict(scope)],
        normalized_value=None,
        credited_from=scope.source_id,
        reason_code=REPORT_SCOPE_V1,
    )
    with pytest.raises(ReviewRejected, match="REPORT_WIDE_SCOPE_NOT_ACTIVITY_SCOPE"):
        service.resolve_review(_actor(), review["review_id"], body, '"1"', str(uuid4()))
    assert service.store.history(TENANT, RUN, review["claim_id"]) == before


def test_policy_change_requires_retag_not_silent_rescore():
    from proofops.application.rescores import RetagRequired, create_rescore

    from tests.acceptance.test_rules import inputs

    old, new = scope_pack(None), scope_pack(ACTIVITY_SCOPE_V2)
    confirmed, context = inputs("management")
    result = create_rescore(new, confirmed, previous_pack=old, context=context)
    assert isinstance(result, RetagRequired)
    assert "ELEMENT_MEANING_CHANGED:M2" in result.reasons


def test_report_heading_ancestor_cannot_be_bypassed_with_generic_scope_subspan():
    from proofops.application.evidence.report_level import scope_rejection_reason
    from proofops.application.ingest.graph_fusion import CanonicalEdge

    from tests.acceptance.test_claims import graph_of

    graph = graph_of("보고 범위 및 경계", "국내 전 사업장", "전사 환경경영체계를 운영합니다.")
    graph = replace(graph, blocks=tuple(replace(b, quality="verified") for b in graph.blocks))
    heading, scope, activity = sorted(graph.blocks, key=lambda b: b.page_num)
    graph = replace(
        graph, edges=(CanonicalEdge(scope.source_id, heading.source_id, "section_parent"),)
    )
    new = scope_pack(ACTIVITY_SCOPE_V2)
    assert scope_rejection_reason("M2", (scope.source_ref(),), rulepack=new, original=graph)
    assert (
        scope_rejection_reason("M2", (activity.source_ref(),), rulepack=new, original=graph) is None
    )
    with pytest.raises(ValueError, match="M2_SCOPE_POLICY_UNSUPPORTED"):
        report_level_policies(scope_pack("unsupported"))


def test_search_display_keeps_unknown_reason_and_api_schema(tmp_path):
    import copy
    import json
    from hashlib import sha256
    from io import BytesIO
    from pathlib import Path

    import jsonschema
    from proofops.adapters.local.job_store import LocalSQLiteJobStore
    from proofops.adapters.local.missing_evidence import missing_evidence
    from pypdf import PdfWriter

    graph, claim, refs = corpus()
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    content = BytesIO()
    writer.write(content)
    original = content.getvalue()
    digest = sha256(original).hexdigest()
    graph = replace(
        graph,
        source_sha256=digest,
        candidates=tuple(replace(batch, source_sha256=digest) for batch in graph.candidates),
    )
    claim = replace(claim, source_sha256=digest)
    snapshot = dict(document={"page_count": 1}, selected_pages=[1], input_hash="c" * 64)
    claims = SimpleNamespace(
        store=SimpleNamespace(
            jobs=LocalSQLiteJobStore(tmp_path / "state.sqlite"),
            snapshot=lambda tenant, run: snapshot,
        ),
        uploads=SimpleNamespace(read_original=lambda tenant, doc: original),
    )
    inputs = SimpleNamespace(
        validate=lambda: None,
        original=graph,
        context=ClaimContext(claim, tags(refs[0])),
        relation_tags={},
        rulepack=scope_pack(ACTIVITY_SCOPE_V2),
    )
    elements = [
        dict(
            element_id="M2",
            state="present",
            evidence_refs=[asdict(refs[1])],
            normalized_value=None,
            reason_code=REPORT_SCOPE_V1,
            credited_from=refs[1].source_id,
        )
    ]
    before = copy.deepcopy(elements)
    result = missing_evidence(
        claims,
        claim.tenant_id,
        claim.claim_id,
        claim,
        track="management",
        elements=elements,
        inputs=inputs,
    )
    m2 = next(e for e in result if e["element_id"] == "M2")
    assert m2["engine_state"] == "unknown"
    assert m2["reason"] == m2["search"]["reason_code"] == "REPORT_WIDE_SCOPE_NOT_ACTIVITY_SCOPE"
    assert m2["evidence_status"] == "undetermined"
    schema = json.loads(Path("contracts/jsonschema/api_models.schema.json").read_text())
    jsonschema.validate(m2, {"$ref": "#/$defs/ElementEvidenceSearch", "$defs": schema["$defs"]})
    assert elements == before
    assert (
        missing_evidence(
            claims,
            claim.tenant_id,
            claim.claim_id,
            claim,
            track="management",
            elements=elements,
            inputs=inputs,
        )
        == result
    )


def test_model_scope_vote_stays_unknown_with_original_refs_and_reason(tmp_path):
    import json

    from proofops.application.evidence.retrieval import freeze_track_packet
    from proofops.application.tagging.tracks import TrackCandidate

    from tests.acceptance.test_tagging import execute, setup

    inputs = setup(tmp_path)
    claim = inputs["context"].claim
    track = TrackCandidate(claim, "management", None)
    # Rebuild the track packet from its retained retrieval input, as production does.
    from proofops.application.evidence.retrieval import retrieve_evidence

    from tests.acceptance.test_citations import RUN
    from tests.acceptance.test_retrieval import SyntheticSearch

    packet = retrieve_evidence(
        claim,
        inputs["original"],
        SyntheticSearch(inputs["original"]),
        tenant_id=claim.tenant_id,
        run_id=RUN,
        index_generation="synthetic",
        rulepack=inputs["rulepack"],
        document_context={},
        token_counter=lambda text: len(text) // 4,
    )
    inputs.update(
        track=track, packet=freeze_track_packet(packet, track=track, rulepack=inputs["rulepack"])
    )
    responder = inputs["invoke"]

    def invoke(request):
        response = responder(request)
        payload = json.loads(response.raw_response_json)
        payload["track"] = "management"
        payload["elements"] = [
            dict(
                element_id=f"M{i}",
                state="unknown",
                evidence_refs=[],
                normalized_value=None,
                credited_from=None,
                reason_code="synthetic",
            )
            for i in range(1, 7)
        ]
        payload["elements"][1].update(
            state="present", evidence_refs=[asdict(responder.source)], reason_code=REPORT_SCOPE_V1
        )
        return replace(response, raw_response_json=json.dumps(payload))

    inputs["invoke"] = invoke
    runs = execute(inputs)
    for run in runs:
        m2 = next(e for e in run.guarded.elements if e.element_id == "M2")
        assert m2.state == "unknown"
        assert m2.reason_code == "REPORT_WIDE_SCOPE_NOT_ACTIVITY_SCOPE"
        assert m2.evidence_refs == (responder.source,)
        assert json.loads(run.raw_response_json)["elements"][1]["state"] == "present"
