"""O1: source-bound page OCR with strict mapping and offline trusted replay."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

import pytest

from tests.acceptance.test_parsing import FOREIGN, TENANT
from tests.integration.test_claim_source_verification import inputs


def response(text="Page 1 emissions 1234 tCO2e", *, boundary=False):
    words = []
    # Matches the synthetic PDF's native words, all inside the pinned block.
    for i, (word, x0, x1) in enumerate(
        zip(text.split(), [72, 100, 110, 164, 194], [98, 106, 160, 190, 233], strict=True)
    ):
        words.append(
            dict(
                id=i,
                text=word,
                confidence=0.99,
                boundingBox=dict(
                    vertices=[
                        dict(x=x0 * 3, y=70 * 3),
                        dict(x=x1 * 3, y=70 * 3),
                        dict(x=x1 * 3, y=82 * 3),
                        dict(x=x0 * 3, y=82 * 3),
                    ]
                ),
            )
        )
    if boundary:
        words[2]["boundingBox"]["vertices"][0]["x"] = 60 * 3
    return json.dumps(
        dict(
            apiVersion="1.1",
            modelVersion="ocr-260930",
            numBilledPages=1,
            pages=[dict(id=0, width=1800, height=2400, words=words)],
            stored=False,
        )
    ).encode()


def store(tmp_path, transport=None, cap="0.50", max_calls=36):
    from proofops.adapters.local.upstage import UpstageProbe
    from proofops.adapters.local.upstage_ocr_page import PageOCRStore

    ledger = tmp_path / "upstage.sqlite3"
    UpstageProbe("test-key", ledger)
    spend = tmp_path / "r108-spend.json"
    spend.write_text(json.dumps(dict(limit_usd="10", cumulative_usd="0")))
    return PageOCRStore(
        ledger,
        spend,
        transport=transport or (lambda png: (response(), "provider-1")),
        cap_usd=Decimal(cap),
        max_calls=max_calls,
    )


def test_mapping_scales_provider_pixels_without_text_repair():
    from proofops.adapters.local.upstage_ocr_page import map_words, parse_response, render_page

    source, graph, _ = inputs()
    image = render_page(source, 1)
    box = graph.blocks[0].candidates[0].bbox
    assert (
        map_words(parse_response(response()), image["manifest"], box)["text"]
        == "Page 1 emissions 1234 tCO2e"
    )
    parsed = parse_response(response().replace(b"1800", b"900").replace(b"2400", b"1200"))
    for word in parsed["words"]:
        for vertex in word["polygon"]:
            vertex[0] /= 2
            vertex[1] /= 2
    assert map_words(parsed, image["manifest"], box)["text"] == "Page 1 emissions 1234 tCO2e"
    assert (
        map_words(parse_response(response(boundary=True)), image["manifest"], box)["status"]
        == "unresolved"
    )
    assert (
        map_words(
            parse_response(response()),
            image["manifest"],
            box,
            competing_boxes=[box, [100, 60, 240, 90]],
        )["status"]
        == "unresolved"
    )


def test_snapshot_schema_rotation_overlap_and_order_are_fail_closed():
    from proofops.adapters.local.upstage_ocr_page import map_words, parse_response, render_page

    source, graph, _ = inputs()
    image = render_page(source, 1)
    box = graph.blocks[0].candidates[0].bbox
    for field, value in [("modelVersion", "ocr"), ("numBilledPages", 2), ("apiVersion", "2.0")]:
        obj = json.loads(response())
        obj[field] = value
        with pytest.raises(ValueError):
            parse_response(json.dumps(obj).encode())
    obj = json.loads(response())
    obj["pages"][0]["words"][1]["id"] = 0
    with pytest.raises(ValueError):
        parse_response(json.dumps(obj).encode())
    parsed = parse_response(response())
    parsed["words"][1]["polygon"] = deepcopy(parsed["words"][0]["polygon"])
    assert map_words(parsed, image["manifest"], box)["status"] == "unresolved"
    parsed = parse_response(response())
    parsed["words"][0]["polygon"][1][1] += 15
    assert map_words(parsed, image["manifest"], box)["status"] == "unresolved"
    parsed = parse_response(response())
    parsed["words"] = list(reversed(parsed["words"]))
    assert map_words(parsed, image["manifest"], box)["status"] == "unresolved"


def test_claim_mapping_and_number_negative_without_swift(tmp_path, monkeypatch):
    from proofops.adapters.local import upstage_ocr_profile as profile

    source, graph, ref = inputs()
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("Swift must never run"))
    good = profile.Reader(store(tmp_path / "good"), run_id="run-1")
    receipt = good.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    assert receipt["records"][0]["status"] == "verified"
    assert receipt["run_id"] == "run-1"
    wrong = profile.Reader(
        store(
            tmp_path / "wrong", lambda png: (response("Page 1 emissions 1235 tCO2e"), "provider-2")
        ),
        run_id="run-1",
    )
    assert (
        wrong.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0]["status"]
        == "unresolved"
    )
    assert (
        wrong.attest_native_sources(graph, source, tenant_id=TENANT)["records"][0]["status"]
        == "unresolved"
    )


def test_offline_replay_rejects_response_image_tenant_and_verdict_forgery(tmp_path):
    from proofops.adapters.local import upstage_ocr_profile as profile
    from proofops.domain.provenance import canonical_hash

    source, graph, ref = inputs()
    db = store(tmp_path)
    reader = profile.Reader(db, run_id="run-1")
    receipt = reader.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    db.transport = lambda png: pytest.fail("replay may not call provider")
    assert (
        reader.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=TENANT) == receipt
    )
    for change in [
        lambda r: r["records"][0].update(status="unresolved"),
        lambda r: r["page_collections"][0].update(response_sha256="0" * 64),
        lambda r: r.update(run_id="other"),
    ]:
        forged = deepcopy(receipt)
        change(forged)
        forged["artifact_sha256"] = canonical_hash(
            {k: v for k, v in forged.items() if k != "artifact_sha256"}
        )
        with pytest.raises(ValueError):
            reader.recompute_claim_receipt(forged, graph, source, (ref,), tenant_id=TENANT)
    with pytest.raises(ValueError):
        reader.recompute_claim_receipt(receipt, graph, source + b"x", (ref,), tenant_id=TENANT)
    with pytest.raises(ValueError):
        reader.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=FOREIGN)


def test_permanent_tenant_cache_coalesces_and_reserves_once(tmp_path):
    from proofops.adapters.local.upstage_ocr_page import render_page

    calls = []
    db = store(tmp_path, lambda png: (calls.append(png) or response(), "provider"))
    image = render_page(inputs()[0], 1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: db.fetch(image, tenant_id=TENANT, run_id="run-1"), range(4))
        )
    assert len(calls) == 1 and len({r["request_id"] for r in results}) == 1
    fresh = store(tmp_path, lambda png: pytest.fail("persistent cache should survive restart"))
    assert (
        fresh.fetch(image, tenant_id=TENANT, run_id="run-2")["request_id"]
        == results[0]["request_id"]
    )
    db.fetch(image, tenant_id=FOREIGN, run_id="foreign")
    assert len(calls) == 2


def test_budget_reservation_is_atomic_and_timeouts_count(tmp_path):
    from proofops.adapters.local.upstage_ocr_page import render_page

    calls = []

    def fail(png):
        calls.append(png)
        raise TimeoutError

    db = store(tmp_path, fail, cap="0.00165", max_calls=1)
    image = render_page(inputs()[0], 1)
    with pytest.raises(ValueError):
        db.fetch(image, tenant_id=TENANT, run_id="run")
    with pytest.raises(ValueError):
        db.fetch(image, tenant_id=FOREIGN, run_id="run")
    assert len(calls) == 1
    assert db.usage()["committed_or_reserved_usd"] == "0.00165"
    assert json.loads(db.spend.read_text())["cumulative_usd"] == "0.00165"


def test_legacy_policies_and_dispatch_default_are_unchanged():
    from proofops.adapters.local import glyph_alignment_verification as apple
    from proofops.adapters.local.claim_source_policies import publication_reader

    assert publication_reader(apple.claim_source_policy()) is apple


@pytest.mark.parametrize("operation", [b"BT 3 Tr", b"BT 1 1 1 rg"])
def test_hidden_text_cannot_verify_with_page_ocr(tmp_path, operation):
    from hashlib import sha256
    from io import BytesIO

    from proofops.adapters.local.upstage_ocr_profile import Reader
    from proofops.application.ingest.graph_fusion import fuse_candidates
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    from tests.acceptance.test_parsing import candidate, pdf

    writer = PdfWriter(clone_from=PdfReader(BytesIO(pdf())))
    page = writer.pages[0]
    stream = DecodedStreamObject()
    stream.set_data(page.get_contents().get_data().replace(b"BT", operation))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    source = output.getvalue()
    batch = replace(
        candidate(
            "hidden", [("P", "paragraph", "Page 1 emissions 1234 tCO2e", (70, 710, 300, 740), ())]
        ),
        source_sha256=sha256(source).hexdigest(),
    )
    graph = fuse_candidates((batch,), tenant_id=TENANT)
    blank = json.loads(response())
    blank["pages"][0]["words"] = []
    reader = Reader(
        store(tmp_path, lambda png: (json.dumps(blank).encode(), "blank")), run_id="run"
    )
    assert (
        reader.attest_native_sources(graph, source, tenant_id=TENANT)["records"][0]["status"]
        == "unresolved"
    )


def test_all_private_rendered_paths_use_page_reader_and_leave_apple_globals(tmp_path, monkeypatch):
    import io

    import pdfplumber
    from proofops.adapters.local import source_verification as apple
    from proofops.adapters.local.upstage_ocr_profile import Reader

    source, graph, ref = inputs()
    reader = Reader(store(tmp_path), run_id="run")
    old = apple._rendered_text
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("Swift must never run"))
    modules, seen = reader._modules(graph, source, TENANT)
    for name in (
        "claim_source_verification_v1",
        "claim_source_verification_v2",
        "claim_source_verification",
    ):
        assert (
            modules[name].attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)["records"][0][
                "status"
            ]
            == "verified"
        )
    with pdfplumber.open(io.BytesIO(source)) as pdf:
        assert (
            modules["selected_cell_table_verification"]._rendered_cell(
                pdf.pages[0], graph.blocks[0].candidates[0].bbox
            )["status"]
            == "read"
        )
    assert len(seen) == 1 and apple._rendered_text is old


def test_trusted_collection_cannot_be_rewritten_or_deleted(tmp_path):
    import sqlite3

    from proofops.adapters.local.upstage_ocr_page import render_page

    db = store(tmp_path)
    image = render_page(inputs()[0], 1)
    db.fetch(image, tenant_id=TENANT, run_id="run")
    with sqlite3.connect(db.ledger) as connection:
        for query in ["DELETE FROM ocr_calls", "UPDATE ocr_calls SET collection='{}'"]:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(query)


def test_profile_is_opt_in_through_pilot_snapshot_and_runtime_settings(tmp_path):
    from types import SimpleNamespace

    from proofops.adapters.local import upstage_ocr_profile
    from proofops.adapters.local.claim_source_policies import publication_reader
    from proofops.application.runs import RunService

    from evaluation.local_upstage_pilot import claim_source_policy_for
    from tests.integration import test_run_lifecycle as lifecycle

    service, _ = lifecycle.setup(tmp_path)
    assert service.claim_source_policy is None
    policy = claim_source_policy_for(SimpleNamespace(claim_source_profile="upstage-ocr-page-v1"))
    opted = RunService(
        service.store,
        service.uploads,
        service.registry,
        extraction_profile=service.extraction_profile,
        extraction_mode="upstage_probe",
        claim_source_policy=policy,
    )
    assert opted.claim_source_policy == policy and publication_reader(policy) is upstage_ocr_profile
    bad = deepcopy(policy)
    bad["reader"]["model"] = "ocr"
    with pytest.raises(ValueError):
        publication_reader(bad)


def test_concurrent_distinct_tenants_cannot_overrun_atomic_call_cap(tmp_path):
    from proofops.adapters.local.upstage_ocr_page import render_page

    calls = []
    db = store(tmp_path, lambda png: (calls.append(png) or response(), "provider"), max_calls=1)
    image = render_page(inputs()[0], 1)

    def attempt(tenant):
        try:
            return db.fetch(image, tenant_id=tenant, run_id="run")["request_id"]
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, [TENANT, FOREIGN, "tenant-c", "tenant-d"]))
    assert len(calls) == 1 and sum(r is not None for r in results) == 1
    assert db.usage()["calls"] == 1


def test_exhausted_existing_provider_or_r108_ledger_never_calls(tmp_path):
    import sqlite3

    from proofops.adapters.local.upstage import UpstageProbe
    from proofops.adapters.local.upstage_ocr_page import render_page

    db = store(tmp_path, lambda png: pytest.fail("exhausted shared cap must not call"))
    image = render_page(inputs()[0], 1)
    with sqlite3.connect(db.ledger) as connection:
        connection.executemany(
            "INSERT INTO probe_calls VALUES (?,?,?,?)",
            [(str(i), "s", "1", None) for i in range(10)],
        )
    with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        db.fetch(image, tenant_id=TENANT, run_id="run")
    assert db.usage()["calls"] == 0
    other = store(tmp_path / "r108", lambda png: pytest.fail("exhausted R108 cap must not call"))
    other.spend.write_text(json.dumps(dict(limit_usd="10", cumulative_usd="10")))
    with pytest.raises(ValueError, match="R108_BUDGET_EXHAUSTED"):
        other.fetch(image, tenant_id=TENANT, run_id="run")
    assert other.usage()["calls"] == 0
    with sqlite3.connect(db.ledger) as connection:
        assert UpstageProbe._call_total(connection) == Decimal("10")


def test_unrecognized_word_holds_its_block_without_disabling_other_page_blocks():
    from proofops.adapters.local.upstage_ocr_page import map_words, parse_response, render_page

    data = json.loads(response())
    data["pages"][0]["words"][0]["text"] = ""
    parsed = parse_response(json.dumps(data).encode())
    image = render_page(inputs()[0], 1)
    assert (
        map_words(parsed, image["manifest"], [70, 60, 300, 90])["reason"] == "ocr_unrecognized_word"
    )
    assert (
        map_words(parsed, image["manifest"], [110, 60, 240, 90])["text"] == "emissions 1234 tCO2e"
    )


def test_selected_table_profile_attests_and_replays_without_swift(tmp_path, monkeypatch):
    import io

    import pdfplumber
    from proofops.adapters.local.upstage_ocr_profile import Reader

    from tests.integration.test_selected_cell_table_verification import (
        LAYOUT_A_CELLS,
        LAYOUT_A_WORDS,
        grid_pdf,
        table_graph,
    )

    source = grid_pdf(LAYOUT_A_WORDS)
    graph = table_graph(source, LAYOUT_A_CELLS)
    from proofops.adapters.local.native_glyph_geometry import native_word_ink_geometry

    ink = {
        w["native_word_index"]: w["ink_bbox"]
        for w in native_word_ink_geometry(source, 1, list(range(6)))["matched_words"]
    }
    words = []
    with pdfplumber.open(io.BytesIO(source)) as doc:
        for index, w in enumerate(doc.pages[0].extract_words()):
            x0, top, x1, bottom = ink[index]
            polygon = [(x0, top), (x1, top), (x1, bottom), (x0, bottom)]
            words.append(
                dict(
                    id=index,
                    text=w["text"],
                    confidence=1,
                    boundingBox=dict(vertices=[dict(x=x * 3, y=y * 3) for x, y in polygon]),
                )
            )
    data = json.loads(response())
    data["pages"][0]["words"] = words
    reader = Reader(store(tmp_path, lambda png: (json.dumps(data).encode(), "table")), run_id="run")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("Swift must never run"))
    receipt = reader.attest_tables(graph, source, tenant_id=TENANT)
    assert any(r["selections"] for r in receipt["records"])
    promoted = reader.replay_tables(receipt, graph, source, tenant_id=TENANT)
    assert any(b.kind == "table_cell" and b.quality == "verified" for b in promoted.blocks)


def test_context_source_profile_fresh_and_explicit_replay_are_offline(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from dataclasses import asdict
    from types import SimpleNamespace

    from proofops.adapters.local import upstage_ocr_profile as profile
    from proofops.adapters.local.tag_store import LocalTagStore

    source, graph, ref = inputs()
    reader = profile.Reader(store(tmp_path), run_id="run-1")
    monkeypatch.setattr(profile, "for_run", lambda run_id: reader)
    jobs = SimpleNamespace(_transaction=lambda: nullcontext(object()))
    backend = SimpleNamespace(
        snapshot=lambda *a: {"claim_source_policy": profile.claim_source_policy()}, jobs=jobs
    )
    tags = LocalTagStore(backend, SimpleNamespace(read_original=lambda *a: source), None)
    claim = SimpleNamespace(
        tenant_id=TENANT, document_version_id=graph.document_version_id, claim_id="claim-1"
    )
    case = SimpleNamespace(run_id="run-1", original=graph, context=SimpleNamespace(claim=claim))
    _, receipt = tags.verify_context_sources(case, (ref,))
    reader.store.transport = lambda png: pytest.fail("explicit context replay must be offline")
    published = dict(
        confirmed_tags=dict(claim_id="claim-1"),
        report_level_review=[dict(refs=[asdict(ref)], source_receipt=receipt)],
    )
    _, replay = tags.verify_context_sources(
        case, (ref,), replay_receipt=receipt, published_tag=published
    )
    assert replay == receipt
