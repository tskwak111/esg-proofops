"""Offline real-PDF extraction and literal-source smoke checks, never semantic evaluation.

Run with --reports-dir and --output; PDF originals are never modified. A first run
records supplied official source URLs and filesystem download-time estimates in
sources.json. Later runs verify that inventory rather than silently trusting new bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from proofops.adapters.reconciliation import FileSourceReader, SourceReadError
from pypdf import PdfReader

REPORTS = (
    (
        "NAVER_2024_KOR.pdf",
        "NAVER Integrated Report 2024",
        2024,
        "https://www.navercorp.com/static/NAVER_Integrated_Report_2024_KOR.pdf",
    ),
    (
        "Samsung_Electronics_2025_KOR.pdf",
        "삼성전자 지속가능경영보고서 2025",
        2025,
        "https://www.samsung.com/sec/sustainability/media/pdf/"
        "Samsung_Electronics_Sustainability_Report_2025_KOR.pdf",
    ),
    (
        "Samsung_SDI_2025_KOR.pdf",
        "2025 SAMSUNG SDI 지속가능경영보고서",
        2025,
        "https://samsungsdi.com/upload/download/sustainable-management/"
        "Samsung_SDI_Sustainability_Report_2025_KR_fn.pdf",
    ),
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path, data: Any, *, exclusive: bool = False) -> None:
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def source_inventory(root: Path) -> dict[str, Any]:
    """Inventory report editions, explicitly not trusted company or fiscal-year bindings."""
    destination = root / "sources.json"
    if destination.exists():
        inventory = json.loads(destination.read_text(encoding="utf-8"))
        if inventory.get("schema_version") != "report-sources-1":
            raise ValueError("invalid_inventory")
        if {entry["filename"] for entry in inventory["sources"]} != {r[0] for r in REPORTS}:
            raise ValueError("inventory_report_set_mismatch")
        for entry in inventory["sources"]:
            path = (root / entry["filename"]).resolve(strict=True)
            if (
                path.parent != root.resolve()
                or _sha(path.read_bytes()) != entry["sha256"]
                or path.stat().st_size != entry["file_size"]
            ):
                raise ValueError("inventory_artifact_mismatch")
            if (
                entry.get("trusted_company_id") is not None
                or entry.get("trusted_fiscal_year") is not None
            ):
                raise ValueError("smoke_inventory_must_not_assert_trusted_identity")
        return inventory
    entries = []
    for filename, title, year, url in REPORTS:
        path = root / filename
        payload = path.read_bytes()
        entries.append(
            {
                "filename": filename,
                "official_url": url,
                "title": title,
                "report_year": year,
                "file_size": len(payload),
                "sha256": _sha(payload),
                "downloaded_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "downloaded_at_basis": "filesystem_mtime_estimate_not_download_receipt",
                "url_provenance": "operator_supplied_official_url_not_refetched",
                "trusted_company_id": None,
                "trusted_fiscal_year": None,
            }
        )
    inventory = {"schema_version": "report-sources-1", "sources": entries}
    _json(destination, inventory, exclusive=True)
    return inventory


def smoke_pdf(path: Path, output: Path, *, render: bool = True) -> dict[str, Any]:
    """Extract every page and test literal quote, tampered bytes/quote, and invalid page.

    Readable means non-whitespace text was extracted, not OCR accuracy or semantic truth.
    Empty pages remain explicitly non-readable; no complete coverage claim is inferred.
    """
    output.mkdir(parents=True, exist_ok=True)
    payload = path.read_bytes()
    digest = _sha(payload)
    result: dict[str, Any] = {
        "filename": path.name,
        "sha256": digest,
        "file_size": len(payload),
        "status": "failed",
        "page_count": 0,
        "readable_pages": 0,
        "non_readable_pages": [],
        "extraction_errors": [],
        "pages": [],
        "checks": {},
        "semantic_evaluation": "not_run",
        "semantic_gold": None,
        "policy_approval": None,
        "trusted_company_id": None,
        "trusted_fiscal_year": None,
        "visual_inspection": "pending" if render else "not_run",
    }
    texts = []
    try:
        pdf = PdfReader(path, strict=True)
        if pdf.is_encrypted:
            raise ValueError("encrypted_pdf")
        result["page_count"] = len(pdf.pages)
        for number, page in enumerate(pdf.pages, 1):
            error = None
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                text, error = "", type(exc).__name__
                result["extraction_errors"].append({"page": number, "error": error})
            texts.append(text)
            readable = bool(text.strip())
            result["readable_pages"] += int(readable)
            if not readable:
                result["non_readable_pages"].append(number)
            result["pages"].append(
                {
                    "page": number,
                    "characters": len(text),
                    "readable": readable,
                    "text_sha256": _sha(text.encode()),
                    "error": error,
                }
            )
    except Exception as exc:
        result["extraction_errors"].append({"page": None, "error": type(exc).__name__})
    (output / "extracted.txt").write_text(
        "\n\n".join(f"=== PDF page {i} ===\n{text}" for i, text in enumerate(texts, 1)),
        encoding="utf-8",
    )
    eligible = [i for i, text in enumerate(texts, 1) if text.strip()]
    if eligible:
        selected = next((i for i in eligible if i >= 3 and len(texts[i - 1]) >= 80), eligible[0])
        text = texts[selected - 1]
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        quote = next((line[:160] for line in lines if len(line) >= 20), lines[0][:160])
        ref = {
            "source_id": "smoke-literal",
            "document_id": "report",
            "artifact_sha256": digest,
            "locator": f"page:{selected}",
            "quote": quote,
        }
        result["selected_source"] = ref
        reader = FileSourceReader(
            path.parent,
            {
                "report": {"path": path.name, "format": "pdf", "sha256": digest},
            },
        )
        bad_quote = "SMOKE_NEGATIVE_LITERAL_NOT_IN_REPORT"
        while bad_quote in text:
            bad_quote += "_X"
        cases = (
            ("literal_quote", ref, None, None),
            ("tampered_payload", ref, payload + b"\nSMOKE_TAMPER", "artifact_hash_mismatch"),
            ("tampered_quote", {**ref, "quote": bad_quote}, None, "quote_mismatch"),
            (
                "invalid_page",
                {**ref, "locator": f"page:{len(texts) + 1}"},
                None,
                "page_out_of_range",
            ),
        )
        for name, reference, supplied, expected in cases:
            actual = None
            try:
                reader.validate(reference, supplied)
            except SourceReadError as exc:
                actual = str(exc)
            result["checks"][name] = {
                "passed": actual == expected,
                "expected_error": expected,
                "actual_error": actual,
            }
        if render:
            try:
                import pypdfium2 as pdfium

                with pdfium.PdfDocument(path) as document:
                    page = document[selected - 1]
                    bitmap = page.render(scale=1.4)
                    bitmap.to_pil().save(output / "representative.png")
                    bitmap.close()
                    page.close()
                result["render"] = {
                    "status": "passed",
                    "page": selected,
                    "path": "representative.png",
                }
            except Exception as exc:
                result["render"] = {"status": "failed", "error": type(exc).__name__}
        else:
            result["render"] = {"status": "not_run"}
        if (
            not result["extraction_errors"]
            and all(check["passed"] for check in result["checks"].values())
            and result["render"]["status"] != "failed"
        ):
            result["status"] = "passed"
    result["text_coverage"] = (
        "all_pages_nonempty"
        if result["page_count"]
        and not result["non_readable_pages"]
        and not result["extraction_errors"]
        else "incomplete"
    )
    _json(output / "evidence.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, default=Path("지속가능경영보고서"))
    parser.add_argument("--output", type=Path, default=Path(".local/report-smoke"))
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args(argv)
    inventory = source_inventory(args.reports_dir)
    args.output.mkdir(parents=True, exist_ok=True)
    results = [
        smoke_pdf(
            args.reports_dir / entry["filename"],
            args.output / Path(entry["filename"]).stem,
            render=not args.no_render,
        )
        for entry in inventory["sources"]
    ]
    summary = {
        "schema_version": "report-smoke-1",
        "run_at": datetime.now(UTC).isoformat(),
        "pypdf_version": version("pypdf"),
        "pypdfium2_version": version("pypdfium2"),
        "semantic_evaluation": "not_run",
        "semantic_gold": None,
        "policy_approval": None,
        "reports": results,
        "passed": bool(results) and all(r["status"] == "passed" for r in results),
    }
    _json(args.output / "summary.json", summary)
    print(
        json.dumps(
            {
                "passed": summary["passed"],
                "reports": len(results),
                "pages": sum(r["page_count"] for r in results),
            }
        )
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
