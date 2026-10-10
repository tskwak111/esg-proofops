from dataclasses import replace
from uuid import uuid4

import pytest
from proofops.adapters.parsing.docling_document import (
    OPTIONS,
    VERSION,
    DoclingParser,
    convert_pages,
)
from proofops.adapters.parsing.docling_validation import audit, guarded_graph, key, native_check
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure
from proofops.application.ingest.graph_fusion import ParserProfile
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_parsing import MANIFEST, TENANT, pdf, source


def fixture():
    item = source(pdf())
    profile = ParserProfile(MANIFEST, parser_mode="docling", table_auxiliary=False)
    cells = []
    chars = []
    for row, values in enumerate((("Year", "2024"), ("Revenue", "100"))):
        for col, text in enumerate(values):
            x, y = 10 + col * 100, 10 + row * 30
            cells.append(
                dict(
                    text=text,
                    bbox=dict(l=x, t=y, r=x + 80, b=y + 20, coord_origin="TOPLEFT"),
                    start_row_offset_idx=row,
                    end_row_offset_idx=row + 1,
                    start_col_offset_idx=col,
                    end_col_offset_idx=col + 1,
                    row_span=1,
                    col_span=1,
                )
            )
            chars.append(dict(text=text + " ", bbox=[x, 200 - y - 20, x + 80, 200 - y]))
    pages = {
        "1": dict(
            version=VERSION,
            options=OPTIONS,
            page=1,
            geometry=dict(width_pt=300, height_pt=200, rotation=0, crop_box=[0, 0, 300, 200]),
            chars=chars,
            document=dict(
                pages={"1": dict(size=dict(width=300, height=200))},
                tables=[
                    dict(
                        prov=[
                            dict(
                                page_no=1,
                                bbox=dict(l=10, t=190, r=190, b=130, coord_origin="BOTTOMLEFT"),
                            )
                        ],
                        data=dict(num_rows=2, num_cols=2, table_cells=cells),
                    )
                ],
                texts=[],
                pictures=[],
            ),
        )
    }
    local = convert_pages(pages, item, profile)
    run = str(uuid4())
    other = replace(
        local,
        parser_run_id=run,
        parser_name="upstage_async_standard",
        parser_family="upstage-document-parse",
        blocks=tuple(replace(b, source=replace(b.source, parser_run_id=run)) for b in local.blocks),
    )
    return item, profile, pages, local, other


def test_direct_coordinates_and_no_ocr_configuration():
    _, _, _, local, _ = fixture()
    assert local.blocks[-1].source.native_bbox == (110, 140, 190, 160)
    assert OPTIONS["do_ocr"] is False and OPTIONS["do_cell_matching"] is True
    assert local.parser_family == "docling"


def test_same_independent_rows_reach_diagnostic_consensus():
    item, _, pages, local, other = fixture()
    records = audit([local, other], pages)
    assert all(r["reason"] == "consensus" for r in records if "-c" in r["key"].split("/")[-1])
    graph = guarded_graph([local, other], records, tenant_id=item.tenant_id)
    assert all(b.quality == "unverified" for b in graph.blocks)


@pytest.mark.parametrize("replacement", ["999", "-100", "100%", "100.1"])
def test_numeric_values_signs_units_and_decimals_cannot_be_invented(replacement):
    item, _, pages, local, other = fixture()
    cell = other.blocks[-1]
    changed = replace(
        cell, source=replace(cell.source, raw_text=replacement, char_end=len(replacement))
    )
    other = replace(other, blocks=other.blocks[:-1] + (changed,))
    records = audit([local, other], pages)
    assert (
        next(r for r in records if r["key"] == key(changed))["reason"]
        == "numeric_not_in_native_region"
    )
    graph = guarded_graph([local, other], records, tenant_id=item.tenant_id)
    assert any(b.winner is None for b in graph.blocks if b.kind == "table_cell")
    assert all(not b.raw_text for b in graph.blocks if b.kind == "table")


def test_same_number_elsewhere_is_rejected():
    _, _, pages, local, _ = fixture()
    target = local.blocks[-1]
    pages["1"]["chars"][-1]["bbox"] = [210, 10, 250, 20]
    assert not native_check(target, pages["1"])


def test_wrong_year_and_swapped_rows_do_not_agree():
    _, _, pages, local, other = fixture()
    cells = list(other.blocks)
    cells[2] = replace(cells[2], source=replace(cells[2].source, raw_text="2023"))
    other = replace(other, blocks=tuple(cells))
    records = audit([local, other], pages)
    assert not any(r["reason"] == "consensus" for r in records)


