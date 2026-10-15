"""Offline regressions for Sprint5 execution blockers; no paid provider calls."""

import json
import sys
from types import SimpleNamespace

import pytest
from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure, _child
from proofops.application.claims import ExtractionOutputError
from proofops.application.ingest.graph_fusion import ParserProfile
from proofops_agent.upstage_extraction import GraphBoundExtractor
from proofops_worker.live_tagging import _local_stop_code


def test_missing_display_source_is_unresolved_without_dispatch():
    def dispatch(*args, **kwargs):
        pytest.fail("missing original source must never reach model dispatch")

    bound = GraphBoundExtractor(
        SimpleNamespace(_display_text_profile="glyph-joined-display-v1", extract=dispatch),
        SimpleNamespace(source_sha256="a" * 64),
        None,
    )
    with pytest.raises(ExtractionOutputError, match="DISPLAY_SOURCE_UNAVAILABLE"):
        bound.extract({})


def test_catalog_missing_source_raises_controlled_code():
    with pytest.raises(ValueError, match="DISPLAY_SOURCE_UNAVAILABLE"):
        GlyphDisplayCatalog(SimpleNamespace(source_sha256="a" * 64), None)


def test_batch_continuation_passes_original_to_graph_bound_extractor(tmp_path, monkeypatch):
    from proofops_worker import extract_runner

    from tests.acceptance.test_upload import TENANT
    from tests.integration.test_extract_batch_continuation import setup_run

    _, run_id, runner, _, _, graph = setup_run(tmp_path, monkeypatch, paragraphs=4, limit=2)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    runner.extractor._display_text_profile = "glyph-joined-display-v1"
    expected = runner.uploads.read_original(TENANT, graph.document_version_id)
    received = []

    def bind(extractor, graph, source=None, *, rb1=None):
        assert not rb1.active  # This historical fixture does not opt in to isolation.
        received.append(source)
        assert source == expected
        return extractor

    monkeypatch.setattr(extract_runner, "_live_extractor", bind)
    runner.run_batch(tenant_id=TENANT, run_id=run_id, max_calls=2)
    assert received == [expected]


@pytest.mark.parametrize(
    "message,expected",
    [
        ("PROBE_REQUEST_TOO_LARGE", "PROBE_REQUEST_TOO_LARGE"),
        ("DISPLAY_PACKET_MISMATCH", "DISPLAY_PACKET_MISMATCH"),
        ("display quote absent or ambiguous", "DISPLAY_QUOTE_UNRESOLVED"),
        ("preliminary quote absent or ambiguous", "PRELIMINARY_QUOTE_UNRESOLVED"),
        ("secret PDF text /private/file.pdf", "PRELIMINARY_LOCAL_STOP:ValueError"),
    ],
)
def test_preliminary_local_reason_preserves_only_known_causes(message, expected):
    assert _local_stop_code("preliminary", ValueError(message)) == expected


def test_parser_preserves_sdk_stderr_and_surfaces_safe_heap_cause(tmp_path, monkeypatch):
    import subprocess

    import opendataloader_pdf

    from tests.acceptance.test_parsing import JAVA, MANIFEST, pdf

    profile = ParserProfile(MANIFEST, java_executable=JAVA)
    (tmp_path / "source.pdf").write_bytes(pdf())
    (tmp_path / "request.json").write_text(
        json.dumps({"profile": profile.invocation_snapshot(), "selected": [1]})
    )
    stderr = "Exception in thread main java.lang.OutOfMemoryError: Java heap space\n"

    def fail(**kwargs):
        raise subprocess.CalledProcessError(1, ["java"], stderr=stderr)

    monkeypatch.setattr(opendataloader_pdf, "convert", fail)
    # Do not apply child rlimits in the pytest process itself.
    monkeypatch.setattr("proofops.adapters.parsing.opendataloader._child_limits", lambda p: None)
    with pytest.raises(subprocess.CalledProcessError):
        _child(tmp_path)
    assert (tmp_path / "parser-stderr.txt").read_text() == stderr
    with pytest.raises(ParseFailure, match="PARSER_JAVA_HEAP_EXHAUSTED") as failure:
        OpenDataLoaderParser._execute(
            [sys.executable, "-c", "raise SystemExit(1)"], tmp_path, {}, profile
        )
    assert failure.value.stderr_path.is_file()
    assert failure.value.stderr_path.read_text() == stderr
    assert failure.value.stderr_path.parent != tmp_path  # survives scratch cleanup


