"""MC scope/readability/citation guards with real local search and API artifacts."""

from copy import deepcopy
from hashlib import sha256

from proofops.adapters.local.evidence_search import LocalEvidenceSearch
from proofops.adapters.local.missing_evidence import document_search
from proofops.application.evidence.missing import literal_hits, search_elements
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_claims import TENANT, graph_of


def doc(pages, *, unreadable=(), missing=(), count=None):
    count = count or len(pages)
    return dict(
        page_texts={str(k): v for k, v in pages.items()},
        artifact_sha256="a" * 64,
        selected_pages=[1],
        coverage=dict(
            page_count=count,
            searched_pages=sorted(pages),
            readable_pages=sorted(set(pages) - set(unreadable)),
            unreadable_pages=list(unreadable),
            missing_pages=list(missing),
        ),
    )


def results(document, elements=None, confirmed=None):
    return search_elements(
        track="goal",
        claim_quote="2030년 NF3 감축 목표",
        document=document,
        elements=elements or [],
        confirmed_refs=confirmed or {},
        candidate_refs={},
    )


def test_complete_miss_display_only_and_coverage_gaps_stay_unknown():
    complete = doc({1: "nothing relevant", 2: "plain text"})
    original = deepcopy(complete)
    assert all(e["evidence_status"] == "not_found_in_report" for e in results(complete))
    assert all(
        e["engine_state"] == "unknown" and not e["search"]["absence_admissible"]
        for e in results(complete)
    )
    assert complete == original
    for partial in (
        doc({1: "nothing relevant"}, count=2, missing=[2]),
        doc({1: "nothing relevant", 2: "plain text"}, unreadable=[2]),
    ):
        assert all(e["evidence_status"] == "undetermined" for e in results(partial))
        assert "보고서에서 찾지 못함" not in str(results(partial))


def test_native_candidate_outside_selection_never_confirms_or_supplies_numbers():
    document = doc({1: "NF3 감축", 2: "2030년 스팀 900 tCO2 다른 사업장"})
    res = results(document)
    g1 = res[0]
    assert g1["evidence_status"] == "undetermined"
    assert g1["search"]["outside_selected_pages"] == [2]
    assert "보고서 부재 판정이 아닙니다" in g1["search"]["scope_note"]
    assert g1["undetermined_reason"] == "no_text_candidate"
    assert all(e["engine_state"] == "unknown" and not e["evidence_refs"] for e in res)


def test_unvalidated_present_conflict_and_na_never_become_confirmed_or_absent():
    elements = [
        dict(element_id="G1", state="present"),
        dict(element_id="G2", state="conflict"),
        dict(element_id="G3", state="not_applicable"),
    ]
    output = results(doc({1: "plain text"}), elements)
    assert [e["evidence_status"] for e in output[:3]] == ["undetermined"] * 3
    assert [e["engine_state"] for e in output[:3]] == ["present", "conflict", "not_applicable"]


def test_exhaustive_bm25_and_literals_find_beyond_top20_without_changing_legacy():
    graph = graph_of(*[f"NF3 목표 {i}" for i in range(30)])
    search = LocalEvidenceSearch(graph, tenant_id=TENANT, pages=range(1, 31), index_generation="MC")
    assert len(search.search(search.scope, "목표").hits) == 20
    assert len(search.search_all(search.scope, "목표").hits) == 30
    assert literal_hits({30: "목 표 연 도 2030"}, ["목표연도", "2030"])[0]["char_start"] == 0
    assert search.search_all(search.scope, "목표").status == "complete"


def test_document_native_index_all_pages_and_priority_without_paid_parse():
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=600, height=800)
    output = BytesIO()
    writer.write(output)
    content = output.getvalue()
    document = document_search(
        content,
        identity=dict(source_sha256=sha256(content).hexdigest(), page_count=3),
        selected_pages=[2, 3],
        environment_pages=[2],
    )
    assert document["coverage"]["searched_pages"] == [1, 2, 3]
    assert document["coverage"]["search_order"] == [2, 3, 1]
    assert document["coverage"]["unreadable_pages"] == [1, 2, 3]
    assert document["artifact_sha256"] == canonical_hash(
        {k: v for k, v in document.items() if k != "artifact_sha256"}
    )


def test_real_api_search_artifacts_are_idempotent_tenant_scoped_and_additive(tmp_path, monkeypatch):
    from proofops_api.routers.claims import build_claims_router

    from tests.integration.test_local_tag_runner import verified_setup
    from tests.integration.test_run_lifecycle import client, validate

    service, run_id, runner, now, _ = verified_setup(tmp_path, monkeypatch)
    http, auth = client(service)
    http.app.include_router(build_claims_router(runner.claims, auth, tags=runner.tags))
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    claim = runner.claims.list(TENANT, run_id)[0]
    before = service.store.snapshot(TENANT, run_id)
    url = f"/v1/runs/{run_id}/claims/{claim.claim_id}"
    first = http.get(url)
    assert first.status_code == 200, first.text
    validate("ClaimDetail", first.json())
    assert len(first.json()["element_evidence"]) == 6
    assert all(e["engine_state"] == "unknown" for e in first.json()["element_evidence"])
    assert http.get(url).json() == first.json()
    assert service.store.snapshot(TENANT, run_id) == before
    with service.store.jobs._transaction() as db:
        assert len(service.store.jobs._all(db, TENANT, run_id, "document_evidence_search")) == 1
        assert len(service.store.jobs._all(db, TENANT, run_id, "element_evidence_search")) == 1
    http.cookies.clear()
    assert http.get(url).status_code == 401


