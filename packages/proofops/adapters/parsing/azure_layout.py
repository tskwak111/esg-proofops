"""Azure adapter for the existing immutable candidate graph and replay boundary.

Provider coordinates locate candidates; they do not approve source truth.
All PDF geometry comes from the uploaded PDF, never a fabricated page rectangle.
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid5

from proofops.adapters.parsing.azure_client import (
    API_VERSION,
    MODEL,
    AzureFailure,
    AzureLayoutClient,
)
from proofops.adapters.parsing.opendataloader import (
    OpenDataLoaderParser,
    ParseFailure,
    _child_limits,
    _json,
    _transform_box,
    _with_quality_issues,
)
from proofops.application.ingest.geometry import invert_affine
from proofops.application.ingest.graph_fusion import (
    CandidateBatch,
    CandidateBlock,
    CandidateEdge,
    candidates_from_snapshot,
    fuse_candidates,
)
from proofops.application.uploads_security import PdfLimits, QuarantinedPdf, verify_quarantined_pdf
from proofops.domain.documents import NativeSource, PageGeometry


def convert_result(result, source, profile, geometries):
    if result.get("modelId") != MODEL or result.get("apiVersion") != API_VERSION:
        raise ParseFailure("AZURE_MODEL_VERSION_MISMATCH")
    if result.get("stringIndexType") != "unicodeCodePoint":
        raise ParseFailure("AZURE_STRING_INDEX_UNSUPPORTED")
    pages = {p["pageNumber"]: p for p in result["pages"]}
    selected = profile.physical_pages or tuple(sorted(geometries))
    if len(pages) != len(result["pages"]) or set(pages) != set(selected):
        raise ParseFailure("AZURE_PAGE_COVERAGE_MISMATCH")
    run_id = str(uuid5(UUID(profile.parse_manifest_id), "azure-layout-v1"))
    blocks, edges = [], []
    content = result["content"]

    def append(item, identifier, kind, *, table=None, context=()):
        text = item.get("content", "")
        if not isinstance(text, str):
            raise ParseFailure("AZURE_TEXT_INVALID")
        spans = item.get("spans", [])
        if text:
            if not spans or any(
                type(s.get("offset")) is not int
                or type(s.get("length")) is not int
                or s["offset"] < 0
                or s["length"] < 0
                or s["offset"] + s["length"] > len(content)
                for s in spans
            ):
                raise ParseFailure("AZURE_SPAN_INVALID")
            if "".join(content[s["offset"] : s["offset"] + s["length"]] for s in spans) != text:
                raise ParseFailure("AZURE_SPAN_TEXT_MISMATCH")
        regions = item.get("boundingRegions", [])
        if not regions:
            # Retain a source only when a physical page is known; never guess page 1.
            raise ParseFailure("AZURE_PAGE_LOCATION_MISSING")
        # Multi-page text cannot be attributed in full to either page. Keep it
        # unlocated on its first explicit page for review, rather than miscite it.
        page = regions[0]["pageNumber"]
        if page not in pages:
            raise ParseFailure("AZURE_PAGE_MAPPING_INVALID")
        geometry = PageGeometry(**geometries[page])
        info = pages[page]
        if info.get("unit") != "inch":
            raise ParseFailure("AZURE_PDF_UNIT_UNSUPPORTED")
        if not (
            math.isclose(info["width"] * 72, geometry.width_pt, abs_tol=1)
            and math.isclose(info["height"] * 72, geometry.height_pt, abs_tol=1)
        ):
            raise ParseFailure("AZURE_PDF_GEOMETRY_MISMATCH")
        box = None
        if len(regions) == 1 and regions[0].get("polygon"):
            polygon = regions[0]["polygon"]
            if (
                len(polygon) < 8
                or len(polygon) % 2
                or any(
                    isinstance(x, bool) or not isinstance(x, int | float) or not math.isfinite(x)
                    for x in polygon
                )
            ):
                raise ParseFailure("AZURE_POLYGON_INVALID")
            xs, ys = polygon[::2], polygon[1::2]
            candidate = (min(xs) * 72, min(ys) * 72, max(xs) * 72, max(ys) * 72)
            if not (
                0 <= candidate[0] < candidate[2] <= geometry.width_pt + 0.1
                and 0 <= candidate[1] < candidate[3] <= geometry.height_pt + 0.1
            ):
                raise ParseFailure("AZURE_POLYGON_OUTSIDE_PAGE")
            box = candidate
        native_box = _transform_box(box, invert_affine(geometry.to_canonical_affine()))
        native = NativeSource(
            source.document_version_id,
            profile.parse_manifest_id,
            run_id,
            identifier,
            page,
            None,
            native_box,
            "pdf_bottom_left_points",
            text,
            0,
            len(text),
        )
        blocks.append(
            CandidateBlock(
                kind,
                native,
                geometry,
                tuple(context),
                parser_bbox=box,
                parser_coordinate_system="azure_display_top_left_points",
                parser_to_canonical=(1, 0, 0, 1, 0, 0),
                table_native_id=table,
                row_number=item.get("rowIndex"),
                column_number=item.get("columnIndex"),
                row_span=item.get("rowSpan", 1) if table else None,
                column_span=item.get("columnSpan", 1) if table else None,
            )
        )
        if table:
            edges.append(CandidateEdge(identifier, table, "table_parent"))

    table_ranges = []
    for index, table in enumerate(result.get("tables", [])):
        identifier = f"table-{index}"
        append(dict(table, content="", spans=[]), identifier, "table")
        table_ranges.extend(
            (s["offset"], s["offset"] + s["length"]) for s in table.get("spans", [])
        )
        cells = table.get("cells", [])
        occupied = set()
        for number, cell in enumerate(cells):
            row, column = cell.get("rowIndex"), cell.get("columnIndex")
            rows, columns = cell.get("rowSpan", 1), cell.get("columnSpan", 1)
            if (
                any(type(v) is not int or v < 0 for v in (row, column))
                or any(type(v) is not int or not 1 <= v <= 1000 for v in (rows, columns))
                or row + rows > table["rowCount"]
                or column + columns > table["columnCount"]
            ):
                raise ParseFailure("AZURE_TABLE_GRID_INVALID")
            positions = {
                (r, c) for r in range(row, row + rows) for c in range(column, column + columns)
            }
            if occupied & positions:
                raise ParseFailure("AZURE_TABLE_GRID_OVERLAP")
            occupied.update(positions)
            headers = []
            for header in cells:
                if header.get("kind") == "columnHeader" and (
                    header["columnIndex"]
                    <= cell["columnIndex"]
                    < header["columnIndex"] + header.get("columnSpan", 1)
                ):
                    headers.append("column_header: " + header["content"])
                if header.get("kind") == "rowHeader" and (
                    header["rowIndex"]
                    <= cell["rowIndex"]
                    < header["rowIndex"] + header.get("rowSpan", 1)
                ):
                    headers.append("row_header: " + header["content"])
            append(
                cell,
                f"{identifier}-cell-{number}",
                "table_cell",
                table=identifier,
                context=tuple(headers),
            )
        if table.get("caption"):
            caption_id = identifier + "-caption"
            append(table["caption"], caption_id, "caption")
            edges.append(CandidateEdge(caption_id, identifier, "caption_of"))
        for number, note in enumerate(table.get("footnotes", [])):
            note_id = f"{identifier}-footnote-{number}"
            append(note, note_id, "footnote")
            edges.append(CandidateEdge(note_id, identifier, "footnote_of"))
    for index, paragraph in enumerate(result.get("paragraphs", [])):
        spans = paragraph.get("spans", [])
        if spans and all(
            any(a <= s["offset"] and s["offset"] + s["length"] <= b for a, b in table_ranges)
            for s in spans
        ):
            continue
        role = paragraph.get("role")
        kind = (
            "heading"
            if role in ("title", "sectionHeading")
            else ("footnote" if role == "footnote" else "paragraph")
        )
        append(paragraph, f"paragraph-{index}", kind, context=(f"role: {role}",) if role else ())
    if not blocks:
        raise ParseFailure("AZURE_NO_CONTENT_REQUIRES_REVIEW")
    return CandidateBatch(
        source.tenant_id,
        source.document_version_id,
        profile.parse_manifest_id,
        source.sha256,
        run_id,
        "azure-layout",
        API_VERSION,
        "azure",
        profile.config_hash(),
        tuple(blocks),
        tuple(edges),
        source.synthetic,
    )


class AzureLayoutParser:
    def __init__(self, artifact_root, *, client=None):
        self.artifact_root, self.client = Path(artifact_root), client

    def _directory(self, source, profile):
        return (
            self.artifact_root
            / source.tenant_id
            / source.document_version_id
            / profile.parse_manifest_id
        )

    def _identity(self, source, profile):
        return dict(
            schema_version="azure-layout-manifest-v1",
            tenant_id=source.tenant_id,
            document_id=source.document_id,
            document_version_id=source.document_version_id,
            source_sha256=source.sha256,
            object_version_id=source.object_version_id,
            parse_manifest_id=profile.parse_manifest_id,
            parser_config=profile.config_snapshot(),
            parser_profile=json.loads(_json(profile.invocation_snapshot())),
            synthetic_source=source.synthetic,
        )

    def parse(self, source, profile, *, tenant_id):
        if source.tenant_id != tenant_id:
            raise ParseFailure("NOT_FOUND")
        if sha256(source.content).hexdigest() != source.sha256:
            raise ParseFailure("SOURCE_INTEGRITY_MISMATCH")
        if (
            profile.vision_parse != "off"
            or profile.table_source_policy_sha256
            or profile.table_structure_repair
        ):
            raise ParseFailure("AZURE_PROFILE_OPTIONS_UNSUPPORTED")
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
        pages = profile.physical_pages or tuple(range(1, verified.page_count + 1))
        if any(page > verified.page_count for page in pages):
            raise ParseFailure("PAGE_SELECTION_INVALID")
        final = self._directory(source, profile)
        if final.exists():
            raise ParseFailure("PARSE_MANIFEST_EXISTS")
        final.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=final.parent, prefix="az-") as temporary:
            work = Path(temporary)
            (work / "source.pdf").write_bytes(source.content)
            (work / "request.json").write_bytes(
                _json(
                    {
                        "pages": pages,
                        "limits": {
                            "timeout_seconds": profile.timeout_seconds,
                            "max_output_bytes": profile.max_output_bytes,
                        },
                    }
                )
            )
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
            if os.name == "nt":
                env["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
            OpenDataLoaderParser._execute(
                [sys.executable, "-I", str(Path(__file__).resolve()), str(work)], work, env, profile
            )
            geometries = {
                int(k): v for k, v in json.loads((work / "geometry.json").read_bytes()).items()
            }
            try:
                client = self.client or AzureLayoutClient.from_environment(
                    self.artifact_root.parent / "azure-requests.sqlite3"
                )
                result, usage = client.analyze(source.content, pages, scope=tenant_id)
            except AzureFailure as exc:
                raise ParseFailure(str(exc)) from None
            batch = convert_result(result, source, profile, geometries)
            graph = _with_quality_issues(
                fuse_candidates((batch,), tenant_id=tenant_id), pages, profile
            )
            artifacts = {
                "response.json": result,
                "candidates.json": [asdict(batch)],
                "graph.json": graph.to_dict(),
                "usage.json": usage,
            }
            for name, value in artifacts.items():
                (work / name).write_bytes(_json(value))
            names = (*artifacts, "geometry.json")
            manifest = dict(
                self._identity(source, profile),
                artifacts={name: sha256((work / name).read_bytes()).hexdigest() for name in names},
            )
            (work / "manifest.json").write_bytes(_json(manifest))
            (work / "source.pdf").unlink()
            (work / "request.json").unlink()
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
            if directory.is_symlink() or (directory / "manifest.json").is_symlink():
                raise ValueError("unsafe manifest")
            if (directory / "manifest.json").stat().st_size > profile.max_output_bytes:
                raise ValueError("manifest too large")
            raw = (directory / "manifest.json").read_bytes()
            if manifest_sha256 and sha256(raw).hexdigest() != manifest_sha256:
                raise ValueError("manifest changed")
            manifest = json.loads(raw)
            if any(manifest.get(k) != v for k, v in self._identity(source, profile).items()):
                raise ValueError("identity changed")
            required = {
                "response.json",
                "candidates.json",
                "graph.json",
                "usage.json",
                "geometry.json",
            }
            if set(manifest["artifacts"]) != required:
                raise ValueError("artifact set changed")
            data = {}
            for name in required:
                path = directory / name
                if path.is_symlink() or path.stat().st_size > profile.max_output_bytes:
                    raise ValueError("unsafe artifact")
                value = path.read_bytes()
                if sha256(value).hexdigest() != manifest["artifacts"][name]:
                    raise ValueError("artifact changed")
                data[name] = json.loads(value)
            geometries = {int(k): v for k, v in data["geometry.json"].items()}
            batch = convert_result(data["response.json"], source, profile, geometries)
            if _json([asdict(batch)]) != _json(data["candidates.json"]):
                raise ValueError("candidate replay mismatch")
            graph = fuse_candidates(
                candidates_from_snapshot(data["candidates.json"]), tenant_id=tenant_id
            )
            graph = _with_quality_issues(graph, tuple(geometries), profile)
            if _json(graph.to_dict()) != _json(data["graph.json"]):
                raise ValueError("graph replay mismatch")
            return graph
        except (OSError, ValueError, KeyError, TypeError):
            raise ParseFailure("PARSER_ARTIFACT_INTEGRITY_MISMATCH") from None


def _geometry_child(work):
    import pypdfium2 as pdfium

    request = json.loads((work / "request.json").read_bytes())
    _child_limits(request["limits"])
    result = {}
    with pdfium.PdfDocument(work / "source.pdf") as document:
        for number in request["pages"]:
            page = document.get_page(number - 1)
            try:
                crop = tuple(float(v) for v in page.get_bbox())
                rotation = page.get_rotation() % 360
                width, height = crop[2] - crop[0], crop[3] - crop[1]
                if rotation in (90, 270):
                    width, height = height, width
                result[number] = asdict(PageGeometry(width, height, rotation, crop))
            finally:
                page.close()
    (work / "geometry.json").write_bytes(_json(result))


if __name__ == "__main__":
    _geometry_child(Path(sys.argv[1]))
