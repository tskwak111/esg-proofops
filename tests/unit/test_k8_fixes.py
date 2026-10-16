from dataclasses import replace

import pytest


def test_k8_is_explicit_and_preserves_k7_and_default():
    from proofops.application.analysis_profile import (
        FINALS_I6_POLICY,
        FINALS_K7_POLICY,
        FINALS_K8_POLICY,
        policy_for,
        publication_policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert (
        canonical_hash(FINALS_K7_POLICY)
        == "9762279aac6d10ce95aa029bb99d9157a5d1e3b437e6e7ddf28f5c8b3c1192de"
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I6_POLICY))
        == FINALS_I6_POLICY
    )
    digest = canonical_hash(FINALS_K8_POLICY)
    assert digest != canonical_hash(FINALS_K7_POLICY)
    assert policy_for("finals-unattended-v2", pinned_hash=digest) == FINALS_K8_POLICY
    assert publication_policy_for("finals-unattended-v2", pinned_hash=digest) == FINALS_K8_POLICY


@pytest.mark.parametrize("version", [1, 2, 3])
def test_k8_management_guidance_reaches_wire_without_granting_evidence(
    tmp_path, monkeypatch, version
):
    from proofops.application.tagging.k7_wire import POLICY_K8, POLICY_K8_V2, POLICY_K8_V3

    from tests.integration.test_upstage_tagging_v4 import configured

    adapter, _, _, request = configured(tmp_path, monkeypatch)
    import json

    data = json.loads(request["user_json"])
    data["untrusted_document_data"]["allowed_elements"] = ["M1", "M2", "M3", "M4", "M5", "M6"]
    data["untrusted_document_data"]["tagging_wire_policy"] = {
        1: POLICY_K8,
        2: POLICY_K8_V2,
        3: POLICY_K8_V3,
    }[version]
    request["system_prompt"] = (
        adapter._settings.rendered_system
        + "\nValidated classification; tag only its elements: "
        + '{"track":"management","safe_harbor_category":null}'
    )
    request["user_json"] = json.dumps(data)
    system, wire, _, _, _ = adapter._wire_request(request)
    assert "검토·승인합니다" in system and "검토할 예정" in system
    assert "2023년 2월" in system and "감축량" in system
    assert "그룹" in system and "Scope" in system
    assert "Never cite" in system
    assert "명명된 수단은 표준·설비 외에" not in system
    if version == 3:
        data["untrusted_document_data"]["atomic_quote"] = (
            "건축물 단열 성능 개선 및 에너지 효율 향상"
        )
        request["user_json"] = json.dumps(data)
        system, _, _, _, _ = adapter._wire_request(request)
        assert "명명된 수단은 표준·설비 외에" in system
    if version in (2, 3):
        assert "주체·날짜·완료 행동" in system


@pytest.mark.parametrize(
    "change", ["other_column", "other_page", "too_far", "terminal", "ambiguous"]
)
def test_k8_join_rejects_unsafe_layout(change):
    from proofops.adapters.parsing.k8_source_recovery import _continues

    from tests.integration.test_parser_source_recovery import block, fixture

    source, manifest, run = fixture([])
    a = block(source, manifest, run, "a", "감축을 최대화할 수 있", (30, 40, 250, 55))
    b = block(
        source, manifest, run, "b", "도록 대체가스 개발을 지속할 계획입니다.", (30, 54, 220, 67)
    )
    assert _continues(a, b)
    if change == "other_column":
        b = replace(b, source=replace(b.source, native_bbox=(280, 233, 390, 246)))
    elif change == "other_page":
        b = replace(b, source=replace(b.source, physical_page=2))
    elif change == "too_far":
        b = replace(b, source=replace(b.source, native_bbox=(30, 200, 220, 213)))
    elif change == "terminal":
        a = replace(
            a,
            source=replace(
                a.source, raw_text="감축할 수 있습니다.", char_end=len("감축할 수 있습니다.")
            ),
        )
    else:
        # Ambiguity is resolved by recover_sources, never by choosing one neighbour.
        assert _continues(a, b)
        return
    assert not _continues(a, b)


def sk_case():
    import json
    from hashlib import sha256
    from pathlib import Path
    from uuid import uuid4

    from proofops.application.ingest.graph_fusion import SourceArtifact, candidates_from_snapshot

    folder = Path(__file__).parents[1] / "fixtures/k8"
    content = (folder / "sk19.pdf").read_bytes()
    batches = candidates_from_snapshot(json.loads((folder / "sk19.json").read_text()))
    batch = batches[0]
    source = SourceArtifact(
        batch.tenant_id,
        str(uuid4()),
        batch.document_version_id,
        sha256(content).hexdigest(),
        "1",
        content,
    )
    return source, batches


