"""Original glyph/font proof for a narrow mislabeled strategy section title."""

import io
import json
from contextlib import closing
from dataclasses import asdict, replace
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from statistics import median
from uuid import UUID, uuid5

import pdfplumber
import pypdfium2 as pdfium
import pypdfium2.raw as raw

from proofops.application.ingest.h1_boundaries import POLICY
from proofops.domain.provenance import canonical_hash


class NativeTitleCatalog:
    def __init__(self, graph, source):
        if sha256(source).hexdigest() != graph.source_sha256:
            raise ValueError("H1_TITLE_SOURCE_MISMATCH")
        self.graph, self.source, self.pages = graph, source, {}

    def proof(self, source_id):
        from proofops.application.ingest.h1_boundaries import strategy_title

        block = next(b for b in self.graph.blocks if b.source_id == source_id)
        result = dict(
            source_id=source_id,
            source_sha256=self.graph.source_sha256,
            quote_sha256=canonical_hash(block.normalized_text),
            is_title=False,
            policy_sha256=canonical_hash(POLICY),
        )
        if (
            block.kind != "paragraph"
            or block.winner is None
            or block.bbox is None
            or not strategy_title(block.normalized_text)
        ):
            return result
        if block.page_num not in self.pages:
            with pdfplumber.open(io.BytesIO(self.source)) as doc:
                page = doc.pages[block.page_num - 1]
                self.pages[block.page_num] = (page.chars, page.rotation)
        chars, rotation = self.pages[block.page_num]
        if rotation:
            return result
        from proofops.adapters.parsing.source_recovery import _provider_box

        box = block.bbox
        font_box = _provider_box(block.candidates[block.winner])
        local = [
            c
            for c in chars
            if font_box[0] <= (c["x0"] + c["x1"]) / 2 <= font_box[2]
            and font_box[1] <= (c["top"] + c["bottom"]) / 2 <= font_box[3]
        ]
        from proofops.adapters.local.claim_source_verification_v3 import _native_page, _quote_glyphs

        with pdfium.PdfDocument(self.source) as native:
            glyphs = _quote_glyphs(
                _native_page(native, block.page_num), block.normalized_text, box, []
            )
        if not glyphs:
            return result

        def compact(text):
            return "".join(text.split())

        if not local or compact("".join(c["text"] for c in local)) != compact(
            block.normalized_text
        ):
            return result
        body = [c["size"] for c in chars if c["text"].strip()]
        title = [c["size"] for c in local if c["text"].strip()]
        if body and title and median(title) > median(body) * 1.1:
            result.update(
                is_title=True,
                parser_bbox=list(box),
                declared_region=list(font_box),
                body_font=median(body),
                title_font=median(title),
            )
        return result