def test_confirmed_requires_real_citation_and_binding_metric_period_boundary_guards():
    from dataclasses import asdict
    from types import SimpleNamespace

    from proofops.adapters.local.missing_evidence import validated_present_refs
    from proofops.application.evidence.binding import ClaimContext

    from tests.acceptance.test_binding import DIMENSIONS, corpus, span, tags
    from tests.acceptance.test_rules import pack

    # Synthetic provenance fixture; production guards, no mocked gate results.
    for change in ({}, {"metric": "스팀량"}, {"reporting_period": "2026"}, {"boundary": "해외"}):
        graph, claim, refs = corpus(**change)
        inputs = SimpleNamespace(
            validate=lambda: None,
            context=ClaimContext(claim, tags(refs[0])),
            relation_tags={refs[1].source_id: tags(refs[1], DIMENSIONS | change)},
            rulepack=pack(),
        )
        ref = span(refs[0] if not change else refs[1], "40%")
        elements = [
            dict(element_id="P1", state="present", evidence_refs=[asdict(ref)], reason_code=None)
        ]
        validated = validated_present_refs(elements, inputs, claim, graph)
        assert bool(validated) == (not change)
        if not change:
            assert validated["P1"][0]["quote"] == "40%"
        else:
            assert elements[0]["state"] == "present"  # read-only, old revision untouched


def test_all_export_formats_preserve_card_and_search_record(tmp_path, monkeypatch):
    import json

    from tests.acceptance.test_exports import archive, create, exports
    from tests.integration.test_revision_coverage import resolve

    ws = exports(tmp_path, monkeypatch)
    resolve(ws)
    response = create(ws)
    assert response.status_code == 202, response.text
    bundle, _, _ = archive(ws, response.json())
    model = json.loads(bundle.read("report.json"))
    card = model["claims"][0]["element_evidence"]
    assert card and all(e["search"]["terms"] for e in card)
    assert "element_evidence" in bundle.read("report.csv").decode()
    html = bundle.read("report.html").decode()
    assert "부족 근거 카드" in html and "판독불가·미해결 쪽" in html


def test_mc2_text_and_image_readability_are_separate_from_absence():
    from proofops.adapters.local.missing_evidence import page_readability
    from proofops.application.evidence.element_queries import READABILITY_POLICY

    minimum = READABILITY_POLICY["normal_text_min_chars"]
    assert page_readability("text " * minimum, [0.8])["state"] == "text_readable"
    assert page_readability("Logo", [0.01])["state"] == "text_readable"
    assert page_readability("Cover", [0.8])["state"] == "image_dominant_unreadable"
    assert page_readability("", [0.8])["state"] == "image_dominant_unreadable"
    assert page_readability("\ufffd" * minimum, [0.01])["state"] == "invalid_text"


def test_mc2_subreasons_use_same_window_anchors_not_report_global_numbers():
    def search(quote, text):
        document = doc({1: text}, unreadable=[])
        document["coverage"]["absence_readability_complete"] = False
        return search_elements(
            track="goal",
            claim_quote=quote,
            document=document,
            elements=[],
            confirmed_refs={},
            candidate_refs={},
        )[0]

    quote = "국내 NF3 공정가스 감축 목표 2030년"
    matching = search(quote, quote)
    assert matching["undetermined_reason"] == "candidate_needs_review"
    preview = matching["search"]["native_candidates"][0]
    assert preview["linkage"] == "matched" and len(preview["quote"]) <= 200
    assert not preview["citation_verified"] and not preview["binding_accepted"]
    wrong = search(quote, "해외 NF3 공정가스 감축 목표 2026년")
    assert wrong["undetermined_reason"] == "linkage_unclear"
    assert "기간" in wrong["search"]["native_candidates"][0]["rejection_reason"]
    assert "범위" in wrong["search"]["native_candidates"][0]["rejection_reason"]
    unrelated = search(quote, "해외 스팀량 목표 2030년")
    assert unrelated["undetermined_reason"] == "no_text_candidate"
    split = search(quote, "NF3 공정가스 목표 " + "다른 문장 " * 100 + "국내 2030년")
    assert split["undetermined_reason"] == "linkage_unclear"
    assert all(
        r["engine_state"] == "unknown" and r["evidence_status"] == "undetermined"
        for r in (matching, wrong, unrelated, split)
    )


def test_mc2_large_image_native_geometry_and_whole_absence_guard():
    from io import BytesIO

    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
        NumberObject,
    )

    writer = PdfWriter()
    image = DecodedStreamObject()
    image.set_data(b"\xff\xff\xff")
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    page = writer.add_blank_page(width=600, height=800)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): writer._add_object(image)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"q 600 0 0 800 0 0 cm /Im1 Do Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    content = output.getvalue()
    document = document_search(
        content, identity=dict(source_sha256=sha256(content).hexdigest(), page_count=1)
    )
    assert document["coverage"]["image_dominant_unreadable_pages"] == [1]
    assert document["page_readability"]["1"]["largest_image_area_ratio"] == 1.0
    assert not document["coverage"]["absence_readability_complete"]


def test_mc2_matching_unit_and_year_do_not_establish_metric_candidate():
    document = doc({1: "국내 스팀 감축 목표 2030년 100 tCO2eq"})
    document["coverage"]["absence_readability_complete"] = False
    rows = search_elements(
        track="goal",
        claim_quote="국내 NF3 감축 목표 2030년 100 tCO2eq",
        document=document,
        elements=[],
        confirmed_refs={},
        candidate_refs={},
    )
    assert rows[0]["undetermined_reason"] == "linkage_unclear"
    assert all(
        candidate["linkage"] == "rejected" for candidate in rows[0]["search"]["native_candidates"]
    )
    assert all(row["engine_state"] == "unknown" and not row["evidence_refs"] for row in rows)
