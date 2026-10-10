"""Azure transport faults, Korean spans, geometry, budget and immutable replay."""

import copy
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from proofops.adapters.parsing.azure_client import (
    API_VERSION,
    MODEL,
    AzureFailure,
    AzureLayoutClient,
)
from proofops.adapters.parsing.azure_layout import AzureLayoutParser, convert_result
from proofops.adapters.parsing.opendataloader import ParseFailure
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact, fuse_candidates
from proofops.domain.documents import PageGeometry
from pypdf import PdfWriter

ENDPOINT = "https://example.cognitiveservices.azure.com"
OPERATION = (
    ENDPOINT
    + "/documentintelligence/documentModels/prebuilt-layout/analyzeResults/test?api-version="
    + API_VERSION
)


def fixture():
    writer, output = PdfWriter(), BytesIO()
    writer.add_blank_page(width=612, height=792)
    writer.write(output)
    content = output.getvalue()
    source = SourceArtifact(
        str(uuid4()), str(uuid4()), str(uuid4()), sha256(content).hexdigest(), "v1", content, True
    )
    profile = ParserProfile(
        str(uuid4()), physical_pages=(1,), parser_mode="azure", table_auxiliary=False
    )
    text = "2024년 감축량 30,925 tCO₂e"
    result = {
        "apiVersion": API_VERSION,
        "modelId": MODEL,
        "stringIndexType": "unicodeCodePoint",
        "content": text,
        "pages": [{"pageNumber": 1, "width": 8.5, "height": 11, "unit": "inch"}],
        "paragraphs": [
            {
                "content": text,
                "spans": [{"offset": 0, "length": len(text)}],
                "boundingRegions": [{"pageNumber": 1, "polygon": [1, 1, 4, 1, 4, 2, 1, 2]}],
            }
        ],
    }
    geometry = {1: asdict(PageGeometry(612, 792, 0, (0, 0, 612, 792)))}
    return source, profile, result, geometry


def client(tmp_path, handler, **kwargs):
    return AzureLayoutClient(
        ENDPOINT,
        "test-key",
        tmp_path / "requests.sqlite3",
        transport=httpx.MockTransport(handler),
        poll_interval=0,
        **kwargs,
    )


def test_request_unicode_cache_and_budget(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            assert request.url.params["stringIndexType"] == "unicodeCodePoint"
            return httpx.Response(202, headers={"operation-location": OPERATION})
        return httpx.Response(
            200, json={"status": "succeeded", "analyzeResult": {"content": "한글"}}
        )

    api = client(tmp_path, handler, max_pages=1)
    first, _ = api.analyze(b"pdf", (1,), scope="tenant")
    second, receipt = api.analyze(b"pdf", (1,), scope="tenant")
    assert first == second and receipt["cache_hit"] and calls == ["POST", "GET"]
    with pytest.raises(AzureFailure, match="BUDGET"):
        api.analyze(b"other", (1,), scope="tenant")


def test_lost_post_is_never_automatically_resubmitted(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.method)
        raise httpx.ReadTimeout("possibly billed")

    api = client(tmp_path, handler)
    with pytest.raises(AzureFailure, match="UNCERTAIN"):
        api.analyze(b"pdf", (1,), scope="tenant")
    with pytest.raises(AzureFailure, match="REQUIRES_REVIEW"):
        api.analyze(b"pdf", (1,), scope="tenant")
    assert calls == ["POST"]
    assert api.summary()["uncertain"]["pages"] == 1


def test_lost_poll_resumes_without_resubmission(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(202, headers={"operation-location": OPERATION})
        if calls == ["POST", "GET"]:
            raise httpx.ReadTimeout("retry GET")
        return httpx.Response(200, json={"status": "succeeded", "analyzeResult": {}})

    api = client(tmp_path, handler)
    with pytest.raises(AzureFailure, match="RESUMABLE"):
        api.analyze(b"pdf", (1,), scope="tenant")
    _, receipt = api.analyze(b"pdf", (1,), scope="tenant")
    assert calls == ["POST", "GET", "GET"] and receipt["resumed"]


def test_reject_cross_origin_operation_before_sending_key(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(202, headers={"operation-location": "https://evil.test/key"})

    with pytest.raises(AzureFailure, match="URL_INVALID"):
        client(tmp_path, handler).analyze(b"pdf", (1,), scope="tenant")
    assert calls == ["POST"]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_submit_errors_have_no_secret_or_automatic_retry(tmp_path, status):
    api = client(tmp_path, lambda req: httpx.Response(status, text="secret-key-and-document"))
    with pytest.raises(AzureFailure, match=f"HTTP_{status}") as error:
        api.analyze(b"pdf", (1,), scope="tenant")
    assert "secret" not in str(error.value)
    with pytest.raises(AzureFailure, match="REQUIRES_REVIEW"):
        api.analyze(b"pdf", (1,), scope="tenant")


def test_korean_coordinates_located_but_not_approved():
    source, profile, result, geometry = fixture()
    batch = convert_result(result, source, profile, geometry)
    graph = fuse_candidates((batch,), tenant_id=source.tenant_id)
    assert graph.blocks[0].bbox == (72, 72, 288, 144)
    assert graph.blocks[0].quality == "unverified"
    assert graph.blocks[0].raw_text == result["content"]


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda r: r.update(stringIndexType="utf16CodeUnit"), "INDEX"),
        (lambda r: r["pages"][0].update(pageNumber=2), "COVERAGE"),
        (lambda r: r["paragraphs"][0].update(content="2024년 감축량 30,926 tCO₂e"), "SPAN"),
        (lambda r: r["pages"][0].update(width=5), "GEOMETRY"),
    ],
)
def test_wrong_spans_pages_dimensions_fail_closed(mutation, code):
    source, profile, result, geometry = fixture()
    mutation(result)
    with pytest.raises(ParseFailure, match=code):
        convert_result(result, source, profile, geometry)


