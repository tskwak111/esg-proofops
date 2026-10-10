"""Direct Docling CPU parser with independent Upstage receipts and guarded replay."""

import json
import os
import sys
from dataclasses import asdict, replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4, uuid5

from proofops.adapters.parsing.docling_validation import audit, guarded_graph
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser, ParseFailure, _json
from proofops.application.ingest.graph_fusion import (
    CandidateBatch,
    CandidateBlock,
    CandidateEdge,
    candidates_from_snapshot,
)
from proofops.application.uploads_security import PdfLimits, QuarantinedPdf, verify_quarantined_pdf
from proofops.domain.documents import NativeSource, PageGeometry
from proofops.domain.provenance import canonical_hash

VERSION = "2.137.0"
OPTIONS = dict(
    do_ocr=False, table_mode="accurate", do_cell_matching=True, device="cpu", num_threads=2
)


def runtime_metadata(receipts, routing):
    def summary(mode):
        selected = [r for r in receipts if r["mode"] == mode]
        amounts = [r["result"].get("cost_with_vat_reserve_usd") for r in selected]
        return dict(
            selected_pages=[p for r in selected for p in r["pages"]],
            requests=len(selected),
            cache_hits=sum(r["result"].get("cache_hit") is True for r in selected),
            receipt_cost_usd=str(sum((Decimal(a) for a in amounts), Decimal(0)))
            if all(a is not None for a in amounts)
            else None,
        )

    vision = routing["vision"]
    return dict(
        upstage_parse=dict(
            standard=summary("standard"),
            enhanced=summary("enhanced"),
            enhanced_deferred=routing["deferred"],
        ),
        vision_status="candidate_only" if vision["status"] == "candidate_only" else "not_run",
        vision_parse=vision,
    )


def convert_pages(pages, source, profile):
    run = str(uuid5(UUID(profile.parse_manifest_id), "direct-docling-v1"))
    blocks, edges = [], []
    for number, record in sorted(pages.items(), key=lambda item: int(item[0])):
        page = int(number)
        expected_options = (
            dict(OPTIONS, device="cuda", num_threads=16) if profile.docling_ssh_target else OPTIONS
        )
        if (
            record["version"] != VERSION
            or record["options"] != expected_options
            or record["page"] != page
        ):
            raise ParseFailure("DOCLING_CONFIG_MISMATCH")
        document = record["document"]
        if set(map(int, document["pages"])) != {page}:
            raise ParseFailure("DOCLING_PAGE_MAPPING_INVALID")
        geometry = PageGeometry(**record["geometry"])
        size = document["pages"][number]["size"]
        if (
            abs(size["width"] - geometry.width_pt) > 0.1
            or abs(size["height"] - geometry.height_pt) > 0.1
        ):
            raise ParseFailure("DOCLING_PAGE_GEOMETRY_MISMATCH")

        def append(item, identifier, kind, *, box=None, table=None, context=()):
            text = item.get("text", "")
            provenance = item.get("prov", [])
            if box is None and len(provenance) == 1:
                if provenance[0]["page_no"] != page:
                    raise ParseFailure("DOCLING_PAGE_MAPPING_INVALID")
                box = provenance[0].get("bbox")
            native = None
            if box:
                if box["coord_origin"] == "BOTTOMLEFT":
                    native = (box["l"], box["b"], box["r"], box["t"])
                elif box["coord_origin"] == "TOPLEFT":
                    native = (
                        box["l"],
                        geometry.height_pt - box["b"],
                        box["r"],
                        geometry.height_pt - box["t"],
                    )
                else:
                    raise ParseFailure("DOCLING_COORDINATE_SYSTEM_INVALID")
            blocks.append(
                CandidateBlock(
                    kind,
                    NativeSource(
                        source.document_version_id,
                        profile.parse_manifest_id,
                        run,
                        identifier,
                        page,
                        None,
                        native,
                        "pdf_bottom_left_points",
                        text,
                        0,
                        len(text),
                    ),
                    geometry,
                    tuple(context),
                    table_native_id=table,
                    row_number=item.get("start_row_offset_idx"),
                    column_number=item.get("start_col_offset_idx"),
                    row_span=item.get("row_span"),
                    column_span=item.get("col_span"),
                )
            )
            if table:
                edges.append(CandidateEdge(identifier, table, "table_parent"))

        for index, table in enumerate(document.get("tables", [])):
            identifier = f"p{page}-table-{index}"
            append(table, identifier, "table")
            occupied = set()
            for ci, cell in enumerate(table["data"]["table_cells"]):
                row, col = cell["start_row_offset_idx"], cell["start_col_offset_idx"]
                end_row, end_col = cell["end_row_offset_idx"], cell["end_col_offset_idx"]
                if not (
                    0 <= row < end_row <= table["data"]["num_rows"]
                    and 0 <= col < end_col <= table["data"]["num_cols"]
                    and end_row - row == cell["row_span"]
                    and end_col - col == cell["col_span"]
                ):
                    raise ParseFailure("DOCLING_TABLE_GRID_INVALID")
                slots = {(r, c) for r in range(row, end_row) for c in range(col, end_col)}
                context = ("table_grid_overlap",) if occupied & slots else ()
                occupied.update(slots)
                append(
                    cell,
                    f"{identifier}-c{ci}",
                    "table_cell",
                    box=cell.get("bbox"),
                    table=identifier,
                    context=context,
                )
        for index, item in enumerate(document.get("texts", [])):
            label = item.get("label")
            kind = {
                "section_header": "heading",
                "title": "heading",
                "caption": "caption",
                "footnote": "footnote",
                "page_header": "unknown",
                "page_footer": "unknown",
            }.get(label, "paragraph")
            append(item, f"p{page}-text-{index}", kind)
        for index, picture in enumerate(document.get("pictures", [])):
            append(picture, f"p{page}-figure-{index}", "figure")
    return CandidateBatch(
        source.tenant_id,
        source.document_version_id,
        profile.parse_manifest_id,
        source.sha256,
        run,
        "docling",
        VERSION,
        "docling",
        profile.config_hash(),
        tuple(blocks),
        tuple(edges),
        source.synthetic,
    )


