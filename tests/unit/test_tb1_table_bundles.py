from dataclasses import asdict, replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from proofops.domain.values import LlmElement, SourceRef

from tests.integration.test_qt1_pipeline import graph


def table_case(company="kakao", needle="0.027"):
    # Structural unit fixture only: source attestation has its own native-PDF tests.
    g = graph(company)
    g = replace(g, blocks=tuple(replace(b, quality="verified") for b in g.blocks))
    table = next(b for b in g.blocks if b.kind == "table" and needle in b.raw_text)
    from proofops.application.ingest.qt1_tables import candidates_for

    row = next(r for r in candidates_for(table, g) if needle in r["quote"])
    ref = table.source_ref(normalized_char_start=row["start"], normalized_char_end=row["end"])
    claim = SimpleNamespace(tenant_id=g.tenant_id, source_quality="verified", source_refs=(ref,))
    return g, claim


def selection(item, element_id="P1"):
    from proofops.application.tagging.tb1_table_bundles import bundle_refs

    refs = tuple(SourceRef(**r) for r in bundle_refs(item))
    return LlmElement(element_id, "present", refs, item["value"]["quote"], None, None)


def test_shared_year_has_a_verified_source_and_target_actual_stay_separate():
    from proofops.application.tagging.tb1_table_bundles import bundles_for, prepare_element

    g, claim = table_case()
    items = bundles_for(claim, g, tenant_id=g.tenant_id)
    actual = next(x for x in items if x["value"]["quote"] == "0.024")
    target = next(x for x in items if x["value"]["quote"] == "0.027")
    assert actual["period"]["quote"] == "2025년"
    assert actual["period_role"] == "observation" and target["period_role"] == "target"
    assert prepare_element(selection(actual), items)[1]
    assert not prepare_element(selection(target), items)[1]
    assert not prepare_element(selection(target, "P2"), items)[1]
    assert prepare_element(selection(target, "G2"), items)[1]


def test_missing_or_unverified_header_never_becomes_a_bundle():
    from proofops.application.tagging.tb1_table_bundles import bundles_for

    g, claim = table_case()
    g = replace(g, blocks=tuple(replace(b, quality="unverified") for b in g.blocks))
    from proofops.application.evidence.span_citations import span_verified_graph

    g = span_verified_graph(g, claim.source_refs, "0" * 64)
    assert bundles_for(claim, g, tenant_id=g.tenant_id) == []
    assert bundles_for(claim, g, tenant_id=str(uuid4())) == []


def test_packet_tamper_and_wrong_row_column_or_partial_selection_are_rejected():
    from proofops.application.tagging.tb1_table_bundles import (
        augment_packet,
        bundles_for,
        prepare_element,
        validate_packet,
    )

    g, claim = table_case()
    items = bundles_for(claim, g, tenant_id=g.tenant_id)
    actual = next(x for x in items if x["value"]["quote"] == "0.024")
    target = next(x for x in items if x["value"]["quote"] == "0.027")
    vote = selection(actual)
    assert not prepare_element(replace(vote, state="unknown"), items)[1]
    assert not prepare_element(replace(vote, state="conflict"), items)[1]
    assert not prepare_element(replace(vote, evidence_refs=vote.evidence_refs[:2]), items)[1]
    bad = replace(vote, evidence_refs=(*vote.evidence_refs, SourceRef(**target["value"])))
    assert not prepare_element(bad, items)[1]
    data = dict(allowed_elements=["P1", "P2"], evidence_candidates=[])
    augment_packet(data, claim, g, tenant_id=g.tenant_id)
    assert validate_packet(data, claim, g, tenant_id=g.tenant_id)
    data["tb1_table_bundles"][0]["period"] = asdict(claim.source_refs[0])
    with pytest.raises(ValueError, match="TB1"):
        validate_packet(data, claim, g, tenant_id=g.tenant_id)


def test_marked_years_and_comparison_value_have_distinct_roles():
    from proofops.application.tagging.tb1_table_bundles import YEAR, bundles_for, prepare_element

    assert YEAR.fullmatch("2024 1)")[1] == "2024"
    assert YEAR.fullmatch("2023년 2)")[1] == "2023"
    assert YEAR.fullmatch("2024 2025") is None
    g, claim = table_case("lge", "548")
    items = bundles_for(claim, g, tenant_id=g.tenant_id)
    assert {i["year"] for i in items} == {"2022", "2023", "2024"}
    baseline = next(i for i in items if i["year"] == "2023")
    assert prepare_element(selection(baseline, "P2"), items)[1]
    assert not prepare_element(selection(baseline, "P1"), items)[1]
    current = next(i for i in items if i["year"] == "2024")
    assert not prepare_element(selection(current, "P2"), items)[1]
    g, claim = table_case()
    items = bundles_for(claim, g, tenant_id=g.tenant_id)
    target = next(i for i in items if i["period_role"] == "target")
    assert target["notes"]
    without_note = replace(
        selection(target, "G2"),
        evidence_refs=tuple(
            r
            for r in selection(target, "G2").evidence_refs
            if r.source_id not in {n["source_id"] for n in target["notes"]}
        ),
    )
    assert not prepare_element(without_note, items)[1]