def test_rotation_and_crop_roundtrip():
    source, profile, result, _ = fixture()
    result["pages"][0].update(width=11, height=8.5)
    geometry = {1: asdict(PageGeometry(792, 612, 90, (10, 20, 622, 812)))}
    candidate = convert_result(result, source, profile, geometry).blocks[0]
    assert candidate.bbox == pytest.approx((72, 72, 288, 144))


def test_multipage_paragraph_retained_without_false_page_box():
    source, profile, result, geometry = fixture()
    result["pages"].append(dict(result["pages"][0], pageNumber=2))
    geometry[2] = geometry[1]
    profile = replace(profile, physical_pages=(1, 2))
    result["paragraphs"][0]["boundingRegions"].append(
        {"pageNumber": 2, "polygon": [1, 1, 2, 1, 2, 2, 1, 2]}
    )
    block = convert_result(result, source, profile, geometry).blocks[0]
    assert block.bbox is None


def test_actual_windows_subprocess_and_tamper_replay(tmp_path):
    source, profile, result, _ = fixture()

    class Probe:
        def analyze(self, *args, **kwargs):
            return copy.deepcopy(result), {"synthetic_transport": True}

    adapter = AzureLayoutParser(tmp_path, client=Probe())
    graph = adapter.parse(source, profile, tenant_id=source.tenant_id)
    directory = adapter._directory(source, profile)
    digest = sha256((directory / "manifest.json").read_bytes()).hexdigest()
    assert (
        adapter.load_verified(
            source, profile, tenant_id=source.tenant_id, manifest_sha256=digest
        ).to_dict()
        == graph.to_dict()
    )
    (directory / "response.json").write_text("{}")
    with pytest.raises(ParseFailure, match="INTEGRITY"):
        adapter.load_verified(source, profile, tenant_id=source.tenant_id, manifest_sha256=digest)


def test_azure_through_http_run_worker_commit_and_replay(tmp_path, monkeypatch):
    from io import StringIO

    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
    from proofops.application.telemetry import Telemetry
    from proofops_worker.local_runner import LocalParserRunner

    from tests.integration import test_run_lifecycle as lifecycle

    source, profile, result, _ = fixture()
    monkeypatch.setattr(lifecycle, "pdf", lambda count: source.content)

    class Probe:
        def analyze(self, *args, **kwargs):
            return copy.deepcopy(result), {"synthetic_transport": True}

    monkeypatch.setattr(AzureLayoutClient, "from_environment", lambda path: Probe())
    service, body = lifecycle.setup(tmp_path)
    service.parser_profile_hash = profile.config_hash()
    service.parser_profile = profile.config_snapshot()
    http, _ = lifecycle.client(service)
    created = http.post("/v1/runs", json=body)
    assert created.status_code == 202, created.text
    run_id = created.json()["run_id"]
    runner = LocalParserRunner(
        service.store,
        service.uploads,
        OpenDataLoaderParser(tmp_path / "prepared"),
        profile=profile,
        telemetry=Telemetry(service="worker", env="test", stream=StringIO(), hash_key=b"x" * 32),
        clock=lambda: lifecycle.NOW,
    )
    assert runner.run_once(tenant_id=lifecycle.TENANT, run_id=run_id) == "committed"
    graph = runner.load_graph(tenant_id=lifecycle.TENANT, run_id=run_id)
    assert graph.blocks[0].raw_text == result["content"]
    assert graph.blocks[0].quality == "unverified"
    assert runner.run_once(tenant_id=lifecycle.TENANT, run_id=run_id) == "pending_downstream"


def test_table_header_spans_and_footnote_edges_preserved():
    source, profile, result, geometry = fixture()
    values = ["2024년", "30,925", "단위 tCO2e"]
    result["content"] = "\n".join(values)

    def item(text, offset):
        return {
            "content": text,
            "spans": [{"offset": offset, "length": len(text)}],
            "boundingRegions": [{"pageNumber": 1, "polygon": [1, 1, 4, 1, 4, 2, 1, 2]}],
        }

    header = dict(item(values[0], 0), rowIndex=0, columnIndex=0, kind="columnHeader")
    value = dict(item(values[1], len(values[0]) + 1), rowIndex=1, columnIndex=0)
    note = item(values[2], len(values[0]) + len(values[1]) + 2)
    result["paragraphs"] = []
    result["tables"] = [
        {
            "rowCount": 2,
            "columnCount": 1,
            "boundingRegions": header["boundingRegions"],
            "cells": [header, value],
            "footnotes": [note],
        }
    ]
    batch = convert_result(result, source, profile, geometry)
    cell = next(b for b in batch.blocks if b.source.raw_text == "30,925")
    assert cell.context == ("column_header: 2024년",)
    assert any(e.relation == "footnote_of" for e in batch.edges)
    result["tables"][0]["cells"].append(copy.deepcopy(value))
    with pytest.raises(ParseFailure, match="OVERLAP"):
        convert_result(result, source, profile, geometry)
