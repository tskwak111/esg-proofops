"""Run the direct parser, or explicitly local-only diagnostics without paid requests."""

import argparse
import json
import os
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import NAMESPACE_URL, uuid4, uuid5

from proofops.adapters.parsing.docling_document import DoclingParser, convert_pages
from proofops.adapters.parsing.docling_validation import audit, guarded_graph
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact
from proofops.application.uploads_security import PdfLimits, QuarantinedPdf, verify_quarantined_pdf


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pdf", type=Path, required=True)
    cli.add_argument("--pages", required=True, help="Explicit physical pages, comma separated")
    cli.add_argument("--python", type=Path)
    cli.add_argument("--ssh-target", help="Existing SSH user@host for the A100 40GB runtime")
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--artifact-root", type=Path, default=Path(".local/docling-artifacts"))
    cli.add_argument("--invoke-upstage", action="store_true")
    cli.add_argument("--ledger", type=Path)
    cli.add_argument("--env-file", type=Path, help="Read only UPSTAGE_API_KEY; never print/save it")
    cli.add_argument(
        "--vision-key-file",
        type=Path,
        help="Read OPENAI_API_KEY for Sol, otherwise OPENROUTER_API_KEY",
    )
    cli.add_argument("--vision", action="store_true")
    cli.add_argument("--vision-model", choices=["gpt-6-sol"])
    args = cli.parse_args()
    if args.env_file:
        for line in args.env_file.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == "UPSTAGE_API_KEY":
                os.environ["UPSTAGE_API_KEY"] = value.strip().strip("\"'")
    if args.vision_key_file and args.vision:
        for line in args.vision_key_file.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            key_name = "OPENAI_API_KEY" if args.vision_model else "OPENROUTER_API_KEY"
            if separator and name.strip() == key_name:
                os.environ[key_name] = value.strip().strip("\"'")
    if args.output.exists():
        cli.error("output already exists; choose a new result directory")
    if args.invoke_upstage and (not args.ledger or not args.ledger.is_file()):
        cli.error("--invoke-upstage requires the existing shared --ledger")
    content = args.pdf.read_bytes()
    digest = sha256(content).hexdigest()

    def identifier(name):
        return str(uuid5(NAMESPACE_URL, "docling-lab:" + name))

    source = SourceArtifact(
        identifier("tenant"),
        identifier(digest),
        identifier(digest + ":v1"),
        digest,
        "sha256:" + digest,
        content,
        upload_security_limits=asdict(PdfLimits.display()),
    )
    profile = ParserProfile(
        str(uuid4()),
        physical_pages=tuple(sorted(set(map(int, args.pages.split(","))))),
        parser_mode="docling",
        table_auxiliary=False,
        docling_python=str(args.python.resolve()) if args.python else None,
        docling_ssh_target=args.ssh_target,
        timeout_seconds=600,
        memory_bytes=8 * 1024**3,
        max_output_bytes=100 * 1024**2,
        upstage_glyph_boxes=True,
        upstage_region_words=True,
        vision_parse="auto" if args.vision else "off",
        vision_model=args.vision_model,
    )
    args.output.mkdir(parents=True)
    start = monotonic()
    result = dict(
        source_sha256=digest,
        pages=profile.physical_pages,
        mode="independent_crosscheck" if args.invoke_upstage else "local_diagnostic_only",
    )
    try:
        probe = None
        if args.invoke_upstage:
            from proofops.adapters.local.upstage_parse import UpstageParseProbe

            probe = UpstageParseProbe(os.environ.get("UPSTAGE_API_KEY", ""), args.ledger)
        parser = DoclingParser(args.artifact_root, upstage_probe=probe)
        if probe:
            graph = parser.parse(source, profile, tenant_id=source.tenant_id)
            assert parser.load_verified(source, profile, tenant_id=source.tenant_id) == graph
            result["verified_replay"] = True
            result["manifest"] = str(parser._directory(source, profile) / "manifest.json")
        else:
            verified = verify_quarantined_pdf(
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
            if any(p > verified.page_count for p in profile.physical_pages):
                raise ValueError("PAGE_SELECTION_INVALID")
            pages = parser.prepare_pages(source, profile, profile.physical_pages)
            batch = convert_pages(pages, source, profile)
            records = audit([batch], pages, crosscheck=False)
            graph = guarded_graph([batch], records, tenant_id=source.tenant_id, pages=pages)
            (args.output / "pages.json").write_text(json.dumps(pages), encoding="utf-8")
            (args.output / "audit.json").write_text(json.dumps(records), encoding="utf-8")
            result["verified_replay"] = False
        (args.output / "graph.json").write_text(json.dumps(graph.to_dict()), encoding="utf-8")
        result.update(
            status="completed",
            blocks=len(graph.blocks),
            quality=dict(Counter(b.quality for b in graph.blocks)),
            issues=len(graph.issues),
            semantic_gold=None,
        )
    except Exception as error:
        result.update(status="failed", error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        result["duration_seconds"] = round(monotonic() - start, 3)
        (args.output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
