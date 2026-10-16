"""H6: bounded parsing and explicit holds preserve source and money guards."""

import io
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from proofops.adapters.parsing import h6_local_pages
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure
from proofops.application.ingest.graph_fusion import ParserProfile
from proofops.domain.provenance import canonical_hash
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

from tests.acceptance.test_parsing import FOREIGN, JAVA, TENANT
from tests.integration.test_claim_source_verification import inputs
from tests.integration.test_mixed_parser import document
from tests.integration.test_upstage_ocr_page import response, store


def test_h6_keeps_k11_and_v12_hashes():
    from proofops.application.analysis_profile import (
        FINALS_H6_POLICY,
        FINALS_I11_POLICY,
        FINALS_K11_POLICY,
        V2_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )

    assert policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I11_POLICY)) == (
        FINALS_I11_POLICY
    )
    assert canonical_hash(FINALS_I11_POLICY) == (
        "0f7f5cd6f7b009d3e2d25bf049da7d91bc9675c595714555e365f16244f15559"
    )
    assert FINALS_H6_POLICY["tagging_wire_policy"] == FINALS_K11_POLICY["tagging_wire_policy"]
    assert canonical_hash(FINALS_H6_POLICY) != canonical_hash(FINALS_K11_POLICY)
    assert canonical_hash(FINALS_K11_POLICY) == (
        "01ed39928d5a5c35671a78bd6eedb8e42b68a7ea40a1b0fccf4e444b32047c02"
    )
    pin = canonical_hash(FINALS_H6_POLICY)
    assert policy_for(V2_PROFILE, pinned_hash=pin) == FINALS_H6_POLICY
    assert publication_policy_for(V2_PROFILE, pinned_hash=pin) == FINALS_H6_POLICY
    assert policy_for(V2_PROFILE) == V2_POLICY


def test_pdfium_subset_preserves_rotated_cropped_page_geometry():
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    page = writer.add_blank_page(width=700, height=500)
    page.cropbox = RectangleObject((20, 30, 650, 480))
    page.rotate(90)
    stream = io.BytesIO()
    writer.write(stream)
    original = PdfReader(io.BytesIO(stream.getvalue())).pages[1]
    subset = h6_local_pages.subset(stream.getvalue(), (2,))
    restored = PdfReader(io.BytesIO(subset), strict=True).pages[0]
    assert restored.mediabox == original.mediabox
    assert restored.cropbox == original.cropbox
    assert restored.rotation == original.rotation
    with pytest.raises(ValueError, match="PAGE_SELECTION_INVALID"):
        h6_local_pages.subset(stream.getvalue(), (0,))


def test_real_h6_parser_replays_original_page_mapping(tmp_path):
    source = document()
    profile = ParserProfile(
        str(uuid4()),
        physical_pages=(1, 2, 3),
        java_executable=JAVA,
        timeout_seconds=60,
        local_resource_policy="selected-pdf-h6-v1",
        failure_policy="partial-v3",
        table_structure_repair="odl_header_v2",
    )
    parser = OpenDataLoaderParser(tmp_path)
    graph = parser.parse(source, profile, tenant_id=source.tenant_id)
    assert {b.page_num for b in graph.blocks} == {1, 2}
    assert parser.load_verified(source, profile, tenant_id=source.tenant_id) == graph
    with pytest.raises(ParseFailure, match="NOT_FOUND"):
        parser.load_verified(source, profile, tenant_id=FOREIGN)
    path = tmp_path / source.tenant_id / source.document_version_id / profile.parse_manifest_id
    manifest = json.loads((path / "manifest.json").read_text())
    values = {p.name: json.loads(p.read_text()) for p in path.glob("*.json")}
    receipt = deepcopy(values["h6-local.json"])
    receipt["batches"][0]["pages"] = [1, 2]
    with pytest.raises(ValueError, match="H6_LOCAL_GEOMETRY_INVALID"):
        h6_local_pages.validate(receipt, values, manifest["artifacts"], source, (1, 2, 3))


