from dataclasses import replace

from proofops.domain.values import LlmElement

from tests.integration.test_qt1_pipeline import graph


def test_saved_kakao_value_has_note_year_and_literal_unit():
    from proofops.application.tagging.qt1_tuples import tuples_for

    g = graph("kakao")
    b = next(b for b in g.blocks if b.source_id == "6f7a8883-6fcc-5df8-ace8-38cecd4c6732")
    item = next(t for t in tuples_for(b, g) if t["value"]["quote"] == "253 tCO₂eq")
    assert item["year"] == "2025"
    assert item["unit"]["quote"] == "tCO₂eq"
    assert "2025년 운영 실적 기준" in item["period"]["quote"]
    assert item["period_role"] == "observation"
    assert not item["admitted"]  # stored parser candidates are not source approval


def test_target_actual_and_missing_year_are_not_interchangeable():
    from proofops.application.tagging.qt1_tuples import tuples_for

    g = graph("kakao")
    b = next(b for b in g.blocks if b.source_id == "329e3926-72d9-5f66-8274-1f75f2251b0a")
    items = tuples_for(b, g)
    assert {t["period_role"] for t in items} == {"target", "observation"}
    assert all(t["year"] == "2025" for t in items)
    g = graph("lge")
    b = next(b for b in g.blocks if b.source_id == "c41115f7-e1f9-59f5-9d22-58ff14bd737b")
    item = next(t for t in tuples_for(b, g) if t["value"]["quote"] == "0.71kg")
    assert item["year"] is None and not item["admitted"]
    assert item["unit"]["quote"] == "kg"


def test_saved_kia_marker_header_year_and_unit_have_distinct_roles():
    import json
    from pathlib import Path

    from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
    from proofops.application.tagging.qt1_tuples import tuples_for

    data = json.loads((Path(__file__).parents[1] / "fixtures/qt1/kia-106-parse.json").read_text())
    g = fuse_candidates(
        candidates_from_snapshot(data["snapshot"]),
        tenant_id=data["snapshot"][0]["tenant_id"],
        fusion_version=data["fusion_version"],
        mixed_parser=True,
    )
    b = next(b for b in g.blocks if b.kind == "table" and "1,178.5" in b.raw_text)
    items = tuples_for(b, g)
    item = next(t for t in items if t["value"]["quote"] == "1,178.5")
    assert item["unit"]["quote"] == "천tCO2eq" and item["year"] == "2024"
    assert item["period"]["quote"] == "2024"
    assert item["notes_resolved"] and len(item["notes"]) == 1
    assert item["notes"][0]["quote"].startswith("1.2024년부터")
    assert "Scope 1 & 2로 포함하여 산정" in item["notes"][0]["quote"]
    assert "1" not in [t["value"]["quote"] for t in items if t["row"] == item["row"]]
    assert not item["admitted"]  # saved parse alone is still not verification


def test_selected_tuple_requires_value_unit_year_and_same_row():
    from proofops.application.tagging.qt1_tuples import prepare_element, tuple_evidence

    from tests.unit.test_pb2_table_evidence import observation_case

    g, source, claim = observation_case()
    items = tuple_evidence(claim, g, tenant_id=source.tenant_id)
    assert items
    item = next(t for t in items if t["year"] == "2024")
    from proofops.domain.values import SourceRef

    refs = tuple(SourceRef(**item[k]) for k in ("value", "unit", "period"))
    element = LlmElement("P1", "present", refs, refs[0].quote, None, None)
    assert prepare_element(element, items)[1]
    assert not prepare_element(replace(element, evidence_refs=refs[:2]), items)[1]
    assert not prepare_element(replace(element, normalized_value="2023"), items)[1]
    assert not prepare_element(replace(element, state="conflict"), items)[1]


def test_default_and_historical_hashes_remain_registered():
    from proofops.application.analysis_profile import (
        FINALS_I24_POLICY,
        QT1_V25_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert (
        policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I24_POLICY)) == FINALS_I24_POLICY
    )
    assert (
        canonical_hash(FINALS_I24_POLICY)
        == "775e8d04aaed82bd86c002402f3b80fdabd7206e69a1e768403cbc0644638501"
    )
    for p in (FINALS_I24_POLICY, QT1_V25_POLICY):
        assert policy_for(V2_PROFILE, pinned_hash=canonical_hash(p)) == p
        assert publication_policy_for(V2_PROFILE, pinned_hash=canonical_hash(p)) == p