def test_pilot_memory_limit_is_explicit_bounded_and_resume_preserved():
    from evaluation.local_upstage_pilot import apply_resume_metadata, parser_memory_limit

    assert parser_memory_limit(None) == 805306368
    assert parser_memory_limit(2147483648) == 2147483648
    for value in (True, 0, -1, 4294967297, "2147483648"):
        with pytest.raises(ValueError):
            parser_memory_limit(value)
    # Existing immutable pilot metadata rejects a changed cap before any I/O/calls.
    args = SimpleNamespace(parser_memory_bytes=2147483648)
    with pytest.raises(ValueError, match="parser memory limit changed"):
        apply_resume_metadata(args, {})


def test_relation_construction_failure_records_cause_without_a_replica():
    from proofops_worker.live_tagging import LiveTaggingRuntime

    from tests.acceptance.test_binding import corpus

    graph, claim, _ = corpus()
    runtime = object.__new__(LiveTaggingRuntime)
    runtime.graph = graph
    runtime.auth = SimpleNamespace(tenant_id=graph.tenant_id)
    runtime.snapshot = {"run_id": "run"}
    runtime.relation_settings = SimpleNamespace()
    runtime.relation_records = {}
    assert (
        runtime.relations(claim, SimpleNamespace(to_dict=lambda: {}, packet_sha256="a" * 64))
        is None
    )
    (record,) = runtime.relation_records[claim.claim_id]
    assert record == {
        "status": "needs_review",
        "stable_reason": {
            "category": "local_stop",
            "error_code": "RELATION_PACKET_MISMATCH",
            "detail": None,
        },
    }


def test_parser_worker_retains_diagnostic_and_logs_only_known_stderr(tmp_path, monkeypatch, capsys):
    from proofops.application.ports.jobs import JobMessage

    from tests.acceptance.test_parsing import TENANT
    from tests.integration.test_local_parser_runner import runner_setup

    service, run_id, runner, now, _ = runner_setup(tmp_path, monkeypatch)
    artifact = tmp_path / "private-stderr.txt"
    artifact.write_text("java.lang.OutOfMemoryError: Java heap space\nsecret document text")
    error = ParseFailure("PARSER_JAVA_HEAP_EXHAUSTED")
    error.stderr_path = artifact

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(runner.parser, "parse", fail)
    message = JobMessage(
        **service.store.jobs.pending_outbox(TENANT, run_id, now=now[0])[0]["message"]
    )
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "failed"
    assert service.store.jobs.get_job(message)["error_code"] == "PARSER_JAVA_HEAP_EXHAUSTED"
    usage = service.store.jobs.get_usage(message, fencing_token=1)
    assert usage["parser_diagnostic"]["stderr_artifact"] == str(artifact)
    captured = capsys.readouterr()
    assert "java.lang.OutOfMemoryError: Java heap space" in captured.err
    assert "secret document text" not in captured.err + captured.out


def test_context_budget_includes_display_wire_policy_and_system_suffix(tmp_path, monkeypatch):
    from proofops.domain.provenance import canonical_hash

    from tests.integration.test_glyph_display_text import fixture_catalog
    from tests.integration.test_upstage_preliminary_transport import configured_with_context

    adapter, probe, calls, request, envelope, claim, graph = configured_with_context(
        tmp_path, monkeypatch
    )
    catalog = fixture_catalog(graph, {})
    adapter._display_catalog = catalog
    raw_size = len(adapter._settings.rendered_system.encode()) + len(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    cap = raw_size + 1

    def bounded_body(system, user, **kwargs):
        if len(system.encode()) + len(user.encode()) > cap:
            raise ValueError("PROBE_REQUEST_TOO_LARGE")

    monkeypatch.setattr(probe, "request_body", bounded_body)
    bounded = adapter.bound_context(envelope)
    bounded["display_text"] = catalog.preliminary_pins(bounded, claim.source_refs)
    request.update(user_json=json.dumps(bounded), packet_sha256=canonical_hash(bounded))
    system, user, *_ = adapter._wire_request(request)
    bounded_body(system, user)
    assert (
        bounded["untrusted_document_data"]["sources"]
        == envelope["untrusted_document_data"]["sources"]
    )
    assert calls == []
