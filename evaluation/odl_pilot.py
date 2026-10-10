"""Local ODL version experiments; lexical diagnostics are not claim verification."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def raw_nodes(raw):
    """Preserve original physical pages; never invent boxes for containers."""

    def walk(node, page=None, depth=0, path="root"):
        if depth > 100 or not isinstance(node, dict):
            raise ValueError("invalid ODL tree")
        page = node.get("page number", page)
        text = node.get("content", "")
        box = node.get("bounding box")
        valid = (
            isinstance(box, list)
            and len(box) == 4
            and all(type(x) in (int, float) and math.isfinite(x) for x in box)
            and box[0] < box[2]
            and box[1] < box[3]
        )
        if text:
            yield {
                "id": node.get("id", "path:" + path),
                "page": page,
                "kind": node.get("type"),
                "text": text,
                "bbox": box if valid else None,
            }
        for key in ("kids", "rows", "cells", "list items"):
            for index, child in enumerate(node.get(key, [])):
                yield from walk(child, page, depth + 1, f"{path}/{key}/{index}")

    return list(walk(raw))


def compare_quotes(nodes, reference):
    """Match baseline source quotes, not analyst paraphrases or short numbers."""

    def compact(text):
        return "".join(text.split())

    results = []
    for case in reference["rows"]:
        quotes = [compact(block["text"]) for block in case["system_blocks"] if block["text"]]
        hits = [
            node
            for node in nodes
            if node["page"] == case["page"]
            and any(quote in compact(node["text"]) for quote in quotes)
        ]
        results.append(
            {
                "id": case["id"],
                "page": case["page"],
                "baseline_quote_found_in_single_node": bool(hits),
                "located_quote_hits": sum(node["bbox"] is not None for node in hits),
                "node_ids": [node["id"] for node in hits],
                "semantic_verified": False,
            }
        )
    return results


def child(request_path):
    import opendataloader_pdf

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    installed = version("opendataloader-pdf")
    if installed != request["version"]:
        raise ValueError("ODL_VERSION_MISMATCH")
    started = time.monotonic()
    options = {}
    if request.get("hybrid"):
        options = {
            "hybrid": "docling-fast",
            "hybrid_mode": "full",
            "hybrid_url": request["hybrid"],
            "hybrid_timeout": "480000",
            "hybrid_fallback": False,
        }
    else:
        options = {"hybrid": "off"}
    with (Path(request["output"]) / "sdk.log").open("w", encoding="utf-8") as log:
        with redirect_stdout(log), redirect_stderr(log):
            opendataloader_pdf.convert(
                input_path=[request["pdf"]],
                output_dir=request["output"],
                format="json,markdown",
                pages=",".join(map(str, request["pages"])),
                image_output="off",
                quiet=False,
                **options,
            )
    write_json(
        Path(request["output"]) / "timing.json",
        {"version": installed, "conversion_seconds": time.monotonic() - started},
    )


def main():
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, _child_environment
    from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact
    from proofops.application.uploads_security import (
        PdfLimits,
        QuarantinedPdf,
        verify_quarantined_pdf,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pages", default="2,99,100,101,105,200,201,209")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        help="Bounded per-process CPU/wall budget, at most 900 seconds",
    )
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--candidate-python", type=Path)
    parser.add_argument(
        "--table-auxiliary",
        action="store_true",
        help="Use existing pdfplumber auxiliary in the application adapter",
    )
    parser.add_argument("--hybrid-url", help="Explicit loopback Docling backend; full mode")
    parser.add_argument(
        "--hybrid-receipt", type=Path, help="Required evidence of completed backend conversion"
    )
    parser.add_argument("--candidate-version", choices=("2.0.0", "2.5.7"), default="2.0.0")
    args = parser.parse_args()
    timeout = args.timeout_seconds or (600 if args.hybrid_url else 180)
    if args.timeout_seconds is not None and not 1 <= args.timeout_seconds <= 900:
        parser.error("timeout must be between 1 and 900 seconds")
    if args.table_auxiliary and args.candidate_python:
        parser.error("table auxiliary is only available through the application adapter")
    if args.hybrid_url:
        url = urlsplit(args.hybrid_url)
        if (
            not args.candidate_python
            or not args.hybrid_receipt
            or url.scheme != "http"
            or url.hostname not in ("127.0.0.1", "localhost")
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in ("", "/")
        ):
            parser.error("hybrid requires candidate Python and a loopback HTTP origin")
    pages = tuple(sorted(set(map(int, args.pages.split(",")))))
    if not pages or min(pages) < 1:
        parser.error("positive physical pages required")
    if args.pdf.stat().st_size > 100 * 1024 * 1024:
        parser.error("PDF exceeds input limit")
    content = args.pdf.read_bytes()
    digest = sha256(content).hexdigest()
    reference = json.loads(args.reference.read_text(encoding="utf-8")) if args.reference else None
    if reference and reference["source_sha256"] != digest:
        parser.error("reference source hash mismatch")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    tenant = str(uuid5(NAMESPACE_URL, "proofops-odl-pilot"))
    identity = str(uuid5(NAMESPACE_URL, digest))
    source = SourceArtifact(
        tenant,
        identity,
        identity,
        digest,
        digest,
        content,
        upload_security_limits=asdict(PdfLimits.display()),
    )
    profile = ParserProfile(
        str(uuid5(NAMESPACE_URL, str(output))),
        physical_pages=pages,
        timeout_seconds=timeout,
        memory_bytes=2 * 1024**3,
        max_output_bytes=60 * 1024**2,
        table_auxiliary=args.table_auxiliary,
    )
    report = {
        "schema": "odl-pilot-v1",
        "source_sha256": digest,
        "pages": pages,
        "mode": "hybrid-full" if args.hybrid_url else "local",
        "semantic_accuracy": None,
        "claims": "not_run",
        "reconciliation": "not_run",
        "policy_approval": None,
        "table_auxiliary": args.table_auxiliary,
        "timeout_seconds": timeout,
    }
    started = time.monotonic()
    try:
        if args.candidate_python:
            verified = verify_quarantined_pdf(
                QuarantinedPdf(tenant, identity, digest, content, len(content), digest),
                PdfLimits.display(),
                tenant_id=tenant,
            )
            if max(pages) > verified.page_count:
                raise ValueError("PAGE_SELECTION_INVALID")
            work = output / "raw"
            work.mkdir()
            (work / "source.pdf").write_bytes(content)
            write_json(
                work / "request.json",
                {
                    "version": args.candidate_version,
                    "pdf": str(work / "source.pdf"),
                    "output": str(work),
                    "pages": pages,
                    "hybrid": args.hybrid_url,
                },
            )
            java = shutil.which("java")
            if java is None:
                raise ValueError("JAVA_REQUIRED")
            env = _child_environment(java, work, profile)
            OpenDataLoaderParser._execute(
                [
                    str(args.candidate_python.resolve()),
                    "-I",
                    str(Path(__file__).resolve()),
                    "--child",
                    str(work / "request.json"),
                ],
                work,
                env,
                profile,
            )
            raw = json.loads((work / "source.json").read_bytes())
            if raw.get("number of pages") != verified.page_count:
                raise ValueError("PARSER_PAGE_MAPPING_INVALID")
            nodes = raw_nodes(raw)
            if any(node["page"] not in pages for node in nodes):
                raise ValueError("PARSER_PAGE_MAPPING_INVALID")
            report.update(json.loads((work / "timing.json").read_bytes()))
            report["pipeline_integration"] = False
            if args.hybrid_url:
                receipt = json.loads(args.hybrid_receipt.read_text(encoding="utf-8"))
                if (
                    receipt.get("status") != "success"
                    or receipt.get("source_sha256") != digest
                    or receipt.get("pages") != list(pages)
                ):
                    raise ValueError("HYBRID_BACKEND_SUCCESS_UNCONFIRMED")
                raw_backend = args.hybrid_receipt.with_name("docling-document.json").read_bytes()
                if sha256(raw_backend).hexdigest() != receipt.get("document_sha256"):
                    raise ValueError("HYBRID_BACKEND_ARTIFACT_MISMATCH")
                report["backend_receipt"] = receipt
        else:
            adapter = OpenDataLoaderParser(output / "prepared")
            graph = adapter.parse(source, profile, tenant_id=tenant)
            assert graph == adapter.load_verified(source, profile, tenant_id=tenant)
            write_json(
                output / "graph.json",
                {
                    "blocks": [
                        {**block.to_dict(), "quality": block.quality} for block in graph.blocks
                    ],
                    "edges": [asdict(edge) for edge in graph.edges],
                },
            )
            nodes = [
                {
                    "id": block.source_id,
                    "page": block.page_num,
                    "kind": block.kind,
                    "text": block.raw_text,
                    "bbox": block.bbox,
                }
                for block in graph.blocks
            ]
            report.update(
                version=version("opendataloader-pdf"),
                pipeline_integration=True,
                verified_artifact_replay=True,
                qualities=dict(Counter(block.quality for block in graph.blocks)),
            )
        write_json(output / "nodes.json", nodes)
        report.update(
            status="succeeded",
            total_nodes=len(nodes),
            text_nodes=sum(bool(node["text"]) for node in nodes),
            located_nodes=sum(node["bbox"] is not None for node in nodes),
            kinds=dict(Counter(node["kind"] for node in nodes)),
            reference_cases=compare_quotes(nodes, reference) if reference else [],
        )
    except Exception as error:
        report.update(status="failed", reason=type(error).__name__ + ": " + str(error))
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    write_json(output / "report.json", report)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["status"] == "succeeded" else 2


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child(sys.argv[2])
    else:
        raise SystemExit(main())