def test_goal_table_does_not_expose_performance_tuple_ids():
    from proofops.application.tagging.qt1_tuples import augment_packet, validate_packet

    from tests.unit.test_pb2_table_evidence import observation_case

    g, source, claim = observation_case()
    data = dict(allowed_elements=["G1", "G2", "G3", "G4"], evidence_candidates=[])
    augment_packet(data, claim, g, tenant_id=source.tenant_id)
    assert data["qt1_table_tuples"] == [] and data["evidence_candidates"] == []
    assert validate_packet(data, claim, g, tenant_id=source.tenant_id) == []


def test_v25_runtime_create_resume_and_tamper_guard(tmp_path, monkeypatch):
    from proofops.application.analysis_profile import QT1_V25_POLICY

    from tests.integration import test_qt1_pipeline

    monkeypatch.setattr(test_qt1_pipeline, "QT1_POLICY", QT1_V25_POLICY)
    test_qt1_pipeline.test_new_profile_create_resume_and_tamper_guard(tmp_path, monkeypatch)
    import json

    for name in ("settings.json", "pilot.json"):
        assert json.loads((tmp_path / "state" / name).read_text())["extraction_qt1_goal_split"]


def test_wire_projects_only_citable_tuple_ids(tmp_path, monkeypatch):
    import json

    from proofops.application.tagging.qt1_baseline import POLICY

    from tests.integration.test_r19_baseline_link import fixture, receipt
    from tests.integration.test_upstage_tagging_v4 import configured

    graph, context, inventory = fixture()
    link = receipt(graph, context, inventory)["links"][0]
    adapter, _, calls, request = configured(tmp_path, monkeypatch)
    user = json.loads(request["user_json"])
    data = user["untrusted_document_data"]
    data.update(
        allowed_elements=["G2", "G3"],
        evidence_candidates=[
            dict(
                source_refs=[link[k] for k in ("value", "unit", "period")],
                allowed_elements=["G2", "G3"],
            )
        ],
        qt1_baseline_policy=POLICY,
        qt1_baseline_links=[
            {k: link[k] for k in ("value", "unit", "period", "meaning", "elements")}
        ],
    )
    request["user_json"] = json.dumps(user)
    system, wire, *_ = adapter._wire_request(request)
    compact = json.loads(wire)["untrusted_document_data"]["qt1_baseline_links"][0]
    assert compact["value_id"] == "e0" and compact["period_id"] == "e2"
    assert "DEC-93 AP-03" in system
    assert "replica_ids" not in wire and "inventory_sha256" not in wire
    assert calls == []


def test_compound_maintenance_targets_split_only_selected_literal_source(tmp_path):
    from dataclasses import asdict

    from proofops_agent.upstage_extraction import UpstageClaimExtractor

    from tests.integration.test_upstage_extraction import packet
    from tests.unit.test_fxg_extraction_split import Selector

    text = (
        "SK하이닉스는 2050년까지 넷 제로 및 RE100 달성을 장기 목표로 설정하고 이 "
        "를 이행하기 위해 2030년까지 Scope 1&2 온실가스 배출량 2020년 수준 유지 "
        "및 재생에너지 사용률 33% 달성을 중간 목표로 수립했습니다."
    )
    counts = []
    for enabled in (False, True):
        probe = Selector()
        extractor = UpstageClaimExtractor(
            probe,
            tmp_path / str(enabled),
            extraction_source_ids=True,
            extraction_qt1_goal_split=enabled,
        )
        data = packet(text)
        data["extraction_profile"] = asdict(extractor.profile)
        output = extractor.extract(data)
        spans = output["spans"]
        counts.append(len(spans))
        for span in spans:
            assert span["quote"] == text[span["char_start"] : span["char_end"]]
        calls = len(probe.calls)
        assert extractor.extract(data) == output and len(probe.calls) == calls
    assert counts == [1, 4]
    assert "2050" not in spans[2]["quote"] and "2020년 수준 유지" in spans[2]["quote"]
    assert "33%" in spans[3]["quote"] and "2030" not in spans[3]["quote"]