def test_missing_crosscheck_and_overlapping_grid_fail_closed():
    item, _, pages, local, other = fixture()
    records = audit([local], pages, crosscheck=False)
    graph = guarded_graph([local], records, tenant_id=item.tenant_id)
    assert all(b.winner is None for b in graph.blocks if b.kind == "table_cell")
    local = replace(
        local,
        blocks=local.blocks[:-1] + (replace(local.blocks[-1], context=("table_grid_overlap",)),),
    )
    records = audit([local, other], pages)
    assert any(r["reason"] == "table_grid_overlap" for r in records)


def test_enhanced_is_same_family_and_can_resolve_local_disagreement():
    _, _, pages, local, standard = fixture()
    enhanced = replace(standard, parser_name="upstage_async_enhanced")
    records = audit([local, enhanced], pages)
    assert any(r["reason"] == "consensus" for r in records)
    assert enhanced.parser_family == standard.parser_family


def test_chart_values_require_review_even_if_native_numbers_exist():
    _, _, pages, local, other = fixture()
    figure = replace(local.blocks[-1], kind="figure", table_native_id=None)
    local = replace(local, blocks=local.blocks[:-1] + (figure,))
    records = audit([local, other], pages)
    assert (
        next(r for r in records if r["key"] == key(figure))["reason"]
        == "chart_requires_vision_review"
    )


def test_docling_family_cannot_be_counted_as_two_independent_parsers():
    _, _, pages, local, other = fixture()
    with pytest.raises(ValueError, match="INDEPENDENT_PARSER_FAMILY_REQUIRED"):
        audit([local, replace(other, parser_family="docling")], pages)


def test_no_text_layer_is_unreadable_not_evidence_absence():
    item, _, pages, local, other = fixture()
    pages["1"]["chars"] = []
    records = audit([local, other], pages)
    graph = guarded_graph([local, other], records, tenant_id=item.tenant_id, pages=pages)
    assert any(i.kind == "no_extractable_text" and i.state == "unreadable" for i in graph.issues)


def test_page_numbers_do_not_trigger_paid_enhancement():
    _, _, pages, local, _ = fixture()
    footer = replace(local.blocks[-1], kind="unknown", table_native_id=None)
    local = replace(local, blocks=(footer,), edges=())
    records = audit([local], pages)
    assert records[0]["reason"] == "not_numeric"


def test_budget_refusal_can_resume_without_unknown_post_lock(tmp_path):
    class Refused:
        def parse_async(self, *args, **kwargs):
            raise ValueError("BUDGET_EXHAUSTED")

    item, _, _, _, _ = fixture()
    parser = DoclingParser(tmp_path, upstage_probe=Refused())
    for _ in range(2):
        with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
            parser._provider(item, (1,), "standard")
    assert not list(tmp_path.rglob("*.pending"))


def test_profiles_preserve_legacy_hash_and_disallow_odl_with_docling():
    assert "docling_python" not in ParserProfile(MANIFEST).config_snapshot()
    with pytest.raises(ValueError):
        ParserProfile(MANIFEST, parser_mode="docling")
    with pytest.raises(ValueError):
        ParserProfile(MANIFEST, docling_python="python")


def test_missing_provider_does_not_silently_run_local_only(tmp_path):
    item, profile, _, _, _ = fixture()
    with pytest.raises(ParseFailure, match="UPSTAGE_RUNTIME_REQUIRED"):
        OpenDataLoaderParser(tmp_path).parse(item, profile, tenant_id=TENANT)


def test_unknown_provider_request_is_not_resubmitted(tmp_path):
    class Broken:
        calls = 0

        def parse_async(self, *args, **kwargs):
            self.calls += 1
            raise ValueError("UPSTAGE_REQUEST_FAILED")

    item, _, _, _, _ = fixture()
    probe = Broken()
    parser = DoclingParser(tmp_path, upstage_probe=probe)
    with pytest.raises(ValueError, match="UPSTAGE_REQUEST_FAILED"):
        parser._provider(item, (1,), "standard")
    with pytest.raises(ParseFailure, match="PENDING_REQUEST"):
        parser._provider(item, (1,), "standard")
    assert probe.calls == 1