def native_figure_candidates(graph, source):
    """Derive located native bullet candidates; never approve captions or evidence.

    Call only for a new QC opt-in extraction revision. Original blocks, raw
    captions and their source IDs remain intact; the receipt pins the new graph.
    """
    from proofops.adapters.local.claim_source_verification_v3 import _native_page, _quote_glyphs
    from proofops.adapters.parsing.source_recovery import _provider_box
    from proofops.application.ingest.graph_fusion import (
        CandidateEdge,
        CanonicalBlock,
        CanonicalEdge,
    )
    from proofops.application.ingest.k6_coverage import (
        FIGURE_CONTEXT_MARKER,
        FIGURE_MARKER,
        FIGURE_POLICY,
        native_figure_bullets,
    )
    from proofops.application.ingest.normalize import _validate

    _validate(graph, graph.tenant_id)
    if sha256(source).hexdigest() != graph.source_sha256:
        raise ValueError("QC_NATIVE_FIGURE_SOURCE_MISMATCH")
    policy_sha = canonical_hash(FIGURE_POLICY)
    receipt = dict(
        policy=FIGURE_POLICY,
        policy_sha256=policy_sha,
        builder=native_figure_builder_policy(),
        source_sha256=graph.source_sha256,
        input_graph_sha256=canonical_hash(asdict(graph)),
        candidates=[],
        unresolved=[],
    )
    additions, edges, by_run, pages = [], [], {}, {}
    existing = {
        (b.page_num, "".join(b.raw_text.split())) for b in graph.blocks if b.kind != "figure"
    }
    with pdfium.PdfDocument(source) as document:
        for block in graph.blocks:
            if (
                block.kind != "figure"
                or block.winner is None
                or block.quality
                in (
                    "conflicted",
                    "unreadable",
                )
            ):
                continue
            candidate = block.candidates[block.winner]
            if FIGURE_CONTEXT_MARKER in candidate.context:
                continue  # interpretation blocks are never a second candidate origin
            box, geometry = _provider_box(candidate), candidate.geometry
            if (
                box is None
                or geometry.rotation
                or tuple(geometry.crop_box[:2]) != (0, 0)
                or not 0 <= box[0] < box[2] <= geometry.width_pt
                or not 0 <= box[1] < box[3] <= geometry.height_pt
            ):
                receipt["unresolved"].append(dict(source_id=block.source_id, reason="geometry"))
                continue
            if block.page_num not in pages:
                with closing(document[block.page_num - 1]) as page:
                    if (
                        page.get_rotation()
                        or tuple(page.get_cropbox()[:2]) != (0, 0)
                        or page.get_cropbox() != page.get_mediabox()
                        or abs(page.get_width() - geometry.width_pt) > 0.001
                        or abs(page.get_height() - geometry.height_pt) > 0.001
                    ):
                        pages[block.page_num] = (None, "")
                    else:
                        with closing(page.get_textpage()) as textpage:
                            count = textpage.count_chars()
                            text = (
                                "".join(
                                    chr(raw.FPDFText_GetUnicode(textpage, i)) for i in range(count)
                                )
                                if 0 < count <= 20000
                                else ""
                            )
                        pages[block.page_num] = (_native_page(document, block.page_num), text)
            glyphs, text = pages[block.page_num]
            if not glyphs:
                receipt["unresolved"].append(dict(source_id=block.source_id, reason="native_text"))
                continue
            # Split at any outside glyph or backward/large vertical jump. Never
            # delete another column's text and manufacture adjacency.
            groups, current, previous, clipped = [], [], None, False
            for glyph in glyphs:
                a = glyph["bbox"]
                inside = box[0] <= a[0] < a[2] <= box[2] and box[1] <= a[1] < a[3] <= box[3]
                intersects = max(box[0], a[0]) < min(box[2], a[2]) and max(box[1], a[1]) < min(
                    box[3], a[3]
                )
                clipped |= intersects and not inside
                center = (a[1] + a[3]) / 2
                jump = previous is not None and not -4 <= center - previous <= 24
                if not inside or jump:
                    if current:
                        groups.append(current)
                    current, previous = [], None
                if inside:
                    current.append(glyph)
                    previous = center
            if current:
                groups.append(current)
            if (
                clipped
                or len(groups) > FIGURE_POLICY["max_context_groups"]
                or sum(group[-1]["index"] + 2 - group[0]["index"] for group in groups)
                > FIGURE_POLICY["max_chars"]
            ):
                receipt["unresolved"].append(
                    dict(source_id=block.source_id, reason="native_context_ambiguous")
                )
                continue
            # Each group is its own contiguous native slice and located SourceRef.
            # Preserve ALL groups, including headings and distant trailing limits;
            # no synthesized adjacency, semantic inference or evidence authority.
            context_blocks = []
            run = candidate.source.parser_run_id
            family = next(b.parser_family for b in graph.candidates if b.parser_run_id == run)
            for group in groups:
                offset, end = group[0]["index"], group[-1]["index"] + 1
                ident = (
                    "qc-context-"
                    + canonical_hash(
                        dict(
                            origin=block.source_id, start=offset, end=end, policy_sha256=policy_sha
                        )
                    )[:24]
                )
                bounds = tuple(
                    fn(g["bbox"][i] for g in group) for i, fn in enumerate((min, min, max, max))
                )
                quote = text[offset:end]
                native = replace(
                    candidate.source,
                    source_native_id=ident,
                    raw_text=quote,
                    char_start=0,
                    char_end=len(quote),
                    native_bbox=(
                        bounds[0],
                        geometry.height_pt - bounds[3],
                        bounds[2],
                        geometry.height_pt - bounds[1],
                    ),
                )
                derived = replace(
                    candidate,
                    kind="figure",
                    source=native,
                    parser_bbox=None,
                    parser_to_canonical=None,
                    context=(
                        FIGURE_CONTEXT_MARKER,
                        "qc_native_policy=" + policy_sha,
                        "qc_native_origin=" + block.source_id,
                    ),
                )
                sid = str(
                    uuid5(UUID(graph.parse_manifest_id), f"{graph.tenant_id}:{((run, ident),)}")
                )
                context_blocks.append(
                    (
                        CanonicalBlock(sid, "figure", (derived,), (family,), "unverified", 0),
                        CandidateEdge(ident, candidate.source.source_native_id, "derived_from"),
                    )
                )
            context_ids = [b.source_id for b, _ in context_blocks]
            found = 0
            for group in groups:
                offset = group[0]["index"]
                local = text[offset : group[-1]["index"] + 1]
                for start, end, quote in native_figure_bullets(local):
                    compact = "".join(quote.split())
                    if any(p == block.page_num and compact in t for p, t in existing):
                        continue
                    selected = _quote_glyphs(glyphs, quote, box, [])
                    if not selected:
                        continue
                    bounds = tuple(
                        fn(g["bbox"][i] for g in selected)
                        for i, fn in enumerate((min, min, max, max))
                    )
                    ident = (
                        "qc-native-"
                        + canonical_hash(
                            dict(
                                origin=block.source_id,
                                start=offset + start,
                                end=offset + end,
                                policy_sha256=policy_sha,
                            )
                        )[:24]
                    )
                    native = replace(
                        candidate.source,
                        source_native_id=ident,
                        raw_text=quote,
                        char_start=0,
                        char_end=len(quote),
                        native_bbox=(
                            bounds[0],
                            geometry.height_pt - bounds[3],
                            bounds[2],
                            geometry.height_pt - bounds[1],
                        ),
                    )
                    derived = replace(
                        candidate,
                        kind="paragraph",
                        source=native,
                        parser_bbox=None,
                        parser_to_canonical=None,
                        context=(
                            FIGURE_MARKER,
                            "qc_native_policy=" + policy_sha,
                            "qc_native_origin=" + block.source_id,
                            "qc_native_context_ids=" + json.dumps(context_ids),
                        ),
                    )
                    run = native.parser_run_id
                    keys = ((run, ident),)
                    sid = str(uuid5(UUID(graph.parse_manifest_id), f"{graph.tenant_id}:{keys}"))
                    family = next(
                        b.parser_family for b in graph.candidates if b.parser_run_id == run
                    )
                    additions.append(
                        CanonicalBlock(sid, "paragraph", (derived,), (family,), "unverified", 0)
                    )
                    edges.append(CanonicalEdge(sid, block.source_id, "derived_from"))
                    by_run.setdefault(run, []).append(
                        (
                            derived,
                            CandidateEdge(ident, candidate.source.source_native_id, "derived_from"),
                        )
                    )
                    receipt["candidates"].append(
                        dict(
                            source_id=sid,
                            origin_source_id=block.source_id,
                            page_num=block.page_num,
                            quote=quote,
                            bbox=bounds,
                            native_start=offset + start,
                            native_end=offset + end,
                            verification_state="candidate",
                            context_source_refs=[asdict(b.source_ref()) for b, _ in context_blocks],
                        )
                    )
                    existing.add((block.page_num, compact))
                    found += 1
            if found:
                for context_block, context_edge in context_blocks:
                    additions.append(context_block)
                    edges.append(
                        CanonicalEdge(context_block.source_id, block.source_id, "derived_from")
                    )
                    by_run.setdefault(run, []).append((context_block.candidates[0], context_edge))
            if not found:
                receipt["unresolved"].append(
                    dict(source_id=block.source_id, reason="no_new_bullet")
                )
    batches = tuple(
        replace(
            b,
            blocks=(*b.blocks, *(c for c, _ in by_run.get(b.parser_run_id, []))),
            edges=(*b.edges, *(e for _, e in by_run.get(b.parser_run_id, []))),
        )
        for b in graph.candidates
    )
    result = replace(
        graph,
        blocks=tuple(sorted((*graph.blocks, *additions), key=lambda b: (b.page_num, b.source_id))),
        edges=tuple(
            sorted((*graph.edges, *edges), key=lambda e: (e.source_id, e.target_id, e.relation))
        ),
        candidates=batches,
    )
    _validate(result, graph.tenant_id)
    receipt["output_graph_sha256"] = canonical_hash(asdict(result))
    return result, receipt


def native_figure_builder_policy():
    """Pin local parser code and native engine into only the new extraction profile."""
    return dict(
        builder_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        pdfium_version=version("pypdfium2"),
    )
