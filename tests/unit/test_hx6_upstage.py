from dataclasses import replace
from types import SimpleNamespace

import pytest
from proofops.adapters.parsing import hx6_upstage as hx6
from proofops.domain.provenance import canonical_hash


def test_native_claims_survive_provider_outage_without_source_promotion(monkeypatch):
    from tests.integration.test_claim_source_v3 import synthetic
    from tests.unit.test_hx4_parse import profile

    pdf, graph, _ = synthetic("Environmental policy reduces greenhouse gas emissions 10%")
    candidate = graph.candidates[0]
    source = SimpleNamespace(content=pdf, sha256=graph.source_sha256)
    p = replace(profile(), claim_physical_pages=(1,), parser_mode="mixed-v1")
    batches, routing, output = hx6.recover(
        source,
        p,
        (1,),
        (candidate,),
        lambda *a: pytest.fail("readable native page must not incur a paid call"),
        config_hash="test",
    )
    assert batches[0].blocks == candidate.blocks
    assert routing["local_pages"] == [1]
    assert output["failed_batches"] == []
    assert all(not hasattr(b, "quality") for b in batches[0].blocks)


@pytest.mark.parametrize(
    "code,expected",
    [
        ("UPSTAGE_HTTP_503", 2),
        ("UPSTAGE_HTTP_401", 1),
        ("UPSTAGE_REQUEST_TIMEOUT", 1),
        ("BUDGET_EXHAUSTED", 1),
    ],
)
def test_single_page_failures_have_bounded_transient_only_retry(monkeypatch, code, expected):
    monkeypatch.setattr(hx6, "native_pages", lambda *a: [])
    monkeypatch.setattr(hx6, "sleep", lambda *a: None)
    calls = []

    def call(pages, mode):
        calls.append((pages, mode))
        raise ValueError(code)

    p = SimpleNamespace(claim_physical_pages=(2, 3), mixed_ocr_max_pages=0)
    _, routing, output = hx6.recover(None, p, (2, 3), (), call, config_hash="test")
    assert all(len(pages) == 1 for pages, _ in calls)
    assert len(calls) == (expected if code in hx6.STOP else expected * 2)
    assert {p for f in output["failed_batches"] for p in f["pages"]} == {2, 3}
    assert routing["unreadable_pages"] == [2, 3]


def test_new_pin_preserves_hx4_and_default():
    from proofops.application import analysis_profile as p

    assert p.policy_for(p.V2_PROFILE) == p.FINALS_I15_POLICY
    assert (
        p.policy_for(p.V2_PROFILE, pinned_hash=canonical_hash(p.FINALS_HX6_POLICY))
        == p.FINALS_HX6_POLICY
    )
    assert (
        p.publication_policy_for(p.V2_PROFILE, pinned_hash=canonical_hash(p.FINALS_HX6_POLICY))
        == p.FINALS_HX6_POLICY
    )
    assert (
        canonical_hash(p.FINALS_HX4_COMPLETE_POLICY)
        == "57cbf6c9857ff07ed24bcbd63eedbfe4a12dabde5eb514cb8228b992049a4eac"
    )


def test_transport_audit_does_not_expose_exception_message(tmp_path, monkeypatch):
    from proofops.adapters.local.upstage_parse import UpstageParseProbe

    from tests.integration.test_upstage_parse import make_pdf

    client = UpstageParseProbe("private-secret", tmp_path / "budget.sqlite3")
    monkeypatch.setattr(
        client,
        "_post_parse",
        lambda *a: (_ for _ in ()).throw(TimeoutError("private-secret signed-url document-text")),
    )
    with pytest.raises(ValueError, match="UPSTAGE_REQUEST_TIMEOUT"):
        client.parse_async(make_pdf(1), request_id="timeout")
    audit = next((tmp_path / "parse-dispatch").glob("*.json")).read_text()
    assert "private-secret" not in audit and "signed-url" not in audit
    assert '"exception_type": "TimeoutError"' in audit
    assert '"request_bytes"' in audit


def test_complete_pin_keeps_the_existing_hx6_policy():
    from proofops.application import analysis_profile as p

    assert canonical_hash(p.FINALS_HX6_POLICY) == (
        "c3270adcfda417650089a988cdd83d8958fa99ace9b9873b36e560f09656e754"
    )
    assert (
        p.policy_for(p.V2_PROFILE, pinned_hash=canonical_hash(p.FINALS_HX6_COMPLETE_POLICY))
        == p.FINALS_HX6_COMPLETE_POLICY
    )


def test_display_eof_keeps_raw_quote_and_never_promotes_source(monkeypatch):
    from copy import deepcopy
    from dataclasses import asdict

    from pdfplumber.utils.exceptions import PdfminerException
    from proofops.adapters.local import glyph_display_text as display

    from tests.integration.test_claim_source_v3 import synthetic

    pdf, graph, ref = synthetic("Environmental policy reduces greenhouse gas emissions")
    original = deepcopy(graph)
    monkeypatch.setattr(
        display.pdfplumber,
        "open",
        lambda *a, **k: (_ for _ in ()).throw(PdfminerException("Unexpected EOF")),
    )
    pin = display.GlyphDisplayCatalog(graph, pdf).pin(asdict(ref))
    assert pin["text"] == ref.quote and pin["deleted_offsets"] == []
    assert graph == original