def test_goal_refinement_does_not_split_reduction_or_fabricate_maintenance_values():
    from proofops.application.ingest.qt1_goal_split import refine_selected

    for text in (
        "2030년까지 온실가스 배출량을 2020년 대비 30% 감축한다.",
        "2030년까지 Scope 1&2 온실가스 배출량을 2020년 수준으로 유지한다.",
        "2024년 재활용률은 본문 60%이나 표에는 62%이다.",
        "2024년 감축률은 본문 12%이나 표에는 7%이다.",
    ):
        span = dict(kind="claim", char_start=0, char_end=len(text), quote=text)
        assert refine_selected([span], text, kind="paragraph") == ([span], [])


def test_selected_tuple_survives_older_table_preparation_in_tagging(tmp_path):
    from dataclasses import asdict
    from uuid import uuid4

    from proofops.application.analysis_profile import QT1_V25_POLICY
    from proofops.application.budget import BudgetLimits, RoleLimit
    from proofops.application.claims import Claim
    from proofops.application.evidence.binding import ClaimContext
    from proofops.application.evidence.retrieval import (
        freeze_packet,
        freeze_track_packet,
        retrieve_evidence,
    )
    from proofops.application.tagging.pb2_table_evidence import augment_packet as pb2_augment
    from proofops.application.tagging.qt1_tuples import augment_packet, tuple_evidence
    from proofops.application.tagging.tracks import TrackCandidate
    from proofops.domain.values import SourceRef

    from tests.acceptance.test_citations import RUN
    from tests.acceptance.test_retrieval import SyntheticSearch
    from tests.acceptance.test_tagging import SyntheticResponder, execute, setup
    from tests.unit.test_pb2_table_evidence import observation_case

    g, source, simple = observation_case()
    inputs = setup(tmp_path)
    claim = Claim(
        str(uuid4()),
        source.tenant_id,
        source.document_version_id,
        g.parse_manifest_id,
        source.sha256,
        simple.source_refs[0].quote,
        simple.source_refs,
        "verified",
        ("environment",),
        replace(inputs["context"].claim.receipt, source_id=simple.source_refs[0].source_id),
    )
    pack = replace(inputs["rulepack"], tenant_id=source.tenant_id)
    track = TrackCandidate(claim, "performance", None)
    packet = retrieve_evidence(
        claim,
        g,
        SyntheticSearch(g),
        tenant_id=source.tenant_id,
        run_id=RUN,
        index_generation="synthetic-v1",
        rulepack=pack,
        document_context={},
        token_counter=lambda _: 1,
    )
    data = freeze_track_packet(packet, track=track, rulepack=pack).to_dict()
    data.pop("packet_sha256")
    data = pb2_augment(data, claim, g, tenant_id=source.tenant_id)
    data = augment_packet(data, claim, g, tenant_id=source.tenant_id)
    packet = freeze_packet(data)
    item = next(
        t for t in tuple_evidence(claim, g, tenant_id=source.tenant_id) if t["year"] == "2024"
    )
    selected = [item[k] for k in ("value", "unit", "period")]
    inputs["usage_store"].create_budget(
        source.tenant_id,
        RUN,
        claim.document_version_id,
        BudgetLimits(10000, 10000, (RoleLimit("tagger", 3, 10000, 1000, 11000),)),
    )
    inputs.update(
        packet=packet,
        context=ClaimContext(claim, {}),
        track=track,
        original=g,
        rulepack=pack,
        tenant_id=source.tenant_id,
        relation_tags={},
        semantic_policy=QT1_V25_POLICY["semantic_admission"],
        invoke=SyntheticResponder(
            SourceRef(**selected[0]),
            changes={
                i: dict(element=dict(evidence_refs=selected, normalized_value="15"))
                for i in (1, 2, 3)
            },
        ),
    )
    runs = execute(inputs)
    for run in runs:
        p1 = run.guarded.elements[0]
        assert p1.state == "present", run.errors
        assert [asdict(r) for r in p1.evidence_refs] == selected
