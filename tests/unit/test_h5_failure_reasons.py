from types import SimpleNamespace

import pytest


def test_original_large_pdf_page_is_render_limit_without_paid_ocr():
    import io

    from proofops.adapters.local.source_attestation_errors import source_failure_code
    from proofops.adapters.local.upstage_ocr_page import render_page
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=2000, height=1000)
    stream = io.BytesIO()
    writer.write(stream)
    with pytest.raises(ValueError, match="^OCR_RENDER_LIMIT$") as failure:
        render_page(stream.getvalue(), 1)
    assert source_failure_code(failure.value) == "SOURCE_ATTESTATION_RENDER_LIMIT"
    assert source_failure_code(ValueError("SOURCE_INTEGRITY_MISMATCH")) is None


@pytest.mark.parametrize("code", ["H2_CUMULATIVE_BUDGET_EXHAUSTED", "H5_BUDGET_EXHAUSTED"])
def test_source_ocr_budget_stop_is_not_mislabeled_as_pdf_parse_failure(code):
    from proofops.adapters.local.source_attestation_errors import source_failure_code

    assert source_failure_code(ValueError(code)) == "BUDGET_EXHAUSTED"


def test_pdfminer_eof_is_specific_and_keeps_private_diagnostic(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from proofops.adapters.parsing import opendataloader

    work = tmp_path / "work"
    work.mkdir()
    stderr = (
        b"private document words\npdfplumber.utils.exceptions.PdfminerException: Unexpected EOF\n"
    )
    (work / "launcher-stderr.txt").write_bytes(stderr)
    process = SimpleNamespace(poll=lambda: 1, returncode=1)

    class Isolation:
        @contextmanager
        def spawn(self, *args, **kwargs):
            yield process

        def terminate_tree(self, process):
            pass

        def close(self):
            pass

    monkeypatch.setattr(opendataloader, "process_isolation", lambda **kwargs: Isolation())
    monkeypatch.setattr(opendataloader, "_check_limits", lambda *args: None)
    monkeypatch.setattr(opendataloader, "kill_and_reap", lambda *args: None)
    profile = SimpleNamespace(timeout_seconds=10, memory_bytes=768 * 1024**2)
    with pytest.raises(opendataloader.ParseFailure, match="^PARSER_NATIVE_TEXT_UNREADABLE$") as f:
        opendataloader.OpenDataLoaderParser._execute([], work, {}, profile)
    assert f.value.stderr_path.read_bytes() == stderr
    assert "private document" not in str(f.value)


def test_h5_policy_is_new_opt_in_and_h4_hash_stays_frozen():
    from proofops.application.analysis_profile import (
        FINALS_H4_POLICY,
        FINALS_H5_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert canonical_hash(FINALS_H4_POLICY).startswith("02d592aa")
    pin = canonical_hash(FINALS_H5_POLICY)
    assert pin != canonical_hash(FINALS_H4_POLICY)
    assert policy_for(V2_PROFILE, pinned_hash=pin) == FINALS_H5_POLICY
    assert publication_policy_for(V2_PROFILE, pinned_hash=pin) == FINALS_H5_POLICY