def test_parser_native_recovery_and_checkpoint_replay(tmp_path):
    from hashlib import sha256
    from uuid import uuid4

    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
    from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact

    from deploy.public.offline_fixture import source_pdf

    pdf = source_pdf()
    source = SourceArtifact(
        str(uuid4()), str(uuid4()), str(uuid4()), sha256(pdf).hexdigest(), "v1", pdf
    )
    profile = ParserProfile(
        str(uuid4()),
        physical_pages=(1, 2),
        claim_physical_pages=(1, 2),
        java_executable="/opt/homebrew/opt/openjdk@21/bin/java",
        parser_mode="mixed-v1",
        local_resource_policy="selected-pdf-h6-v1",
        failure_policy="partial-v5",
        timeout_seconds=120,
    )

    class Offline:
        def parse_async(self, *a, **kw):
            pytest.fail("Readable native claims must survive without a provider request")

    parser = OpenDataLoaderParser(tmp_path / "parser", upstage_probe=Offline())
    graph = parser.parse(source, profile, tenant_id=source.tenant_id)
    assert {b.page_num for b in graph.blocks if b.sources[0].raw_text} == {1, 2}
    assert all(b.quality != "verified" for b in graph.blocks)
    assert (
        parser.load_verified(source, profile, tenant_id=source.tenant_id).to_dict()
        == graph.to_dict()
    )


def test_download_timeout_retries_get_without_a_new_paid_post(tmp_path, monkeypatch):
    from proofops.adapters.local.upstage_parse import UpstageParseProbe

    probe = UpstageParseProbe("test-secret", tmp_path / "ledger.sqlite3")
    calls = []

    def download(url):
        calls.append(url)
        if len(calls) < 3:
            raise TimeoutError("private signed url")
        return {"elements": []}

    monkeypatch.setattr(probe, "_async_download", download)
    monkeypatch.setattr("proofops.adapters.local.upstage_parse.sleep", lambda *a: None)
    assert probe._download_batches([{"download_url": "private"}]) == [{"elements": []}]
    assert len(calls) == 3
    assert probe.summary()["calls"] == 0


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_hosted_preparation_uses_same_recovery_pin(tmp_path, monkeypatch, platform):
    import json
    import sqlite3
    import sys

    from proofops.application.analysis_profile import FINALS_HX6_POLICY
    from proofops_api import hosted_analysis
    from pypdf import PdfWriter

    from evaluation import local_upstage_pilot as pilot
    from evaluation.hosted_r108 import prepare_argv

    monkeypatch.setattr(hosted_analysis.sys, "platform", platform)

    pdf = tmp_path / "source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(600, 400)
    writer.write(pdf)
    pin = canonical_hash(FINALS_HX6_POLICY)
    argv = prepare_argv(
        pdf,
        tmp_path / "state",
        "11111111-1111-4111-8111-111111111111",
        dict(
            analysis_profile="finals-unattended-v2",
            analysis_policy_sha256=pin,
            report_year=2024,
            period_start="2024-01-01",
            period_end="2024-12-31",
        ),
        options=dict(pages=[1], claim_pages=[1], analysis_profile_sha256=pin),
    )
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    with sqlite3.connect(tmp_path / "state/state.sqlite3") as db:
        snapshot = json.loads(db.execute("select payload from run_snapshots").fetchone()[0])
    assert snapshot["parser_profile"]["failure_policy"] == "partial-v5"
    assert snapshot["claim_source_policy"]["profile"] == "upstage-ocr-page-v17"


def test_provider_page_failure_keeps_other_page_and_replays(tmp_path, monkeypatch):
    import io
    from hashlib import sha256
    from uuid import uuid4

    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
    from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact
    from pypdf import PdfReader

    from deploy.public.offline_fixture import fake_parse, source_pdf

    monkeypatch.setattr(hx6, "native_pages", lambda *a: [])
    pdf = source_pdf()
    source = SourceArtifact(
        str(uuid4()), str(uuid4()), str(uuid4()), sha256(pdf).hexdigest(), "v1", pdf
    )
    profile = ParserProfile(
        str(uuid4()),
        physical_pages=(1, 2),
        claim_physical_pages=(1, 2),
        java_executable="/opt/homebrew/opt/openjdk@21/bin/java",
        parser_mode="mixed-v1",
        local_resource_policy="selected-pdf-h6-v1",
        failure_policy="partial-v5",
    )

    class Provider:
        calls = 0

        def parse_async(self, content, **kwargs):
            self.calls += 1
            assert len(PdfReader(io.BytesIO(content)).pages) == 1
            if self.calls == 1:
                raise ValueError("UPSTAGE_HTTP_400")
            raw = [fake_parse(content, "standard")]
            return dict(raw_batches=raw, response_sha256=canonical_hash(raw))

    provider = Provider()
    parser = OpenDataLoaderParser(tmp_path / "parser", upstage_probe=provider)
    graph = parser.parse(source, profile, tenant_id=source.tenant_id)
    assert provider.calls == 2
    assert {b.page_num for b in graph.blocks} == {2}
    assert {i.page_num for i in graph.issues if i.kind == "parser_batch_failed"} == {1}
    assert all(b.quality != "verified" for b in graph.blocks)
    assert (
        parser.load_verified(source, profile, tenant_id=source.tenant_id).to_dict()
        == graph.to_dict()
    )
