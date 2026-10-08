from hashlib import sha256
from io import BytesIO

import pytest
from proofops.adapters.local.missing_evidence import document_search
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from tests.integration.test_missing_evidence import results


def vector_pdf(native="REPORT 1", *, outside=False, vector=True, image=False):
    writer = PdfWriter()
    if outside:
        writer.add_blank_page(width=600, height=800)
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    if outside:
        # A readable selected page must not independently mask the outside-page bug.
        first = writer.pages[0]
        first[NameObject("/Resources")] = page["/Resources"]
        first_text = DecodedStreamObject()
        first_text.set_data(b"BT /F1 16 Tf 60 730 Td (plain text) Tj ET")
        first[NameObject("/Contents")] = writer._add_object(first_text)
    # Native header and a large outlined numerical disclosure; no raster images.
    commands = [f"BT /F1 16 Tf 60 730 Td ({native}) Tj ET", "4 w"] if native else []
    endpoints = {
        "a": (0, 80, 40, 80),
        "b": (40, 80, 40, 40),
        "c": (40, 40, 40, 0),
        "d": (0, 0, 40, 0),
        "e": (0, 40, 0, 0),
        "f": (0, 80, 0, 40),
        "g": (0, 40, 40, 40),
    }
    segments = {"2": "abged", "0": "abcdef", "3": "abgcd"}
    for index, digit in enumerate("2030" if vector else ""):
        for segment in segments[digit]:
            x1, y1, x2, y2 = endpoints[segment]
            x = 80 + index * 70
            commands.append(f"{x+x1} {500+y1} m {x+x2} {500+y2} l S")
    if vector and len(native) > 200:
        # The word TARGET is paths too; it has no native text representation.
        glyphs = {
            "T": [(0, 40, 30, 40), (15, 40, 15, 0)],
            "A": [(0, 0, 15, 40), (15, 40, 30, 0), (7, 20, 23, 20)],
            "R": [
                (0, 0, 0, 40),
                (0, 40, 30, 40),
                (30, 40, 30, 20),
                (30, 20, 0, 20),
                (0, 20, 30, 0),
            ],
            "G": [(30, 40, 0, 40), (0, 40, 0, 0), (0, 0, 30, 0), (30, 0, 30, 20), (30, 20, 15, 20)],
            "E": [(0, 0, 0, 40), (0, 40, 30, 40), (0, 20, 25, 20), (0, 0, 30, 0)],
        }
        for i, glyph in enumerate("TARGET"):
            for x1, y1, x2, y2 in glyphs[glyph]:
                commands.append(f"{60+i*50+x1} {350+y1} m {60+i*50+x2} {350+y2} l S")
    if image:
        from pypdf.generic import NumberObject

        raster = DecodedStreamObject()
        raster.set_data(b"\xff\xff\xff")
        raster.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(1),
                NameObject("/Height"): NumberObject(1),
                NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                NameObject("/BitsPerComponent"): NumberObject(8),
            }
        )
        page["/Resources"][NameObject("/XObject")] = DictionaryObject(
            {NameObject("/Im1"): writer._add_object(raster)}
        )
        commands.append("q 600 0 0 640 0 0 cm /Im1 Do Q")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.mark.parametrize("native", ["REPORT 1", "plain text " * 50])
@pytest.mark.parametrize("outside", [False, True])
def test_vector_content_remains_unreviewed(native, outside):
    content = vector_pdf(native, outside=outside)
    # Keep the generated PDF in memory.
    doc = document_search(
        content,
        identity=dict(source_sha256=sha256(content).hexdigest(), page_count=2 if outside else 1),
        selected_pages=[1],
    )
    rows = results(doc)
    page = "2" if outside else "1"
    assert doc["page_texts"][page] == native
    assert doc["page_readability"][page]["text_layer_readable"]
    assert not doc["coverage"]["unreadable_pages"]
    assert not doc["page_readability"][page]["whole_page_content_reviewed"]
    assert int(page) in doc["coverage"]["unreviewed_content_pages"]
    assert rows[0]["undetermined_reason"] == "no_text_candidate"
    assert rows[0]["search"]["coverage"]["searched_pages"] == ([1, 2] if outside else [1])
    assert doc["coverage"]["absence_readability_complete"] is False
    assert next(e for e in rows if e["element_id"] == "G1")["evidence_status"] == "undetermined"
    assert all(e["engine_state"] == "unknown" for e in rows)


