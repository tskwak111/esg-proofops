"""Explicit bounded Sol vision review, preserving parser evidence and unapproved candidates."""

import argparse
import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

from proofops.adapters.parsing.openai_vision import OpenAIVisionProbe, parse_pages
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact
from proofops.application.uploads_security import PdfLimits, QuarantinedPdf, verify_quarantined_pdf


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pdf", type=Path, required=True)
    cli.add_argument("--pages", required=True)
    cli.add_argument("--env-file", type=Path, default=Path(".env.openai.local"))
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    pages = sorted(set(map(int, args.pages.split(","))))
    if not 1 <= len(pages) <= 10 or min(pages) < 1 or args.output.exists():
        cli.error("select 1..10 physical pages and a new output directory")
    key = None
    for line in args.env_file.read_text(encoding="utf-8-sig").splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() == "OPENAI_API_KEY":
            key = value.strip().strip("\"'")
    if not key:
        cli.error("OPENAI_API_KEY_REQUIRED")
    content = args.pdf.read_bytes()
    digest = sha256(content).hexdigest()

    def identify(name):
        return str(uuid5(NAMESPACE_URL, "docling-lab:" + name))

    source = SourceArtifact(
        identify("tenant"),
        identify(digest),
        identify(digest + ":v1"),
        digest,
        "sha256:" + digest,
        content,
    )
    checked = verify_quarantined_pdf(
        QuarantinedPdf(
            source.tenant_id,
            source.document_version_id,
            source.object_version_id,
            content,
            len(content),
            digest,
        ),
        PdfLimits.display(),
        tenant_id=source.tenant_id,
    )
    if max(pages) > checked.page_count:
        cli.error("page outside document")
    args.output.mkdir(parents=True)
    probe = OpenAIVisionProbe()
    result = dict(
        source_sha256=digest,
        model="gpt-6-sol",
        candidate_only=True,
        semantic_accuracy=None,
        pages=[],
        budget_before=probe.summary(),
    )
    for number in pages:
        profile = ParserProfile(
            str(uuid4()),
            physical_pages=(number,),
            parser_mode="docling",
            table_auxiliary=False,
            vision_parse="all",
            vision_model="gpt-6-sol",
        )
        try:
            batch, metrics = parse_pages(
                source,
                profile,
                SimpleNamespace(blocks=(), issues=()),
                [number],
                Path(".local/docling-artifacts/vision-cache"),
                key=key,
            )
            metrics["fragment_rate_local"] = (
                None  # No local graph supplied to this review-only tool.
            )
            receipt = dict(
                source_sha256=digest,
                profile=profile.invocation_snapshot(),
                candidate=asdict(batch),
                metrics=metrics,
            )
            raw = json.dumps(receipt, ensure_ascii=False, indent=2).encode("utf-8")
            (args.output / f"page-{number}.json").write_bytes(raw)
            result["pages"].append(
                dict(
                    page=number,
                    status="candidate_only",
                    receipt_sha256=sha256(raw).hexdigest(),
                    metrics=metrics,
                )
            )
        except (ValueError, OSError, TimeoutError) as error:
            result["pages"].append(
                dict(
                    page=number,
                    status="failed_requires_review",
                    error=type(error).__name__,
                    reason=str(error),
                )
            )
            break
        finally:
            result["budget_after"] = probe.summary()
            (args.output / "summary.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    print(
        json.dumps(
            dict(
                pages=[{k: v for k, v in row.items() if k != "metrics"} for row in result["pages"]],
                budget=result["budget_after"],
            )
        )
    )
    if any(row["status"] == "failed_requires_review" for row in result["pages"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
