import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from proofops.domain.rulepacks import RulePackSnapshot

from evaluation import report_decisions as rd


def setup_case(text="2024년 NAVER 전력 100 kWh", track="performance"):
    pack = RulePackSnapshot(**json.loads((rd.ROOT / "api/rulepack.json").read_text()))
    pack = replace(
        pack, status="active", approved_by="synthetic-test", approved_at="2026-10-10T00:00:00Z"
    )
    source = SimpleNamespace(
        sha256="a" * 64, tenant_id=pack.tenant_id, document_version_id=str(uuid4())
    )
    block = dict(
        index=0,
        page=1,
        raw_text=text,
        text=text,
        key=f"{uuid4()}/paragraph",
        bbox=[0, 0, 100, 30],
        table=None,
        row=None,
        column=None,
    )
    claim = dict(
        quote=text,
        page=1,
        block=0,
        track=track,
        source_verified=True,
        tagging_complete=True,
        replicate_hashes=[rd.digest(i) for i in range(3)],
        model="synthetic",
        elements=[],
        normalized={},
    )
    return pack, source, [block], claim


def element(name, eid, quote, blocks, index=0):
    return dict(
        name=name,
        element_id=eid,
        quote=quote,
        candidate_state="present",
        source_verified=True,
        citation=rd.literal_citation(dict(block=index, quote=quote), blocks),
        crosscheck=dict(native_verified=True, status="consensus", original_audit="consensus"),
    )


def test_verified_local_facts_reach_real_engine_and_produce_range():
    pack, source, blocks, claim = setup_case()
    claim["elements"] = [
        element("quantitative_or_qualified_ordinal", "P1", "100", blocks),
        element("unit_or_qualified_ordinal", "P1", "kWh", blocks),
    ]
    rd.decide(claim, source, blocks, pack)
    assert [e["state"] for e in claim["elements"]] == ["present", "present"]
    assert claim["decision"]["evidence_grade"] is None
    assert claim["decision"]["grade_range"]["floor"] == "E1"
    assert claim["decision"]["grade_range"]["ceiling"] == "E3"
    assert not claim["decision_input"]["context"]["local_synthetic"]


def test_approved_pack_does_not_approve_claims_or_reuse_historical_answers():
    _, source, blocks, claim = setup_case()
    rd.decide(claim, source, blocks, None)
    assert claim["decision"]["decision_status"] == "blocked_rule_gap"
    assert claim["decision"]["evidence_grade"] is None


def test_incomplete_votes_do_not_promote_facts():
    pack, source, blocks, claim = setup_case()
    claim["elements"] = [element("quantitative_or_qualified_ordinal", "P1", "100", blocks)]
    claim.update(tagging_complete=False, replicate_hashes=[])
    rd.decide(claim, source, blocks, pack)
    assert claim["elements"][0]["state"] == "unknown"
    assert claim["decision"]["grade_range"] is None


def test_table_conflict_is_not_overridden_by_numeric_match():
    _, _, blocks, claim = setup_case()
    e = element("quantitative_or_qualified_ordinal", "P1", "100", blocks)
    e["crosscheck"]["original_audit"] = "parse_conflict"
    assert rd.bind(claim, e, blocks, ["local_claim"])[0] == "conflict"
    e["crosscheck"]["original_audit"] = "consensus"
    claim["crosscheck"] = dict(original_audit="parse_conflict")
    assert rd.bind(claim, e, blocks, ["local_claim"])[0] == "conflict"


def test_other_page_method_requires_entity_metric_and_period():
    _, _, blocks, claim = setup_case()
    other = dict(
        blocks[0],
        index=1,
        page=9,
        text="2024년 NAVER 전력 산정방법 계량기",
        raw_text="2024년 NAVER 전력 산정방법 계량기",
    )
    blocks.append(other)
    e = element("method", "P3", other["text"], blocks, 1)
    assert rd.bind(claim, e, blocks, ["global_bound"])[0] == "unknown"
    claim["normalized"] = {
        k: dict(value=v) for k, v in dict(entity="NAVER", metric="전력", year="2024").items()
    }
    assert rd.bind(claim, e, blocks, ["global_bound"])[0] == "present"
    e["name"] = "target_year"
    assert rd.bind(claim, e, blocks, ["local_claim", "same_table"])[0] == "unknown"