def test_regular_image_page_keeps_all_unresolved_images():
    # Production page assessment: a readable text page still has an unverified image.
    from proofops.adapters.local.missing_evidence import page_readability

    from tests.integration.test_missing_evidence import doc

    item = page_readability("plain text " * 50, [0.8])
    assert item["text_layer_readable"] and not item["image_content_verified"]
    document = doc({1: "plain text " * 50})
    document["coverage"].update(
        image_pages=[1], image_dominant_unreadable_pages=[], absence_readability_complete=False
    )
    rows = results(document)
    assert rows[0]["evidence_status"] == "undetermined"
    assert rows[0]["search"]["unresolved_image_pages"] == [1]


@pytest.mark.parametrize("historical", [False, True])
def test_r4_saved_failure_status_loads_without_reclassification(tmp_path, monkeypatch, historical):
    import json
    from dataclasses import replace

    from proofops.application.budget import TokenUsage
    from proofops.application.tagging.service import RawTagResponse
    from proofops_worker import tag_runner as module

    from tests.integration.test_local_tag_runner import TENANT, verified_setup

    service, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    invoke = runner.transport.invoke

    def response(request):
        if request["replicate_id"] == 2:
            return RawTagResponse(
                None,
                TokenUsage(10, 5, 0, 0, 1, "succeeded", "citation-fixture"),
                True,
                json.dumps({"validation_error": "TAGGING_EVIDENCE_ID_INVALID"}),
            )
        return invoke(request)

    monkeypatch.setattr(runner.transport, "invoke", response)
    if historical:
        real = module.tag_replicates

        def old_result(*args, **kwargs):
            return tuple(
                replace(r, status="model_failed", errors=("MODEL_UNAVAILABLE",))
                if r.status == "citation_unresolved"
                else r
                for r in real(*args, **kwargs)
            )

        monkeypatch.setattr(module, "tag_replicates", old_result)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    snapshot = runner.tags.load_snapshot(TENANT, run_id)
    claim_id = snapshot["claims"][0]["claim_id"]
    before = json.dumps(snapshot, sort_keys=True)
    loaded = runner.tags.load_inputs(TENANT, run_id, claim_id)
    assert loaded.tag_runs[1].status == ("model_failed" if historical else "citation_unresolved")
    assert "REPLICA_UNRESOLVED" in loaded.consensus.reasons
    assert json.dumps(runner.tags.load_snapshot(TENANT, run_id), sort_keys=True) == before


def test_r4_partial_facts_changes_beyond_diagnostic_label(tmp_path):
    import json
    from dataclasses import replace

    from proofops.application.budget import TokenUsage
    from proofops.application.tagging.consensus import PARTIAL_FACTS_V1, form_consensus
    from proofops.application.tagging.service import RawTagResponse

    from tests.acceptance.test_tagging import TENANT, execute, setup

    inputs = setup(tmp_path)
    invoke = inputs["invoke"]

    def response(request):
        if request["replicate_id"] == 2:
            return RawTagResponse(
                None,
                TokenUsage(10, 5, 0, 0, 1, "succeeded", "citation-fixture"),
                True,
                json.dumps({"validation_error": "TAGGING_EVIDENCE_ID_INVALID"}),
            )
        return invoke(request)

    inputs["invoke"] = response
    current = execute(inputs)
    old = tuple(
        replace(r, status="model_failed", errors=("MODEL_UNAVAILABLE",))
        if r.status == "citation_unresolved"
        else r
        for r in current
    )
    options = dict(
        packet=inputs["packet"],
        rulepack=inputs["rulepack"],
        tenant_id=TENANT,
        tag_revision=1,
        profile=PARTIAL_FACTS_V1,
    )
    before, after = form_consensus(old, **options), form_consensus(current, **options)
    assert len(before.candidate_elements) == 6 and all(
        e.state == "unknown" for e in before.candidate_elements
    )
    assert before.confirmed_tags is not None
    assert after.candidate_elements == before.candidate_elements
    assert after.confirmed_tags is not None
    assert after.reasons == before.reasons


