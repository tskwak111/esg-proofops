"""Local evidence search: bounded BM25 over an explicit page set (TASK owned)."""

from dataclasses import replace
from hashlib import sha256

import pytest
from proofops.application.evidence.retrieval import SearchScope

from tests.acceptance.test_claims import TENANT, graph_of

OTHER = "22222222-2222-4222-8222-222222222222"
GENERATION = "korean-bigram-bm25-v2"


def make_search(graph, pages=None, index_generation=GENERATION, tenant_id=TENANT):
    from proofops.adapters.local.evidence_search import LocalEvidenceSearch

    if pages is None:
        pages = tuple(b.page_num for b in graph.blocks)
    return LocalEvidenceSearch(
        graph, tenant_id=tenant_id, pages=pages, index_generation=index_generation
    )


def test_search_terms_exported_with_korean_bigram_routing():
    from proofops.adapters.local.evidence_search import search_terms

    assert search_terms("온실가스") == ["온실", "실가", "가스"]
    assert search_terms("탄소 4 톤") == ["탄소", "4"]


def test_scope_exact_match_required_foreign_fails_before_search():
    graph = graph_of("온실가스 배출량", "사회 본문")
    search = make_search(graph)
    foreign = SearchScope(TENANT, graph.document_version_id, graph.parse_manifest_id, "wrong")
    with pytest.raises(ValueError):
        search.search(foreign, "온실가스")
    # Foreign scope must fail before search, including vector calls (never not_run).
    with pytest.raises(ValueError):
        search.search(foreign, "온실가스", vector=(1.0,))
    other_tenant = SearchScope(
        OTHER, graph.document_version_id, graph.parse_manifest_id, GENERATION
    )
    with pytest.raises(ValueError):
        search.search(other_tenant, "온실가스", vector=(1.0,))


def test_pages_strict_positive_int_bool_forbidden():
    graph = graph_of("온실가스 배출량", "사회 본문")
    for bad in (True, False, 0, -1, 1.0, "1", None):
        with pytest.raises(ValueError):
            make_search(graph, pages=(bad,))


def test_pages_must_occur_in_graph():
    graph = graph_of("온실가스 배출량", "사회 본문")
    with pytest.raises(ValueError):
        make_search(graph, pages=(999,))
    with pytest.raises(ValueError):
        make_search(graph, pages=(1, 999))


def test_empty_pages_allowed_as_explicit_zero_coverage():
    graph = graph_of("온실가스 배출량", "사회 본문")
    search = make_search(graph, pages=())
    assert search.pages == frozenset()
    result = search.search(search.scope, "온실가스")
    assert result.hits == ()
    assert result.status == "bounded"


def test_zero_match_returns_bounded_empty():
    graph = graph_of("온실가스 배출량", "사회 본문")
    search = make_search(graph)
    result = search.search(search.scope, "zzzqqq-no-such-token")
    assert result.hits == ()
    assert result.status == "bounded"


def test_top20_deterministic_positive_hits():
    texts = [f"배출량 데이터 {i}호 환경 보고" for i in range(25)]
    graph = graph_of(*texts)
    search = make_search(graph)
    first = search.search(search.scope, "배출량")
    second = search.search(search.scope, "배출량")
    assert len(first.hits) == 20
    assert [h.source_id for h in first.hits] == [h.source_id for h in second.hits]
    assert len({h.source_id for h in first.hits}) == 20
    assert first.status == "bounded"


def test_vector_not_none_yields_not_run_never_fake_vectors():
    graph = graph_of("온실가스 배출량", "사회 본문")
    search = make_search(graph)
    for vector in ((1.0,), (0.0, 0.0), ()):
        result = search.search(search.scope, "온실가스", vector=vector)
        assert result.status == "not_run"
        assert result.hits == ()


def test_hits_hash_original_raw_text_and_provenance():
    graph = graph_of("온실가스를 감축하였습니다.", "온실가스 배출량", "직원 수")
    search = make_search(graph)
    assert search.synthetic is True
    assert search.graph is graph
    assert search.pages == frozenset(b.page_num for b in graph.blocks)
    assert search.scope.tenant_id == TENANT
    assert search.scope.document_version_id == graph.document_version_id
    assert search.scope.parse_manifest_id == graph.parse_manifest_id
    assert search.scope.index_generation == GENERATION
    result = search.search(search.scope, "온실가스")
    assert result.hits
    blocks = {b.source_id: b for b in graph.blocks}
    for hit in result.hits:
        assert hit.scope == search.scope
        assert sha256(blocks[hit.source_id].raw_text.encode()).hexdigest() == (hit.raw_text_sha256)


def test_duplicate_block_ids_rejected():
    graph = graph_of("온실가스 배출량", "사회 본문")
    duplicated = replace(graph, blocks=(graph.blocks[0], graph.blocks[0]))
    with pytest.raises(ValueError):
        make_search(duplicated)


def test_graph_identity_validated_before_indexing():
    graph = graph_of("온실가스 배출량", "사회 본문")
    with pytest.raises(ValueError):
        make_search(graph, tenant_id=OTHER)


def test_ranking_values_preserved_for_valid_inputs():
    graph = graph_of(
        "온실가스를 감축하였습니다.",
        "온실가스 사회 본문",
        "온실가스 배출량",
        "직원 수",
        "온실가스 검증 의견서",
    )
    search = make_search(graph)
    blocks = {b.source_id: b for b in graph.blocks}
    hits = search.search(search.scope, "온실가스를 감축하였습니다.").hits
    # Explicit full-page coverage: page 2 ("온실가스 사회 본문") also routes,
    # unlike the section-map subset in evaluation/section_pipeline.py. Only the
    # unrelated page 4 ("직원 수") stays out, with identical BM25 values.
    assert {blocks[h.source_id].page_num for h in hits} == {1, 2, 3, 5}


def test_far_page_numeric_hit_does_not_gain_direct_evidence_scope():
    from proofops.application.evidence.retrieval import retrieve_evidence

    from tests.acceptance.test_citations import RUN
    from tests.acceptance.test_retrieval import corpus
    from tests.acceptance.test_rules import pack

    graph, claim = corpus()
    search = make_search(graph)
    packet = retrieve_evidence(
        claim,
        graph,
        search,
        tenant_id=TENANT,
        run_id=RUN,
        index_generation=search.scope.index_generation,
        rulepack=pack(),
        document_context={},
        token_counter=len,
    ).to_dict()
    numeric_id = next(b.source_id for b in graph.blocks if "2030" in b.raw_text)
    candidate = next(c for c in packet["evidence_candidates"] if c["source_id"] == numeric_id)
    assert candidate["source_scope"] == "global_bound"
    assert "G1" not in candidate["allowed_elements"]
    assert "P1" not in candidate["allowed_elements"]
    assert all(b["state"] == "undetermined" for b in packet["candidate_bindings"])
    assert packet["search_coverage"]["not_found_state"] == "unknown"