def test_other_year_and_exclusions_cannot_be_borrowed():
    _, _, blocks, claim = setup_case()
    claim["normalized"] = {
        k: dict(value=v) for k, v in dict(entity="NAVER", metric="전력", year="2024").items()
    }
    for text in (
        "2023 NAVER 전력 산정방법",
        "2024 NAVER 전력 제외 산정방법",
        "2024 및 2023 NAVER 전력 방법",
    ):
        other = dict(blocks[0], index=1, page=9, text=text, raw_text=text)
        bs = [blocks[0], other]
        assert (
            rd.bind(claim, element("method", "P3", text, bs, 1), bs, ["global_bound"])[0]
            != "present"
        )


def test_assurance_provider_does_not_prove_coverage():
    _, _, blocks, claim = setup_case("2024 NAVER 검증기관 ABC")
    e = element("assurance_covered", "P4", "검증기관 ABC", blocks)
    assert (
        rd.bind(claim, e, blocks, ["local_claim", "global_bound"])[1]
        == "assurance_scope_review_required"
    )


def test_packet_retrieves_methods_from_other_pages_and_records_limits():
    _, _, blocks, claim = setup_case()
    blocks.append(dict(blocks[0], index=1, page=9, text="2024 NAVER 전력 산정방법"))
    packet, coverage = rd.evidence_packet([claim], blocks)
    assert {b["page"] for b in packet} == {1, 9}
    assert coverage["absence_certified"] is False
    _, coverage = rd.evidence_packet([claim], blocks, max_chars=len(blocks[0]["text"]))
    assert coverage["truncated"]


def test_chunks_cover_tail_without_duplication():
    _, _, blocks, _ = setup_case()
    blocks = [dict(blocks[0], index=i) for i in range(350)]
    chunks = rd.extraction_chunks(blocks, max_blocks=100)
    assert [b["index"] for chunk in chunks for b in chunk] == list(range(350))


def test_wrong_table_column_does_not_supply_target_year():
    _, _, blocks, claim = setup_case()
    blocks[0].update(table="t", row=3, column=2)
    other = dict(blocks[0], index=1, row=0, column=1, text="2030", raw_text="2030")
    blocks.append(other)
    e = element("target_year", "G1", "2030", blocks, 1)
    assert rd.bind(claim, e, blocks, ["same_table"])[0] == "unknown"
    other["column"] = 2
    assert rd.bind(claim, e, blocks, ["same_table"])[0] == "present"
    other["column_span"] = 2
    assert rd.bind(claim, e, blocks, ["same_table"])[0] == "unknown"


def test_special_route_does_not_receive_generic_grade_range():
    pack, source, blocks, claim = setup_case("최고 효율 100 kWh")
    claim["elements"] = [
        element("quantitative_or_qualified_ordinal", "P1", "100", blocks),
        element("unit_or_qualified_ordinal", "P1", "kWh", blocks),
    ]
    rd.decide(claim, source, blocks, pack)
    assert claim["decision"]["decision_status"] == "blocked_rule_gap"
    assert claim["decision"]["grade_range"] is None


def test_missing_registry_is_not_auto_approved(tmp_path, monkeypatch):
    monkeypatch.setattr(rd, "ROOT", tmp_path)
    assert rd.load_pack(str(uuid4())) is None


def test_citation_offsets_must_exist_in_raw_source():
    _, _, blocks, _ = setup_case()
    assert rd.literal_citation(dict(block=0, quote="invented"), blocks) is None
    assert rd.literal_citation(dict(block=True, quote="100"), blocks) is None


def test_reduction_activity_is_not_calculation_methodology():
    _, _, blocks, claim = setup_case("절수형 기구로 물 사용량 38% 절감")
    e = element("method", "P3", claim["quote"], blocks)
    assert rd.bind(claim, e, blocks, ["local_claim"])[1] == "calculation_method_review_required"


def test_bare_low_rating_requires_anchored_scale_review():
    _, _, blocks, claim = setup_case("수자원 민감도는 낮은 수준")
    e = element("quantitative_or_qualified_ordinal", "P1", "낮은 수준", blocks)
    assert rd.bind(claim, e, blocks, ["local_claim"])[1] == "ordinal_scale_review_required"