def test_unstamped_complete_native_search_cannot_attest_whole_page_review():
    from tests.integration.test_missing_evidence import doc

    document = doc({1: "plain text"})
    document["coverage"]["absence_readability_complete"] = True
    assert all(row["evidence_status"] == "undetermined" for row in results(document))


def test_v2_reader_and_bytes_are_preserved():
    from copy import deepcopy

    from proofops.application.evidence.missing import SEARCH_PROFILE_HASH
    from proofops.domain.rulepacks import canonical_json

    from tests.integration.test_missing_evidence import doc

    legacy_hash = "422b0ab94a3e8ff8924ffc449c0b02adf830d313ac4e80f9116448d694df6774"
    document = doc({1: "plain text"})
    document["profile_sha256"] = legacy_hash
    document["coverage"]["absence_readability_complete"] = True
    before = canonical_json(document)
    output = results(document)
    assert all(row["evidence_status"] == "not_found_in_report" for row in output)
    assert all(row["search"]["profile_sha256"] == legacy_hash for row in output)
    assert canonical_json(document) == before
    current = deepcopy(document)
    current["profile_sha256"] = SEARCH_PROFILE_HASH
    assert SEARCH_PROFILE_HASH != legacy_hash
    assert all(row["evidence_status"] == "undetermined" for row in results(current))


@pytest.mark.parametrize("profile", ["strict-v1", "partial-facts-v1"])
def test_citation_failure_cannot_approve_two_valid_replica_votes(tmp_path, profile):
    from dataclasses import replace

    from proofops.application.tagging.consensus import form_consensus

    from tests.acceptance.test_tagging import TENANT, execute, setup

    inputs = setup(tmp_path)
    runs = execute(inputs)
    options = dict(
        packet=inputs["packet"],
        rulepack=inputs["rulepack"],
        tenant_id=TENANT,
        tag_revision=1,
        profile=profile,
    )
    failed = replace(
        runs[1], guarded=None, status="citation_unresolved", errors=("TAGGING_EVIDENCE_ID_INVALID",)
    )
    after = form_consensus((runs[0], failed, runs[2]), **options)
    assert after.review_status == "needs_review"
    assert after.confirmed_tags is None or all(
        f.state != "present" for f in after.confirmed_tags.facts
    )
    if profile == "partial-facts-v1":
        assert len(after.candidate_elements) == 6
        assert all(e.state == "unknown" and not e.evidence_refs for e in after.candidate_elements)
    else:
        assert after.confirmed_tags is None
        assert "REPLICA_UNRESOLVED" in after.reasons
    # A diagnostic attached to an existing guarded vote is not an unavailable vote.
    guarded_failure = replace(failed, guarded=runs[1].guarded)
    invalid = form_consensus((runs[0], guarded_failure, runs[2]), **options)
    assert invalid.confirmed_tags is None
    # Do not widen the exception to unrelated provenance/security errors.
    unsafe = replace(failed, errors=failed.errors + ("MODEL_PROVENANCE_INVALID",))
    assert form_consensus((runs[0], unsafe, runs[2]), **options).confirmed_tags is None


@pytest.mark.parametrize(
    "native,image,expected",
    [
        ("plain text " * 50, False, "text_readable"),
        ("plain text " * 50, True, "text_readable"),
        ("", True, "image_dominant_unreadable"),
        ("", False, "empty_text"),
    ],
)
def test_real_pdf_text_image_blank_and_export_consistency(native, image, expected):
    import csv
    import json
    from io import StringIO

    from proofops.application.reporting import build_report_model, render_report
    from proofops_api.routers.claims import ElementEvidenceSearch

    from tests.acceptance.test_report import decisions, manifest

    content = vector_pdf(native, vector=False, image=image)
    document = document_search(
        content, identity=dict(source_sha256=sha256(content).hexdigest(), page_count=1)
    )
    assert document["page_readability"]["1"]["state"] == expected
    assert document["coverage"]["image_pages"] == ([1] if image else [])
    assert not document["coverage"]["absence_readability_complete"]
    rows = results(document)
    assert all(row["evidence_status"] == "undetermined" for row in rows)
    assert all(row["engine_state"] == "unknown" for row in rows)
    api_rows = [ElementEvidenceSearch.model_validate(row).model_dump(mode="json") for row in rows]
    assert api_rows == rows
    model = build_report_model(manifest(), decisions())
    model["claims"][0]["element_evidence"] = api_rows
    html = render_report(model, "html").decode()
    assert "텍스트 판독불가 쪽: " + ("[]" if native else "[1]") in html
    assert "이미지 내용 미확인 쪽: " + ("[1] (1개)" if image else "[] (0개)") in html
    if image and native:
        assert "이미지 쪽 1개 미확인" in html
    csv_row = next(csv.DictReader(StringIO(render_report(model, "csv").decode())))
    assert json.loads(csv_row["element_evidence"]) == rows
    assert json.loads(render_report(model, "json"))["claims"][0]["element_evidence"] == rows


