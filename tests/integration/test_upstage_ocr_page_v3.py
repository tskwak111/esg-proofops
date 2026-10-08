"""O1c composes only existing finite typography and proven space deletion."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from proofops.domain.provenance import canonical_hash


def typography_reading():
    texts = ["•", "C", "arbon", "2024", "10", "“tCO2e”"]
    boxes = [
        [0, 0, 3, 10],
        [7, 0, 12, 10],
        [12.5, 0, 37, 10],
        [41, 0, 61, 10],
        [65, 0, 75, 10],
        [79, 0, 114, 10],
    ]
    words, matched = [], []
    offset = 0
    for i, (text, box) in enumerate(zip(texts, boxes, strict=True)):
        words.append(dict(index=i, text=text, bbox=box))
        matched.append(
            dict(
                native_word_index=i,
                ink_bbox=box,
                pdfium_char_indices=list(range(offset, offset + len(text))),
            )
        )
        offset += len(text) + (0 if i == 1 else 1)
    return dict(
        reason="rendered_quote_unresolved",
        words=words,
        rendered=dict(status="read", text='· Carbon 2024 10 "tCO2e"'),
        glyph_geometry=dict(source_sha256="a" * 64, physical_page=1, matched_words=matched),
    )


def align(reading=None, quote=None):
    from proofops.adapters.local import upstage_ocr_profile_v3 as v3

    r = reading if reading is not None else typography_reading()
    native = " ".join(w["text"] for w in r["words"])
    return v3.align_reading(
        native=native,
        quote=quote or native,
        reading=r,
        page_num=1,
        bbox=[0, 0, 120, 12],
        source_sha256="a" * 64,
    )


def test_typography_composes_with_unchanged_glyph_conditions_and_literal_native():
    from proofops.adapters.local import claim_span_typography as apple
    from proofops.adapters.local import upstage_ocr_profile_v3 as v3

    r = typography_reading()
    before = deepcopy(r)
    result = align(r)
    assert result["status"] == "verified"
    assert result["deleted_native_offsets"] == [3]
    assert result["native_text"] == "• C arbon 2024 10 “tCO2e”"
    assert result["aligned_quote"] == "• Carbon 2024 10 “tCO2e”"
    assert result["rendered_read_sha256"] == canonical_hash(r["rendered"])
    assert result["typography_substitutions"]
    assert v3.normalization_policy()["rendered_fold_entries"] == [
        f"{s}->{t}" for s, t in apple._ADMITTED_ENTRIES
    ]
    assert r == before


@pytest.mark.parametrize(
    "text",
    [
        '1 Carbon 2024 10 "tCO2e"',
        'x Carbon 2024 10 "tCO2e"',
        '● Carbon 2024 10 "tCO2e"',
        '▪ Carbon 2024 10 "tCO2e"',
        '· Carbon 2025 10 "tCO2e"',
        '· Carbon 2024 11 "tCO2e"',
        '· Carbon 2024 -10 "tCO2e"',
        '· Carbon 2024 10 "kgCO2e"',
        "· Carbon 2024 10 ′tCO2e′",
        '· Carbon 2024 10 "tC02e"',
        '· Carbon2024 10 "tCO2e"',
        '· Carbon 2024 1 0 "tCO2e"',
        "",
    ],
)
def test_forged_bullets_numbers_units_signs_and_other_spaces_never_promote(text):
    r = typography_reading()
    r["rendered"]["text"] = text
    assert align(r)["status"] != "verified"


@pytest.mark.parametrize("fault", ["real_space", "gap", "proof", "page", "read", "reason"])
def test_native_geometry_and_rendered_guards_remain_required(fault):
    r = typography_reading()
    if fault == "real_space":
        for m in r["glyph_geometry"]["matched_words"][2:]:
            m["pdfium_char_indices"] = [i + 1 for i in m["pdfium_char_indices"]]
    elif fault == "gap":
        r["words"][2]["bbox"][0] = 15
    elif fault == "proof":
        r.pop("glyph_geometry")
    elif fault == "page":
        r["glyph_geometry"]["physical_page"] = 2
    elif fault == "read":
        r["rendered"]["status"] = "unresolved"
    else:
        r["reason"] = "interactive_visibility_requires_review"
    assert align(r)["status"] != "verified"


def test_native_quote_is_never_typography_folded():
    assert align(quote='· C arbon 2024 10 "tCO2e"')["status"] != "verified"


def test_v3_dispatch_and_prior_policies_are_distinct():
    from proofops.adapters.local import upstage_ocr_profile as v1
    from proofops.adapters.local import upstage_ocr_profile_v2 as v2
    from proofops.adapters.local import upstage_ocr_profile_v3 as v3
    from proofops.adapters.local.claim_source_policies import publication_reader
    from proofops.adapters.parsing.opendataloader import _locates_auxiliary_cells, _table_verifier

    from evaluation.local_upstage_pilot import claim_source_policy_for

    policy = claim_source_policy_for(SimpleNamespace(claim_source_profile=v3.PROFILE))
    assert policy == v3.claim_source_policy()
    for profile in (v1, v2, v3):
        assert publication_reader(profile.claim_source_policy()) is profile
    assert v3.reader_policy()["mapping_sha256"] == v2.reader_policy()["mapping_sha256"]
    assert _table_verifier(v3.table_policy_sha256()) is v3
    assert _locates_auxiliary_cells({"table_source_policy_sha256": v3.table_policy_sha256()})
    policy["normalization"]["rendered_fold_entries"].append("U+0031->U+2022")
    with pytest.raises(ValueError):
        publication_reader(policy)


def test_v3_cached_response_offline_replay_and_numeric_guard(tmp_path, monkeypatch):
    from proofops.adapters.local import upstage_ocr_profile_v3 as v3

    from tests.integration.test_upstage_ocr_page_v2 import (
        test_v2_reuses_v1_collection_and_replays_offline_with_numeric_guard as check,
    )

    monkeypatch.setattr("proofops.adapters.local.upstage_ocr_profile_v2", v3)
    for text in ("Page 1 emissions 1234 tCO2e", "Page 1 emissions 1235 tCO2e"):
        check(tmp_path / text.split()[3], monkeypatch, text)


def test_v3_context_and_native_receipts_replay_with_run_and_policy_guards(tmp_path, monkeypatch):
    from proofops.adapters.local import upstage_ocr_profile_v3 as v3

    from tests.integration.test_upstage_ocr_page_v2 import (
        test_v2_context_receipt_replay_and_run_binding as context,
    )
    from tests.integration.test_upstage_ocr_page_v2 import (
        test_v2_native_dispatch_replays_and_rejects_policy_mutation as native,
    )

    monkeypatch.setattr("proofops.adapters.local.upstage_ocr_profile_v2", v3)
    context(tmp_path / "context", monkeypatch)
    native(tmp_path / "native", monkeypatch)


def test_v3_selected_cell_and_table_span_replay_are_offline(tmp_path, monkeypatch):
    import json
    from io import BytesIO

    import pdfplumber
    from proofops.adapters.local import upstage_ocr_profile_v3 as v3
    from proofops.adapters.local.native_glyph_geometry import native_word_ink_geometry

    from tests.acceptance.test_parsing import TENANT
    from tests.integration.test_selected_cell_table_verification import (
        LAYOUT_B_CELLS,
        LAYOUT_B_WORDS,
        grid_pdf,
        table_graph,
    )
    from tests.integration.test_upstage_ocr_page import response, store

    source = grid_pdf(LAYOUT_B_WORDS)
    graph = table_graph(source, LAYOUT_B_CELLS)
    with pdfplumber.open(BytesIO(source)) as doc:
        words = doc.pages[0].extract_words()
    proof = native_word_ink_geometry(source, 1, list(range(len(words))))
    payload = json.loads(response())
    payload["pages"][0]["words"] = []
    for match in proof["matched_words"]:
        i = match["native_word_index"]
        x0, y0, x1, y1 = match["ink_bbox"]
        payload["pages"][0]["words"].append(
            dict(
                id=i,
                text=words[i]["text"],
                confidence=0.99,
                boundingBox=dict(
                    vertices=[
                        dict(x=x * 3, y=y * 3) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
                    ]
                ),
            )
        )
    db = store(tmp_path, lambda png: (json.dumps(payload).encode(), "provider-table"))
    reader = v3.Reader(db, run_id="table-run")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("Swift must never run"))
    receipt = reader.attest_tables(graph, source, tenant_id=TENANT)
    assert receipt["records"][0]["status"] == "partially_verified"
    before = db.usage()
    db.transport = lambda png: pytest.fail("table replay must be offline")
    promoted = reader.replay_tables(receipt, graph, source, tenant_id=TENANT)
    value = next(b for b in graph.blocks if b.kind == "table_cell" and b.raw_text == "155,446")
    assert next(b for b in promoted.blocks if b.source_id == value.source_id).quality == "verified"

    # Table-span verification additionally requires table-row ownership, which
    # the selected-cell-only fixture above deliberately omits.
    from tests.integration.test_native_table_admission import fixture

    span_source, span_graph = fixture()
    span_reader = v3.Reader(store(tmp_path / "spans"), run_id="span-run")
    # Mock the OCR transport, deriving polygons from these original PDF words.
    with pdfplumber.open(BytesIO(span_source)) as doc:
        span_words = doc.pages[0].extract_words()
    span_proof = native_word_ink_geometry(span_source, 1, list(range(len(span_words))))
    span_payload = json.loads(response())
    span_payload["pages"][0]["words"] = []
    for match in span_proof["matched_words"]:
        i = match["native_word_index"]
        x0, y0, x1, y1 = match["ink_bbox"]
        span_payload["pages"][0]["words"].append(
            dict(
                id=i,
                text=span_words[i]["text"],
                confidence=0.99,
                boundingBox=dict(
                    vertices=[
                        dict(x=x * 3, y=y * 3) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
                    ]
                ),
            )
        )
    span_reader.store.transport = lambda png: (json.dumps(span_payload).encode(), "provider-span")
    value = next(b for b in span_graph.blocks if b.kind == "table_cell" and b.raw_text == "79")
    ref = value.source_ref()
    span = span_reader.attest_table_spans(span_graph, span_source, (ref,), tenant_id=TENANT)
    assert span["records"][0]["status"] == "verified"
    span_reader.store.transport = lambda png: pytest.fail("span replay must be offline")
    span_before = span_reader.store.usage()
    assert (
        span_reader.recompute_table_span_receipt(
            span, span_graph, span_source, (ref,), tenant_id=TENANT
        )
        == span
    )
    forged = deepcopy(span)
    forged["run_id"] = "other-run"
    with pytest.raises(ValueError):
        span_reader.recompute_table_span_receipt(
            forged, span_graph, span_source, (ref,), tenant_id=TENANT
        )
    assert db.usage() == before and span_reader.store.usage() == span_before