class DoclingParser:
    def __init__(self, artifact_root, *, upstage_probe=None):
        self.artifact_root = Path(artifact_root).resolve()
        self.upstage_probe = upstage_probe

    def _directory(self, source, profile):
        return (
            self.artifact_root
            / source.tenant_id
            / source.document_version_id
            / profile.parse_manifest_id
        )

    def _identity(self, source, profile):
        return dict(
            schema_version="docling-manifest-v1",
            source_sha256=source.sha256,
            tenant_id=source.tenant_id,
            document_id=source.document_id,
            document_version_id=source.document_version_id,
            object_version_id=source.object_version_id,
            parse_manifest_id=profile.parse_manifest_id,
            parser_profile=json.loads(_json(profile.invocation_snapshot())),
            parser_version=VERSION,
            options=dict(OPTIONS, device="cuda", num_threads=16)
            if profile.docling_ssh_target
            else OPTIONS,
            synthetic_source=source.synthetic,
        )

    def prepare_pages(self, source, profile, selected):
        if profile.docling_ssh_target:
            from proofops.adapters.parsing.docling_ssh import fetch_pages

            return fetch_pages(source, profile, selected, self.artifact_root)["pages"]
        return {str(p): self._local_page(source, profile, p) for p in selected}

    def _local_page(self, source, profile, number):
        child = Path(__file__).with_name("docling_child.py").resolve()
        cache_root = self.artifact_root / "docling-cache" / source.tenant_id
        cache_root.mkdir(parents=True, exist_ok=True)
        identity = dict(
            source=source.sha256,
            page=number,
            version=VERSION,
            options=OPTIONS,
            worker_sha256=sha256(child.read_bytes()).hexdigest(),
        )
        cache = cache_root / (canonical_hash(identity) + ".json")
        if cache.exists():
            entry = json.loads(cache.read_bytes())
            if entry["identity"] != identity or canonical_hash(entry["result"]) != entry["sha256"]:
                raise ParseFailure("DOCLING_CACHE_INTEGRITY_MISMATCH")
            return entry["result"]
        with TemporaryDirectory(dir=cache_root, prefix="dl-") as temporary:
            work = Path(temporary)
            (work / "source.pdf").write_bytes(source.content)
            (work / "request.json").write_bytes(_json(dict(page=number)))
            env = {
                k: os.environ[k]
                for k in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME")
                if k in os.environ
            }
            env.update(
                PYTHONDONTWRITEBYTECODE="1",
                OMP_NUM_THREADS="2",
                MKL_NUM_THREADS="2",
                HF_HOME=str(self.artifact_root.parent / "docling-model-cache"),
                HF_HUB_DISABLE_TELEMETRY="1",
            )
            # Operator may explicitly reuse an already downloaded model cache.
            if os.environ.get("DOCLING_MODEL_CACHE"):
                env["HF_HOME"] = os.environ["DOCLING_MODEL_CACHE"]
            executable = profile.docling_python or sys.executable
            OpenDataLoaderParser._execute(
                [executable, "-I", str(child), str(work)], work, env, profile
            )
            result = json.loads((work / "result.json").read_bytes())
            entry = dict(identity=identity, result=result, sha256=canonical_hash(result))
            temp = cache.with_name(uuid4().hex + ".tmp")
            temp.write_bytes(_json(entry))
            os.replace(temp, cache)
            return result

    def _provider(self, source, pages, mode):
        from proofops.adapters.parsing.upstage_document import MODEL, selected_pdf

        root = self.artifact_root / "docling-upstage-cache" / source.tenant_id
        root.mkdir(parents=True, exist_ok=True)
        identity = dict(source=source.sha256, pages=list(pages), mode=mode, model=MODEL)
        path = root / (canonical_hash(identity) + ".json")
        if path.exists():
            entry = json.loads(path.read_bytes())
            result = entry["result"]
            if (
                entry["identity"] != identity
                or canonical_hash(result["raw_batches"]) != result["response_sha256"]
            ):
                raise ParseFailure("UPSTAGE_CACHE_INTEGRITY_MISMATCH")
            return dict(result, cache_hit=True)
        # Persist intent before submitting. An interrupted/unknown POST is never silently retried.
        intent = path.with_suffix(".pending")
        request_id = str(uuid4())
        try:
            with intent.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(dict(identity, local_request_id=request_id)))
        except FileExistsError:
            raise ParseFailure("UPSTAGE_PENDING_REQUEST_REQUIRES_RECONCILIATION") from None
        try:
            result = self.upstage_probe.parse_async(
                selected_pdf(source.content, pages), request_id=request_id, mode=mode
            )
        except ValueError as error:
            if str(error) == "BUDGET_EXHAUSTED":
                intent.unlink()  # Reservation refused: no provider request was sent.
            raise
        result = dict(result, local_request_id=request_id)
        if canonical_hash(result["raw_batches"]) != result["response_sha256"]:
            raise ParseFailure("UPSTAGE_RESPONSE_INTEGRITY_MISMATCH")
        temp = path.with_name(uuid4().hex + ".tmp")
        temp.write_bytes(_json(dict(identity=identity, result=result)))
        os.replace(temp, path)
        intent.unlink()
        return dict(result, cache_hit=False)

    def parse(self, source, profile, *, tenant_id):
        if source.tenant_id != tenant_id:
            raise ParseFailure("NOT_FOUND")
        if sha256(source.content).hexdigest() != source.sha256:
            raise ParseFailure("SOURCE_INTEGRITY_MISMATCH")
        if self.upstage_probe is None:
            raise ParseFailure("UPSTAGE_RUNTIME_REQUIRED")
        verified = verify_quarantined_pdf(
            QuarantinedPdf(
                tenant_id,
                source.document_version_id,
                source.object_version_id,
                source.content,
                len(source.content),
                source.sha256,
            ),
            PdfLimits(**source.upload_security_limits)
            if source.upload_security_limits
            else PdfLimits(max_bytes=profile.max_bytes, timeout_seconds=profile.timeout_seconds),
            tenant_id=tenant_id,
        )
        selected = profile.physical_pages or tuple(range(1, verified.page_count + 1))
        if any(p > verified.page_count for p in selected):
            raise ParseFailure("PAGE_SELECTION_INVALID")
        final = self._directory(source, profile)
        if final.exists():
            raise ParseFailure("PARSE_MANIFEST_EXISTS")
        pages = self.prepare_pages(source, profile, selected)
        local = convert_pages(pages, source, profile)
        batches, receipts = [local], []
        from proofops.adapters.parsing.upstage_document import candidate_batch

        def call(numbers, mode):
            for start in range(0, len(numbers), 10):
                chunk = tuple(numbers[start : start + 10])
                result = self._provider(source, chunk, mode)
                batch, metrics = candidate_batch(
                    source,
                    profile,
                    chunk,
                    result["raw_batches"],
                    mode=mode,
                    config_hash=profile.config_hash(),
                )
                batches.append(batch)
                receipts.append(dict(pages=chunk, mode=mode, result=result, metrics=metrics))

        call(selected, "standard")
        first = audit(batches, pages)
        conflicts = sorted(
            {
                r["page"]
                for r in first
                if r["reason"]
                in {"parse_conflict", "numeric_not_in_native_region", "crosscheck_missing"}
            }
        )
        deferred = None
        if conflicts:
            try:
                call(conflicts, "enhanced")
            except ValueError as error:
                # Preserve the local/standard evidence and a review outcome when quota is exhausted.
                if str(error) not in {
                    "BUDGET_EXHAUSTED",
                    "UPSTAGE_PENDING_REQUEST_REQUIRES_RECONCILIATION",
                }:
                    raise
                deferred = str(error)
        records = audit(batches, pages)
        graph = guarded_graph(batches, records, tenant_id=tenant_id, pages=pages)
        chart_pages = sorted(
            {r["page"] for r in records if r["reason"] == "chart_requires_vision_review"}
        )
        vision = dict(status="not_requested", pages=chart_pages)
        if chart_pages and profile.vision_parse != "off":
            from proofops.adapters.parsing.gemini_vision import parse_pages

            key_name = "OPENROUTER_API_KEY"
            if profile.vision_model == "gpt-6-luna":
                from proofops.adapters.parsing.openai_vision import parse_pages

                key_name = "OPENAI_API_KEY"
            if os.environ.get(key_name):
                try:
                    batch, metrics = parse_pages(
                        source,
                        replace(profile, vision_parse="all"),
                        graph,
                        chart_pages,
                        self.artifact_root / "vision-cache",
                        key=os.environ[key_name],
                    )
                    # Vision is review evidence, not text-layer approved numeric output.
                    vision = dict(
                        status="candidate_only",
                        metrics=metrics,
                        candidates=asdict(batch) if batch else None,
                    )
                except (ValueError, OSError, TimeoutError) as error:
                    vision = dict(
                        status="failed_requires_review",
                        pages=chart_pages,
                        error_type=type(error).__name__,
                        http_status=getattr(error, "code", None),
                    )
            else:
                vision = dict(status="blocked_missing_vision_key", pages=chart_pages)
        final.parent.mkdir(parents=True, exist_ok=True)
        artifacts = dict(
            pages=pages,
            candidates=[asdict(b) for b in batches],
            audit=records,
            graph=graph.to_dict(),
            quality=[asdict(i) for i in graph.issues],
            receipts=receipts,
            routing=dict(enhanced_pages=conflicts, deferred=deferred, vision=vision),
        )
        with TemporaryDirectory(dir=final.parent, prefix="dl-") as temporary:
            work = Path(temporary)
            hashes = {}
            for name, value in artifacts.items():
                data = _json(value)
                (work / (name + ".json")).write_bytes(data)
                hashes[name + ".json"] = sha256(data).hexdigest()
            manifest = dict(
                self._identity(source, profile),
                artifacts=hashes,
                selected_physical_pages=selected,
                **runtime_metadata(receipts, artifacts["routing"]),
            )
            (work / "manifest.json").write_bytes(_json(manifest))
            if sum(p.stat().st_size for p in work.iterdir()) > profile.max_output_bytes:
                raise ParseFailure("PARSER_OUTPUT_LIMIT")
            os.rename(work, final)
        return graph

    def load_verified(self, source, profile, *, tenant_id, manifest_sha256=None):
        if source.tenant_id != tenant_id:
            raise ParseFailure("NOT_FOUND")
        if sha256(source.content).hexdigest() != source.sha256:
            raise ParseFailure("SOURCE_INTEGRITY_MISMATCH")
        directory = self._directory(source, profile)
        try:
            manifest_path = directory / "manifest.json"
            if (
                directory.is_symlink()
                or manifest_path.is_symlink()
                or manifest_path.stat().st_size > profile.max_output_bytes
            ):
                raise ValueError("unsafe manifest")
            raw = manifest_path.read_bytes()
            if manifest_sha256 and sha256(raw).hexdigest() != manifest_sha256:
                raise ValueError("manifest hash")
            manifest = json.loads(raw)
            if any(manifest.get(k) != v for k, v in self._identity(source, profile).items()):
                raise ValueError("identity")
            required = {
                n + ".json"
                for n in ("pages", "candidates", "audit", "graph", "quality", "receipts", "routing")
            }
            if set(manifest["artifacts"]) != required:
                raise ValueError("artifact set")
            data, total = {}, len(raw)
            for name in required:
                path = directory / name
                total += path.stat().st_size
                if path.is_symlink() or total > profile.max_output_bytes:
                    raise ValueError("unsafe artifact")
                value = path.read_bytes()
                if sha256(value).hexdigest() != manifest["artifacts"][name]:
                    raise ValueError("artifact hash")
                data[name] = json.loads(value)
            selected = manifest["selected_physical_pages"]
            if any(
                manifest.get(k) != v
                for k, v in runtime_metadata(data["receipts.json"], data["routing.json"]).items()
            ):
                raise ValueError("runtime metadata")
            if (profile.physical_pages and selected != list(profile.physical_pages)) or set(
                map(int, data["pages.json"])
            ) != set(selected):
                raise ValueError("page selection")
            batches = candidates_from_snapshot(data["candidates.json"])
            local = convert_pages(data["pages.json"], source, profile)
            if _json(asdict(local)) != _json(asdict(batches[0])):
                raise ValueError("local replay")
            from proofops.adapters.parsing.upstage_document import candidate_batch

            if len(batches) != 1 + len(data["receipts.json"]):
                raise ValueError("provider count")
            covered = []
            for batch, receipt in zip(batches[1:], data["receipts.json"], strict=True):
                result = receipt["result"]
                if canonical_hash(result["raw_batches"]) != result["response_sha256"]:
                    raise ValueError("receipt hash")
                reconstructed, _ = candidate_batch(
                    source,
                    profile,
                    tuple(receipt["pages"]),
                    result["raw_batches"],
                    mode=receipt["mode"],
                    config_hash=profile.config_hash(),
                )
                reconstructed = replace(
                    reconstructed,
                    parser_run_id=batch.parser_run_id,
                    blocks=tuple(
                        replace(b, source=replace(b.source, parser_run_id=batch.parser_run_id))
                        for b in reconstructed.blocks
                    ),
                )
                if _json(asdict(reconstructed)) != _json(asdict(batch)):
                    raise ValueError("provider replay")
                if receipt["mode"] == "standard":
                    covered.extend(receipt["pages"])
            if sorted(covered) != selected:
                raise ValueError("standard coverage")
            records = audit(batches, data["pages.json"])
            graph = guarded_graph(batches, records, tenant_id=tenant_id, pages=data["pages.json"])
            if (
                _json(records) != _json(data["audit.json"])
                or _json(graph.to_dict()) != _json(data["graph.json"])
                or _json([asdict(i) for i in graph.issues]) != _json(data["quality.json"])
            ):
                raise ValueError("guard replay")
            return graph
        except (OSError, ValueError, KeyError, TypeError):
            raise ParseFailure("PARSER_ARTIFACT_INTEGRITY_MISMATCH") from None