def test_batch_memory_failure_bisects_and_only_bad_page_is_unreadable(tmp_path):
    source = document()
    (tmp_path / "source.pdf").write_bytes(source.content)
    (tmp_path / "request.json").write_text(json.dumps(dict(selected=[1, 2, 3])))
    profile = SimpleNamespace(timeout_seconds=20, max_output_bytes=100000)
    # Use a dataclass profile so each child gets a distinct remaining deadline.
    profile = ParserProfile(str(uuid4()), timeout_seconds=20, max_output_bytes=100000)
    calls = []

    def child(command, work, env, config):
        request = json.loads((work / "request.json").read_text())
        pages = request["selected"]
        calls.append(pages)
        assert 0 < config.timeout_seconds <= 20
        if len(pages) > 1 or pages == [2]:
            raise ParseFailure("PARSER_MEMORY_LIMIT")
        (work / "source.json").write_text(
            json.dumps(
                {
                    "number of pages": 3,
                    "kids": [
                        {
                            "id": "1",
                            "page number": pages[0],
                            "type": "paragraph",
                            "content": "candidate",
                        }
                    ],
                }
            )
        )
        (work / "auxiliary.json").write_text('{"kids":[]}')
        (work / "geometry.json").write_text(json.dumps({str(p): {} for p in pages}))
        (work / "h6-selected.pdf").write_bytes(b"fixture")
        (work / "source.md").write_text("candidate")

    (tmp_path / "request.json").write_text(json.dumps(dict(selected=[1, 2, 3], profile={})))
    h6_local_pages.execute(["child", str(tmp_path)], tmp_path, {}, profile, child)
    receipt = json.loads((tmp_path / "h6-local.json").read_text())
    assert h6_local_pages.failures(receipt) == [dict(pages=[2], error_code="PARSER_MEMORY_LIMIT")]
    raw = json.loads((tmp_path / "source.json").read_text())
    assert [n["page number"] for n in raw["kids"]] == [1, 3]
    assert len({n["id"] for n in raw["kids"]}) == 2
    assert calls == [[1, 2, 3], [1], [2, 3], [2], [3]]


def test_auxiliary_eof_preserves_successful_primary_candidates(tmp_path):
    source = document()
    (tmp_path / "source.pdf").write_bytes(source.content)
    (tmp_path / "request.json").write_text(json.dumps(dict(selected=[1], profile={})))
    profile = ParserProfile(str(uuid4()), timeout_seconds=20)

    def child(command, work, env, config):
        (work / "source.json").write_text(
            json.dumps(
                {
                    "number of pages": 3,
                    "kids": [
                        {
                            "id": "1",
                            "page number": 1,
                            "type": "paragraph",
                            "content": "primary candidate",
                        }
                    ],
                }
            )
        )
        (work / "geometry.json").write_text('{"1":{}}')
        (work / "h6-selected.pdf").write_bytes(b"fixture")
        (work / "source.md").write_text("primary candidate")
        raise ParseFailure("PARSER_NATIVE_TEXT_UNREADABLE")

    h6_local_pages.execute(["child", str(tmp_path)], tmp_path, {}, profile, child)
    receipt = json.loads((tmp_path / "h6-local.json").read_text())
    assert receipt["batches"][0]["status"] == "parsed"
    assert h6_local_pages.failures(receipt) == [
        dict(pages=[1], error_code="PARSER_NATIVE_TEXT_UNREADABLE")
    ]
    assert (
        json.loads((tmp_path / "source.json").read_text())["kids"][0]["content"]
        == "primary candidate"
    )


def test_h6_cli_pins_source_and_failure_readers():
    from proofops.adapters.local import upstage_ocr_profile_v14 as h6
    from proofops.adapters.local.claim_source_policies import publication_reader
    from proofops.application.analysis_profile import (
        FINALS_H6_POLICY,
        V2_PROFILE,
        apply_pilot_profile,
    )

    args = SimpleNamespace(
        analysis_profile=V2_PROFILE, analysis_policy_sha256=canonical_hash(FINALS_H6_POLICY)
    )
    apply_pilot_profile(args)
    assert args.parser_local_resource_policy == "selected-pdf-h6-v1"
    assert args.parser_failure_policy == "partial-v3"
    assert args.claim_source_profile == h6.PROFILE
    assert publication_reader(h6.claim_source_policy()) is h6


def test_render_limit_holds_only_the_oversized_page_without_dispatch():
    from proofops.adapters.local.upstage_ocr_profile_v14 import _page_hold

    sent = []

    def read(page, box):
        if page.page_number == 2:
            raise ValueError("OCR_RENDER_LIMIT")
        sent.append(page.page_number)
        return dict(status="read", text="unchanged")

    safe = _page_hold(read)
    assert safe(SimpleNamespace(page_number=2), ()) == dict(
        status="unresolved", reason="render_limit"
    )
    assert safe(SimpleNamespace(page_number=1), ())["text"] == "unchanged"
    assert sent == [1]
    with pytest.raises(ValueError, match="SOURCE_INTEGRITY_MISMATCH"):
        _page_hold(lambda *a: (_ for _ in ()).throw(ValueError("SOURCE_INTEGRITY_MISMATCH")))(None)


