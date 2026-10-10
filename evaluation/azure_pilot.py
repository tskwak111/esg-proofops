"""Explicit, resumable Azure parsing diagnostic; no grading or policy approval."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from proofops.adapters.parsing.azure_client import AzureFailure, AzureLayoutClient
from proofops.adapters.parsing.azure_layout import AzureLayoutParser
from proofops.adapters.parsing.opendataloader import ParseFailure
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact
from proofops.application.uploads_security import PdfLimits, UploadRejected

ROOT = Path(__file__).resolve().parents[1]


def load_credentials(path):
    allowed = {
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT",
        "AZURE_DOCUMENT_INTELLIGENCE_KEY",
        "AZURE_DOCUMENT_INTELLIGENCE_MAX_PAGES",
    }
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if separator and key.strip() in allowed:
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pages", required=True, help="Explicit comma-separated physical pages")
    parser.add_argument("--state", type=Path, default=ROOT / ".local/azure-pilot")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.azure.local")
    parser.add_argument("--invoke", action="store_true", help="Submit selected pages to Azure")
    args = parser.parse_args()
    pages = tuple(sorted(set(int(p) for p in args.pages.split(","))))
    if not pages or min(pages) < 1:
        parser.error("pages must be positive")
    load_credentials(args.env_file)
    args.state.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "azure-pilot-v1",
        "selected_pages": pages,
        "parsing": "not_run",
        "claims": "not_run",
        "tagging": "not_run",
        "reconciliation": "not_run",
        "semantic_accuracy": None,
        "policy_approval": None,
        "cost_usd": None,
    }
    started = time.monotonic()
    try:
        client = AzureLayoutClient.from_environment(args.state / "azure-requests.sqlite3")
        report["credentials"] = "configured_unverified"
        if args.invoke:
            if args.pdf.stat().st_size > 100 * 1024 * 1024:
                raise ParseFailure("PARSER_INPUT_LIMIT")
            content = args.pdf.read_bytes()
            digest = sha256(content).hexdigest()
            tenant = str(uuid5(NAMESPACE_URL, "proofops-azure-lab"))
            version = str(uuid5(NAMESPACE_URL, digest))
            profile = ParserProfile(
                str(uuid5(NAMESPACE_URL, digest + str(pages) + "azure-v1")),
                physical_pages=pages,
                parser_mode="azure",
                table_auxiliary=False,
                timeout_seconds=180,
                memory_bytes=1024 * 1024 * 1024,
            )
            source = SourceArtifact(
                tenant,
                version,
                version,
                digest,
                digest,
                content,
                upload_security_limits=asdict(PdfLimits.display()),
            )
            adapter = AzureLayoutParser(args.state / "prepared", client=client)
            directory = adapter._directory(source, profile)
            if directory.exists():
                graph = adapter.load_verified(source, profile, tenant_id=tenant)
                report["artifact_reused"] = True
            else:
                graph = adapter.parse(source, profile, tenant_id=tenant)
                report["artifact_reused"] = False
            report.update(
                parsing="succeeded",
                source_sha256=digest,
                blocks=len(graph.blocks),
                qualities=dict(Counter(b.quality for b in graph.blocks)),
                manifest_path=str(directory / "manifest.json"),
                usage=client.summary(),
            )
    except (AzureFailure, ParseFailure, UploadRejected) as exc:
        report.update(parsing="blocked" if not args.invoke else "failed", reason=str(exc))
    report["duration_seconds"] = round(time.monotonic() - started, 3)
    (args.state / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 2 if report["parsing"] in ("blocked", "failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
