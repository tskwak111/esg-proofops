"""Small synthetic PDF checks for repeatable offline report smoke validation."""

import json

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from evaluation import reconciliation_report_smoke as smoke


def make_pdf(path, *, text=True, blank_page=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    if text:
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/F1"): DictionaryObject(
                            {
                                NameObject("/Type"): NameObject("/Font"),
                                NameObject("/Subtype"): NameObject("/Type1"),
                                NameObject("/BaseFont"): NameObject("/Helvetica"),
                            }
                        )
                    }
                ),
            }
        )
        content = DecodedStreamObject()
        content.set_data(
            b"BT /F1 12 Tf 20 200 Td (Literal sustainability report smoke quote) Tj ET"
        )
        page[NameObject("/Contents")] = writer._add_object(content)
    if blank_page:
        writer.add_blank_page(width=300, height=300)
    writer.write(path)
    return path


def test_literal_and_negative_checks_leave_original_unchanged(tmp_path):
    path = make_pdf(tmp_path / "source.pdf", blank_page=True)
    original = path.read_bytes()
    result = smoke.smoke_pdf(path, tmp_path / "out", render=False)
    assert result["status"] == "passed"
    assert result["page_count"] == 2
    assert result["readable_pages"] == 1
    assert result["non_readable_pages"] == [2]
    assert result["text_coverage"] == "incomplete"
    assert result["extraction_errors"] == []
    assert set(result["checks"]) == {
        "literal_quote",
        "tampered_payload",
        "tampered_quote",
        "invalid_page",
    }
    assert all(check["passed"] for check in result["checks"].values())
    assert result["checks"]["tampered_payload"]["actual_error"] == "artifact_hash_mismatch"
    assert result["checks"]["invalid_page"]["actual_error"] == "page_out_of_range"
    assert path.read_bytes() == original
    assert result["semantic_evaluation"] == "not_run"
    assert result["semantic_gold"] is result["policy_approval"] is None
    assert json.loads((tmp_path / "out/evidence.json").read_text()) == result
    repeated = smoke.smoke_pdf(path, tmp_path / "out", render=False)
    assert repeated == result


@pytest.mark.parametrize("invalid", [False, True])
def test_unreadable_or_invalid_pdf_cannot_pass(tmp_path, invalid):
    path = tmp_path / "source.pdf"
    if invalid:
        path.write_bytes(b"not a PDF")
    else:
        make_pdf(path, text=False)
    result = smoke.smoke_pdf(path, tmp_path / "out", render=False)
    assert result["status"] == "failed"
    assert result["checks"] == {}
    assert result["readable_pages"] == 0
    assert result["text_coverage"] == "incomplete"
    assert bool(result["extraction_errors"]) == invalid


def test_page_extraction_error_is_recorded(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "source.pdf")

    class BrokenPage:
        def extract_text(self):
            raise RuntimeError("synthetic extraction error")

    class BrokenReader:
        is_encrypted = False
        pages = [BrokenPage()]

    monkeypatch.setattr(smoke, "PdfReader", lambda *args, **kwargs: BrokenReader())
    result = smoke.smoke_pdf(path, tmp_path / "out", render=False)
    assert result["status"] == "failed"
    assert result["page_count"] == 1
    assert result["extraction_errors"] == [{"page": 1, "error": "RuntimeError"}]


def test_rendered_page_requires_separate_visual_review(tmp_path):
    pytest.importorskip("pypdfium2")
    path = make_pdf(tmp_path / "source.pdf")
    result = smoke.smoke_pdf(path, tmp_path / "out")
    assert result["status"] == "passed"
    assert result["render"]["page"] == 1
    assert (tmp_path / "out/representative.png").read_bytes().startswith(b"\x89PNG")
    assert result["visual_inspection"] == "pending"


def test_smoke_fails_if_reader_stops_rejecting_negative_cases(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "source.pdf")
    monkeypatch.setattr(smoke.FileSourceReader, "validate", lambda *args: True)
    result = smoke.smoke_pdf(path, tmp_path / "out", render=False)
    assert result["status"] == "failed"
    assert result["checks"]["literal_quote"]["passed"] is True
    assert result["checks"]["tampered_payload"]["passed"] is False
    assert result["checks"]["invalid_page"]["passed"] is False


def test_inventory_preserved_and_changed_original_rejected(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "source.pdf")
    monkeypatch.setattr(
        smoke,
        "REPORTS",
        ((path.name, "Synthetic report", 2024, "https://example.invalid/synthetic.pdf"),),
    )
    inventory = smoke.source_inventory(tmp_path)
    entry = inventory["sources"][0]
    assert entry["trusted_company_id"] is entry["trusted_fiscal_year"] is None
    assert entry["file_size"] == path.stat().st_size
    assert entry["downloaded_at_basis"] == "filesystem_mtime_estimate_not_download_receipt"
    assert smoke.source_inventory(tmp_path) == inventory
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="inventory_artifact_mismatch"):
        smoke.source_inventory(tmp_path)


def test_cli_records_nonsemantic_machine_evidence(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "source.pdf")
    monkeypatch.setattr(
        smoke,
        "REPORTS",
        ((path.name, "Synthetic report", 2024, "https://example.invalid/synthetic.pdf"),),
    )
    output = tmp_path / "out"
    assert smoke.main(["--reports-dir", str(tmp_path), "--output", str(output), "--no-render"]) == 0
    summary = json.loads((output / "summary.json").read_text())
    assert summary["passed"] is True
    assert summary["semantic_evaluation"] == "not_run"
    assert summary["semantic_gold"] is summary["policy_approval"] is None