def test_pipeline_enhanced_routing_and_replay(tmp_path, monkeypatch):
    from proofops.adapters.parsing import docling_document as module

    item, profile, pages, local, standard = fixture()
    calls = []
    parser = DoclingParser(tmp_path, upstage_probe=object())
    monkeypatch.setattr(parser, "_local_page", lambda *args: pages["1"])
    monkeypatch.setattr(
        module, "verify_quarantined_pdf", lambda *a, **k: type("V", (), {"page_count": 1})()
    )
    raw = [{"dummy": True}]
    monkeypatch.setattr(
        parser,
        "_provider",
        lambda s, p, m: (
            calls.append((p, m)) or dict(raw_batches=raw, response_sha256=canonical_hash(raw))
        ),
    )

    def candidate(*args, mode, **kwargs):
        run = str(uuid4())
        batch = replace(
            standard,
            parser_name="upstage_async_" + mode,
            parser_run_id=run,
            blocks=tuple(
                replace(b, source=replace(b.source, parser_run_id=run)) for b in standard.blocks
            ),
        )
        if mode == "standard":
            cell = batch.blocks[-1]
            batch = replace(
                batch,
                blocks=batch.blocks[:-1]
                + (replace(cell, source=replace(cell.source, raw_text="999")),),
            )
        return batch, {}

    monkeypatch.setattr("proofops.adapters.parsing.upstage_document.candidate_batch", candidate)
    graph = parser.parse(item, profile, tenant_id=TENANT)
    assert calls == [((1,), "standard"), ((1,), "enhanced")]
    assert parser.load_verified(item, profile, tenant_id=TENANT) == graph
    directory = parser._directory(item, profile)
    (directory / "audit.json").write_text("[]")
    with pytest.raises(ParseFailure, match="INTEGRITY"):
        parser.load_verified(item, profile, tenant_id=TENANT)


def test_worker_publishes_docling_quality_and_reopens_without_provider(tmp_path, monkeypatch):
    import copy

    from proofops.adapters.parsing import docling_document as module
    from proofops.application.ports.jobs import JobMessage
    from proofops_worker.local_runner import LocalParserRunner

    from tests.integration import test_run_lifecycle as lifecycle

    _, profile, fixture_pages, _, _ = fixture()
    service, body = lifecycle.setup(tmp_path)
    service.parser_profile_hash = profile.config_hash()
    service.parser_profile = profile.config_snapshot()
    http, _ = lifecycle.client(service)
    response = http.post("/v1/runs", json=body)
    assert response.status_code == 202
    run_id = response.json()["run_id"]

    def local_page(self, source, profile, number):
        page = copy.deepcopy(fixture_pages["1"])
        page["page"] = number
        page["document"]["pages"] = {str(number): page["document"]["pages"]["1"]}
        page["document"]["tables"][0]["prov"][0]["page_no"] = number
        return page

    def provider(self, source, pages, mode):
        raw = [dict(pages=list(pages))]
        return dict(raw_batches=raw, response_sha256=canonical_hash(raw))

    def candidates(source, profile, selected, raw, *, mode, config_hash):
        pages = {str(p): local_page(None, source, profile, p) for p in selected}
        batch = module.convert_pages(pages, source, profile)
        run = str(uuid4())
        return replace(
            batch,
            parser_name="upstage_async_" + mode,
            parser_family="upstage-document-parse",
            parser_run_id=run,
            blocks=tuple(
                replace(b, source=replace(b.source, parser_run_id=run)) for b in batch.blocks
            ),
        ), {}

    monkeypatch.setattr(module.DoclingParser, "_local_page", local_page)
    monkeypatch.setattr(module.DoclingParser, "_provider", provider)
    monkeypatch.setattr("proofops.adapters.parsing.upstage_document.candidate_batch", candidates)
    parser = OpenDataLoaderParser(tmp_path / "prepared", upstage_probe=object())
    from io import StringIO

    from proofops.application.telemetry import Telemetry

    runner = LocalParserRunner(
        service.store,
        service.uploads,
        parser,
        profile=profile,
        telemetry=Telemetry(service="worker", env="test", stream=StringIO(), hash_key=b"x" * 32),
        clock=lambda: lifecycle.NOW,
    )
    event = service.store.jobs.pending_outbox(TENANT, run_id, now=lifecycle.NOW)[0]
    message = JobMessage(**event["message"])
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    assert service.store.jobs.read_checkpoint(message)
    graph = runner.load_graph(tenant_id=TENANT, run_id=run_id)
    assert any(i.kind == "parser_consensus" for i in graph.issues)
    assert not any(b.parser_name == "opendataloader" for b in graph.candidates)
    parser.upstage_probe = None
    assert runner.load_graph(tenant_id=TENANT, run_id=run_id) == graph
    service.uploads.close()
    service.uploads.registry.close()
