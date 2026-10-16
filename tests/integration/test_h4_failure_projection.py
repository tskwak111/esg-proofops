import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "code",
    [
        "PARSER_FAILED",
        "PARSER_MEMORY_LIMIT",
        "PARSER_PDF_INVALID",
        "CLAIM_PAGES_UNREADABLE",
        "SOURCE_ATTESTATION_UNAVAILABLE",
        "SOURCE_ATTESTATION_REPLAY_MISMATCH",
        "SOURCE_ATTESTATION_RENDER_LIMIT",
        "PARSER_NATIVE_TEXT_UNREADABLE",
        "EXTRACTION_INPUT_INVALID",
        "PROBE_REQUEST_TOO_LARGE",
    ],
)
def test_committed_job_reason_survives_hosted_projection(code):
    from proofops.application.ports.jobs import JobMessage

    from evaluation.hosted_r108 import stage_failure_code

    uid = "00000000-0000-4000-8000-000000000001"
    message = JobMessage(
        tenant_id=uid,
        run_id=uid,
        document_version_id=uid,
        job_id=uid,
        stage="parse",
        shard="all",
        input_hash="0" * 64,
    )
    jobs = SimpleNamespace(get_job=lambda _: dict(error_code=code))
    assert stage_failure_code(jobs, [message]) == code
    assert (
        stage_failure_code(
            SimpleNamespace(get_job=lambda _: dict(error_code="private source text")), [message]
        )
        is None
    )


def test_uncommitted_extraction_still_publishes_reason(tmp_path, monkeypatch):
    from proofops_api import hosted_results

    (tmp_path / "pilot.json").write_text(json.dumps(dict(tenant_id="t")))
    (tmp_path / "outcome.json").write_text(
        json.dumps(dict(status="partial_blocked", reason="EXTRACTION_INPUT_INVALID"))
    )
    jobs = SimpleNamespace(
        get_run=lambda *a: dict(current_stage="extract"), read_checkpoint=lambda *a: None
    )
    claims = SimpleNamespace(store=SimpleNamespace(jobs=jobs))

    @contextmanager
    def services(*args):
        yield "r", claims, None, None

    monkeypatch.setattr(hosted_results, "services", services)
    result = hosted_results.read_result(tmp_path, "t", [1])
    assert result["claims"] == []
    assert result["hold_reasons"] == ["EXTRACTION_INPUT_INVALID"]
    assert result["confirmed_grade"] is None


def test_pdf_read_failure_is_specific_sanitized_and_commits_no_source(tmp_path, monkeypatch):
    from proofops.application.ports.jobs import JobMessage
    from pypdf.errors import PdfReadError

    from tests.acceptance.test_upload import TENANT
    from tests.integration.test_local_parser_runner import runner_setup

    service, run, worker, now, stream = runner_setup(tmp_path, monkeypatch)
    event = service.store.jobs.pending_outbox(TENANT, run, now=now[0])[0]
    message = JobMessage(**event["message"])

    def fail(*a, **k):
        raise PdfReadError("private source content must never appear")

    monkeypatch.setattr(worker.parser, "parse", fail)
    assert worker.run_once(tenant_id=TENANT, run_id=run) == "failed"
    assert worker.store.jobs.get_job(message)["error_code"] == "PARSER_PDF_INVALID"
    assert worker.store.jobs.read_checkpoint(message) is None
    assert "private source content" not in stream.getvalue()


def test_pending_tag_job_preserves_committed_extracted_claims(tmp_path, monkeypatch):
    from proofops_api import hosted_results

    from tests.acceptance.test_upload import TENANT
    from tests.integration.test_local_tag_runner import tag_setup

    service, run, worker, now, _ = tag_setup(tmp_path, monkeypatch)
    state = service.store.jobs.get_run(TENANT, run)
    assert "tag_job" not in state and "tag_snapshot_sha256" not in state
    assert any(
        event["message"]["stage"] == "tag"
        for event in service.store.jobs.pending_outbox(TENANT, run, now=now[0])
    )
    published = tmp_path / "publication"
    published.mkdir()
    (published / "pilot.json").write_text(json.dumps(dict(tenant_id=TENANT)))
    (published / "outcome.json").write_text(
        json.dumps(dict(status="partial_blocked", reason="PROBE_REQUEST_TOO_LARGE"))
    )

    @contextmanager
    def services(*args):
        reviews = SimpleNamespace(store=SimpleNamespace(page=lambda *a, **k: dict(items=[])))
        yield run, worker.claims, None, reviews

    monkeypatch.setattr(hosted_results, "services", services)
    result = hosted_results.read_result(published, TENANT, [1, 2, 3])
    assert result["claims"]
    assert result["hold_reasons"] == ["PROBE_REQUEST_TOO_LARGE", "CLAIM_PAGE_PARSE_FAILURE"]
    assert {
        p["physical_page"] for p in result["pipeline"]["extraction_outcome"]["page_failures"]
    } == {1, 3}
    assert all(c["confirmed_grade"] is None for c in result["claims"])