def test_new_source_reader_publishes_and_replays_without_paid_retry(tmp_path):
    from proofops.adapters.local import upstage_ocr_profile_v14 as h6

    calls = []
    db = store(tmp_path, lambda png: (calls.append(1) or response(), "fixture"))
    source, graph, ref = inputs()
    reader = h6.Reader(db, run_id="h6-fixture")
    receipt = reader.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    assert receipt["policy"] == h6.claim_source_policy()
    db.transport = lambda *a: pytest.fail("offline replay dispatched OCR")
    assert (
        reader.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=TENANT) == receipt
    )
    with pytest.raises(ValueError):
        reader.attest_claim_spans(graph, source, (ref,), tenant_id=FOREIGN)
    forged = deepcopy(receipt)
    forged["records"][0]["status"] = (
        "verified" if receipt["records"][0]["status"] != "verified" else "unresolved"
    )
    with pytest.raises(ValueError):
        reader.recompute_claim_receipt(forged, graph, source, (ref,), tenant_id=TENANT)


def test_failed_original_native_reader_stays_unresolved(tmp_path, monkeypatch):
    from pdfplumber.utils.exceptions import PdfminerException
    from proofops.adapters.local import upstage_ocr_profile_v14 as h6

    source, graph, ref = inputs()
    db = store(tmp_path, lambda *a: pytest.fail("unreadable source dispatched OCR"))
    reader = h6.Reader(db, run_id="h6-unreadable")
    modules, seen = reader._modules(graph, source, TENANT)

    def unreadable(*args, **kwargs):
        raise PdfminerException("Unexpected EOF")

    monkeypatch.setattr(modules["source_verification"], "attest_native_sources", unreadable)
    monkeypatch.setattr(reader, "_modules", lambda *a, **k: (modules, seen))
    receipt = reader.attest_native_sources(graph, source, tenant_id=TENANT)
    assert {r["status"] for r in receipt["records"]} == {"unresolved"}
    assert reader.replay_native_sources(receipt, graph, source, tenant_id=TENANT) == graph


def test_usd0_denied_provider_preserves_local_candidates(tmp_path):
    class NoPaid:
        calls = 0

        def parse_async(self, *args, **kwargs):
            self.calls += 1
            raise ValueError("BUDGET_EXHAUSTED")

    source = document()
    probe = NoPaid()
    profile = ParserProfile(
        str(uuid4()),
        physical_pages=(1, 2, 3),
        claim_physical_pages=(1,),
        java_executable=JAVA,
        timeout_seconds=60,
        parser_mode="mixed-v1",
        failure_policy="partial-v3",
        local_resource_policy="selected-pdf-h6-v1",
    )
    parser = OpenDataLoaderParser(tmp_path, upstage_probe=probe)
    graph = parser.parse(source, profile, tenant_id=source.tenant_id)
    assert graph.blocks
    assert any(
        i.kind == "parser_batch_failed" and i.reason == "BUDGET_EXHAUSTED" for i in graph.issues
    )
    assert parser.load_verified(source, profile, tenant_id=source.tenant_id) == graph
    assert probe.calls == 1


@pytest.mark.parametrize(
    "code",
    [
        "H5_CUMULATIVE_BUDGET_EXHAUSTED",
        "H5_BUDGET_EXHAUSTED",
        "R108_FINALS_CUMULATIVE_BUDGET_EXHAUSTED",
    ],
)
def test_shared_money_fence_preserves_denial_without_dispatch_or_reservation(tmp_path, code):
    import sqlite3
    from decimal import Decimal

    from scripts.finals_demo import FinalsBudget

    ledger = tmp_path / "probe.sqlite3"
    with sqlite3.connect(ledger) as db:
        db.execute("CREATE TABLE probe_calls (request_id TEXT, committed TEXT, receipt TEXT)")
    before = ledger.read_bytes()
    fence = FinalsBudget(tmp_path / "spend.json", {"openai": ledger}, tmp_path / "events.jsonl")

    def denied(bound):
        assert bound == Decimal("0.02")
        raise ValueError(code)

    fence.reserve = denied
    call = fence.guarded(
        lambda *a, **k: pytest.fail("denied dispatch reached provider"),
        "openai",
        lambda *a: Decimal("0.02"),
    )
    with pytest.raises(ValueError, match="^BUDGET_EXHAUSTED$"):
        call(SimpleNamespace(ledger=ledger), request_id="denied-h6")
    assert ledger.read_bytes() == before
    assert not (tmp_path / "spend.json").exists()