def test_real_sk_native_continuation_reaches_extraction_with_original_refs():
    from proofops.adapters.parsing.k8_source_recovery import recover_sources
    from proofops.application.claims import ClaimScope, ExtractionProfile, discover_atomic_claims
    from proofops.application.ingest.graph_fusion import fuse_candidates

    source, original = sk_case()
    recovered, receipt = recover_sources(source, original)
    assert receipt["joined"] == 1
    assert recovered[0].blocks[:2] == original[0].blocks
    graph = fuse_candidates(recovered, tenant_id=source.tenant_id)
    joined = next(
        b
        for b in graph.blocks
        if b.raw_text.endswith("지속할 계획입니다.") and "\n도록 " in b.raw_text
    )
    assert joined.quality == "unverified"
    assert (
        len(
            [
                e
                for e in graph.edges
                if e.source_id == joined.source_id and e.relation == "derived_from"
            ]
        )
        == 2
    )

    class Selector:
        profile = ExtractionProfile("a" * 64, "b" * 64, "c" * 64, True)

        def extract(self, packet):
            text = packet["untrusted_document_data"]["text"]
            at = text.index("SK하이닉스는 Scope 1 온실가스 배출량 감축을 최대화")
            return {
                "spans": [
                    {
                        "char_start": at,
                        "char_end": len(text),
                        "quote": text[at:],
                        "kind": "claim",
                        "reason": None,
                        "topic_ids": [],
                    }
                ]
            }

    scope = ClaimScope(
        source.tenant_id,
        source.document_version_id,
        graph.parse_manifest_id,
        "declared_subset",
        (1,),
    )
    discovery = discover_atomic_claims(graph, scope, extractor=Selector())
    (claim,) = discovery.claims
    assert "있\n도록" in claim.quote
    assert "대체가스 개발 및 양산 적용" in claim.quote
    assert len(claim.source_refs) == 3
    originals = {b.source_id: b for b in graph.blocks if b != joined}
    for ref in claim.source_refs[1:]:
        block = originals[ref.source_id]
        assert ref.quote == block.raw_text[ref.char_start : ref.char_end]
        assert ref.bbox == block.bbox
        assert ref.verification_state != "verified"


@pytest.mark.parametrize("change", ["ambiguous", "wrong_text", "foreign_tenant", "source_hash"])
def test_native_join_failures_do_not_manufacture_continuity(change):
    from proofops.adapters.parsing.k8_source_recovery import recover_sources

    source, batches = sk_case()
    batch = batches[0]
    left, right = batch.blocks
    if change == "ambiguous":
        duplicate = replace(right, source=replace(right.source, source_native_id="duplicate"))
        batches = (replace(batch, blocks=(*batch.blocks, duplicate)),)
    elif change == "wrong_text":
        text = right.source.raw_text.replace("대체가스", "가상물질")
        batches = (
            replace(
                batch,
                blocks=(
                    left,
                    replace(right, source=replace(right.source, raw_text=text, char_end=len(text))),
                ),
            ),
        )
    elif change == "foreign_tenant":
        batches = (replace(batch, tenant_id="00000000-0000-4000-8000-000000000099"),)
    else:
        source = replace(source, sha256="f" * 64)
    if change in ("foreign_tenant", "source_hash"):
        with pytest.raises(ValueError, match="MISMATCH"):
            recover_sources(source, batches)
    else:
        recovered, receipt = recover_sources(source, batches)
        assert receipt["joined"] == 0
        assert recovered == batches


def test_m4_complete_citation_cannot_bypass_unknown_boundary():
    from proofops.application.evidence.binding import (
        ClaimContext,
        accept_binding,
        local_relation_tags,
        relation_tags_for,
    )

    from tests.acceptance.test_binding import span
    from tests.acceptance.test_rules import pack
    from tests.unit.test_k5_context import case

    text = "가상기업은 2023년 2월 CCS 사업화 추진반을 구성하여 사업을 추진합니다."
    graph, claim = case([text], (0, text))
    full = claim.source_refs[0]
    context = ClaimContext(
        claim,
        {
            "entity": span(full, "가상기업"),
            "metric": None,
            "reporting_period": None,
            "boundary": None,
        },
    )
    relations = local_relation_tags(context)

    def binding(ref):
        return accept_binding(
            context,
            ref,
            relation_tags_for(ref, relations),
            original=graph,
            tenant_id=graph.tenant_id,
            rulepack=pack(),
            element_id="M4",
            local_value_identity=True,
        )

    assert binding(span(full, "2023년 2월 CCS 사업화 추진반을 구성")) == "undetermined"
    assert binding(full) == "undetermined"