def test_v3_api_keeps_v2_artifacts_and_run_state_byte_identical(tmp_path, monkeypatch):
    import json

    from proofops.application.evidence.missing import (
        LEGACY_SEARCH_PROFILE_HASH,
        SEARCH_PROFILE_HASH,
    )
    from proofops.domain.provenance import canonical_hash
    from proofops_api.routers.claims import build_claims_router

    from tests.integration.test_local_tag_runner import TENANT, verified_setup
    from tests.integration.test_run_lifecycle import client

    service, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    claim = runner.claims.list(TENANT, run_id)[0]
    snapshot = service.store.snapshot(TENANT, run_id)
    identity = dict(
        tenant_id=TENANT,
        run_id=run_id,
        document_version_id=claim.document_version_id,
        parse_manifest_id=claim.parse_manifest_id,
        source_sha256=claim.source_sha256,
        page_count=snapshot["document"]["page_count"],
    )
    content = runner.claims.uploads.read_original(TENANT, claim.document_version_id)
    legacy = document_search(content, identity=identity, selected_pages=snapshot["selected_pages"])
    legacy["profile_sha256"] = LEGACY_SEARCH_PROFILE_HASH
    legacy.pop("whole_document_policy")
    for item in legacy["page_readability"].values():
        item.pop("whole_page_content_reviewed")
    legacy["coverage"].pop("whole_page_content_reviewed_pages")
    legacy["coverage"].pop("unreviewed_content_pages")
    legacy["artifact_sha256"] = canonical_hash(
        {k: v for k, v in legacy.items() if k != "artifact_sha256"}
    )
    key = canonical_hash(identity | {"profile_sha256": LEGACY_SEARCH_PROFILE_HASH})
    legacy_rows = results(legacy)
    jobs = service.store.jobs
    with jobs._transaction() as db:
        jobs._put(db, TENANT, run_id, "document_evidence_search", key, legacy, immutable=True)
        jobs._put(
            db,
            TENANT,
            run_id,
            "element_evidence_search",
            "legacy-fixture",
            {"elements": legacy_rows},
            immutable=True,
        )
        before = db.execute(
            "SELECT kind, record_id, value FROM job_records WHERE tenant_id=? AND run_id=?",
            (TENANT, run_id),
        ).fetchall()
    http, auth = client(service)
    http.app.include_router(build_claims_router(runner.claims, auth, tags=runner.tags))
    url = f"/v1/runs/{run_id}/claims/{claim.claim_id}"
    response = http.get(url)
    assert response.status_code == 200, response.text
    assert all(
        row["search"]["profile_sha256"] == SEARCH_PROFILE_HASH
        for row in response.json()["element_evidence"]
    )
    assert http.get(url).json() == response.json()
    assert service.store.snapshot(TENANT, run_id) == snapshot
    with jobs._transaction() as db:
        for kind, record_id, raw in before:
            assert jobs._raw(db, TENANT, run_id, kind, record_id) == raw
        assert len(jobs._all(db, TENANT, run_id, "document_evidence_search")) == 2
        assert len(jobs._all(db, TENANT, run_id, "element_evidence_search")) == 2
        assert (
            results(json.loads(jobs._raw(db, TENANT, run_id, "document_evidence_search", key)))
            == legacy_rows
        )