def test_native_header_attestation_preserves_old_source_and_refuses_tampering():
    from proofops.adapters.local.tb1_claim_source import attest_headers
    from proofops.adapters.local.upstage_ocr_profile_v7 import cell_proof
    from proofops.domain.provenance import canonical_hash

    from tests.unit.test_pb1_source import fixture

    g, source, ref = fixture()
    before = canonical_hash(asdict(g))
    old = cell_proof(g, source.content, [ref], tenant_id=g.tenant_id)
    proofs = attest_headers(g, source.content, [ref], tenant_id=g.tenant_id)
    assert len(proofs) == 1 and proofs[0]["status"] == "verified"
    assert proofs[0]["ref"]["quote"] == "Metric\tUnit\t2023\t2024"
    assert canonical_hash(asdict(g)) == before
    assert cell_proof(g, source.content, [ref], tenant_id=g.tenant_id) == old
    assert all(
        p["status"] != "verified"
        for p in attest_headers(g, source.content, [ref], tenant_id=str(uuid4()))
    )
    assert all(
        p["status"] != "verified"
        for p in attest_headers(g, source.content + b"\n", [ref], tenant_id=g.tenant_id)
    )


def test_other_metric_row_and_missing_year_do_not_supply_a_bundle():
    from proofops.application.tagging.tb1_table_bundles import bundles_for, prepare_element

    g, claim = table_case()
    _, other = table_case(needle="13.4")
    own = bundles_for(claim, g, tenant_id=g.tenant_id)
    foreign = bundles_for(other, g, tenant_id=g.tenant_id)
    assert not prepare_element(selection(foreign[-1]), own)[1]
    g, claim = table_case("lge", "0.71kg")
    assert bundles_for(claim, g, tenant_id=g.tenant_id) == []


def test_new_profile_is_opt_in_and_old_hashes_are_identical():
    from proofops.application.analysis_profile import (
        FINALS_I29B_POLICY,
        TB1_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert (
        policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I29B_POLICY)) == FINALS_I29B_POLICY
    )
    assert canonical_hash(FINALS_I29B_POLICY) == (
        "9fd37ccb4d397e2b3b4c0a468502cca4aed18dbb5d9a0853a72e0d7cae33153d"
    )
    assert policy_for(V2_PROFILE, pinned_hash=canonical_hash(TB1_POLICY)) == TB1_POLICY
    assert publication_policy_for(V2_PROFILE, pinned_hash=canonical_hash(TB1_POLICY)) == TB1_POLICY


def test_goal_year_uses_period_and_baseline_requires_earlier_same_row_unit():
    from proofops.application.tagging.tb1_table_bundles import bundles_for, prepare_element

    g, claim = table_case("lge", "548")
    items = bundles_for(claim, g, tenant_id=g.tenant_id)
    # Role-stage fixture: source parsing and target/actual role detection are
    # exercised separately above with the literal Kakao target column.
    target = next(i for i in items if i["year"] == "2024") | dict(period_role="target")
    earlier = next(i for i in items if i["year"] == "2023")
    pair = [earlier, target]
    year = replace(selection(target, "G1"), normalized_value=target["period"]["quote"])
    assert prepare_element(year, pair)[1]
    assert not prepare_element(selection(target, "G1"), pair)[1]
    assert prepare_element(selection(earlier, "G3"), pair)[1]
    assert not prepare_element(selection(target, "G3"), pair)[1]
    assert not prepare_element(selection(earlier, "G3"), [earlier])[1]
    assert not prepare_element(selection(earlier, "G3"), [earlier, target | dict(row_number=999)])[
        1
    ]
    assert not prepare_element(
        selection(earlier, "G3"),
        [earlier, target | dict(unit=target["unit"] | dict(quote="different-unit"))],
    )[1]


def test_row_spanning_parent_footnote_is_required_on_child_rows():
    from proofops.application.tagging.tb1_table_bundles import bundles_for, prepare_element

    g, claim = table_case("lge", "2,919")
    items = bundles_for(claim, g, tenant_id=g.tenant_id)
    current = next(i for i in items if i["year"] == "2024")
    assert any(r["quote"] == "에너지2)" for r in current["row_labels"])
    assert [r["quote"] for r in current["notes"]] == [
        "2) 구매 에너지 → 에너지(자가발전 포함) 데이터로 정정 "
    ]
    vote = selection(current)
    assert prepare_element(vote, items)[1]
    note_ids = {r["source_id"] for r in current["notes"]}
    assert not prepare_element(
        replace(
            vote, evidence_refs=tuple(r for r in vote.evidence_refs if r.source_id not in note_ids)
        ),
        items,
    )[1]


def test_complete_comparison_pair_is_allowed_but_partial_later_bundle_is_not():
    from proofops.application.tagging.tb1_table_bundles import bundles_for, prepare_element

    g, claim = table_case("lge", "548")
    items = bundles_for(claim, g, tenant_id=g.tenant_id)
    baseline = selection(next(i for i in items if i["year"] == "2023"), "P2")
    current = selection(next(i for i in items if i["year"] == "2024"))
    pair = replace(baseline, evidence_refs=baseline.evidence_refs + current.evidence_refs)
    assert prepare_element(pair, items)[1]
    partial = replace(baseline, evidence_refs=baseline.evidence_refs + current.evidence_refs[:1])
    assert not prepare_element(partial, items)[1]


def test_method_element_rejects_unit_year_and_restatement_only():
    from proofops.application.tagging.tb1_table_bundles import bundles_for, prepare_element

    for company, needle in (("kakao", "0.027"), ("lge", "2,919")):
        g, claim = table_case(company, needle)
        item = bundles_for(claim, g, tenant_id=g.tenant_id)[-1]
        vote = replace(selection(item, "P3"), normalized_value=None)
        assert not prepare_element(vote, [item])[1]
