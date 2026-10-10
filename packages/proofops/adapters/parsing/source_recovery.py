"""PS1 opt-in: unique literal locations and native-grounded paragraph continuations.

No provider calls and no verification promotion. The original candidates and
each join's derived_from edges remain in the immutable parser artifact.
"""

from __future__ import annotations

import io
import re
from bisect import bisect_right
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from statistics import median

import pdfplumber
from proofops.adapters.parsing.gemini_vision import NUMBERS, compact, fragment
from proofops.application.ingest.graph_fusion import CandidateEdge

PROFILE = "ps1-v1"
JOIN_CONTEXT = "source_recovery_join=ps1-v1"


def _typography(page):
    chars = [c for c in page.chars if compact(c["text"])]
    parts = [compact(c["text"]) for c in chars]
    ends, size = [], 0
    for part in parts:
        size += len(part)
        ends.append(size)
    return dict(
        chars=chars,
        text="".join(parts),
        ends=ends,
        body_size=median(c["size"] for c in chars) if chars else 0,
    )


def _heading_like(text, typography):
    target = compact(text)
    at = typography["text"].find(target)
    if not target or at < 0 or typography["text"].find(target, at + 1) >= 0:
        return False
    first = bisect_right(typography["ends"], at)
    last = bisect_right(typography["ends"], at + len(target) - 1)
    chars = typography["chars"][first : last + 1]
    # Native font metadata catches provider-mislabeled headings. No inferred
    # text or model tags; uncertain layout simply retains the original blocks.
    return median(c["size"] for c in chars) > typography["body_size"] * 1.1


def _provider_box(block):
    for item in block.context:
        if item.startswith("provider_bbox="):
            try:
                box = tuple(map(float, item.split("=", 1)[1].split(",")))
                if len(box) == 4 and box[0] < box[2] and box[1] < box[3]:
                    return box
            except ValueError:
                pass
    return block.bbox


def _streams(words, blocks, flow_words=()):
    """Keep native order; column filtering never sorts/reconstructs characters."""
    regions = {None}
    for block in blocks:
        box = _provider_box(block)
        if box:
            regions.add((round(box[0], 2) - 2, round(box[2], 2) + 2, None, None))
            regions.add((box[0] - 2, box[2] + 2, box[1] - 2, box[3] + 2))
    streams = []
    seen = set()
    positions = {
        (w["text"], w["x0"], w["top"], w["x1"], w["bottom"]): i for i, w in enumerate(words)
    }
    flow_keys = [(w["text"], w["x0"], w["top"], w["x1"], w["bottom"]) for w in flow_words]
    # Text-flow extraction can group words differently. Dropping an unmapped
    # word would manufacture adjacency, so reject that entire alternative.
    flow = (
        tuple(positions[key] for key in flow_keys)
        if all(key in positions for key in flow_keys)
        else ()
    )
    sequences = [flow] if flow else []
    for region in regions:
        indices = tuple(
            i
            for i, w in enumerate(words)
            if region is None
            or (
                region[0] <= w["x0"]
                and w["x1"] <= region[1]
                and (region[2] is None or region[2] <= w["top"] and w["bottom"] <= region[3])
            )
        )
        sequences.append(indices)
    for indices in sequences:
        if indices in seen:
            continue
        seen.add(indices)
        parts = [compact(words[i]["text"]) for i in indices]
        ends, size = [], 0
        for part in parts:
            size += len(part)
            ends.append(size)
        streams.append((indices, "".join(parts), ends))
    return streams


def _locate(text, words, streams, *, bounds=None):
    target = compact(text)
    if not target:
        return None
    matches = {}
    for indices, native, ends in streams:
        at = native.find(target)
        while at >= 0:
            first = bisect_right(ends, at)
            last = bisect_right(ends, at + len(target) - 1)
            chosen = indices[first : last + 1]
            local = [words[i] for i in chosen]
            box = (
                min(w["x0"] for w in local),
                min(w["top"] for w in local),
                max(w["x1"] for w in local),
                max(w["bottom"] for w in local),
            )
            if NUMBERS.findall(text) == NUMBERS.findall(" ".join(w["text"] for w in local)):
                matches[chosen, at - (ends[first - 1] if first else 0)] = box
            at = native.find(target, at + 1)
    # Uniqueness is PAGE-wide, including other columns, even if a provider box exists.
    if len(matches) != 1:
        return None
    box = next(iter(matches.values()))
    if bounds is not None and not (
        bounds[0] - 2 <= box[0] < box[2] <= bounds[2] + 2
        and bounds[1] - 2 <= box[1] < box[3] <= bounds[3] + 2
    ):
        return None
    return box


def _located(block, box, context):
    g = block.geometry
    return replace(
        block,
        parser_bbox=None,
        parser_to_canonical=None,
        source=replace(
            block.source, native_bbox=(box[0], g.height_pt - box[3], box[2], g.height_pt - box[1])
        ),
        context=tuple(c for c in block.context if c not in {"vision_only", "native_glyph_ink_box"})
        + (context,),
    )


def _continues(left, right):
    a, b = left.bbox, right.bbox
    return (
        left.kind == right.kind == "paragraph"
        and a is not None
        and b is not None
        and left.source.physical_page == right.source.physical_page
        and left.geometry == right.geometry
        and [c for c in left.context if c.startswith("section=")]
        == [c for c in right.context if c.startswith("section=")]
        and not re.search(r"[.!?。！？][\s\"'’”)]*$", left.source.raw_text)
        and not left.source.raw_text.rstrip().endswith((":", ";", "다", "음"))
        and fragment(left.source.raw_text)
        and not re.match(r"\s*(?:[•·*\-]|\d+[.)]\s)", right.source.raw_text)
        and len(left.source.raw_text.strip()) >= 8
        and abs(a[0] - b[0]) <= 6
        and 0 <= b[1] - a[3] <= min(24, max(6, (a[3] - a[1]) * 2))
        and min(a[2], b[2]) - max(a[0], b[0]) >= min(a[2] - a[0], b[2] - b[0]) * 0.8
    )


def recover_sources(source, batches, *, references=()):
    """Return new candidates and an auditable receipt; leave all inputs untouched."""
    if sha256(source.content).hexdigest() != source.sha256:
        raise ValueError("SOURCE_RECOVERY_SOURCE_MISMATCH")
    if not batches or len({b.parse_manifest_id for b in (*batches, *references)}) != 1:
        raise ValueError("SOURCE_RECOVERY_IDENTITY_MISMATCH")
    for batch in (*batches, *references):
        if (batch.tenant_id, batch.document_version_id, batch.source_sha256) != (
            source.tenant_id,
            source.document_version_id,
            source.sha256,
        ):
            raise ValueError("SOURCE_RECOVERY_IDENTITY_MISMATCH")
    receipt = dict(
        profile=PROFILE,
        policy_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        source_sha256=source.sha256,
        located=0,
        joined=0,
        locations=[],
        joins=[],
    )
    all_blocks = [b for batch in (*batches, *references) for b in batch.blocks]
    by_page = {}
    for block in all_blocks:
        by_page.setdefault(block.source.physical_page, []).append(block)
    result = []
    with pdfplumber.open(io.BytesIO(source.content)) as document:
        native, typography = {}, {}
        for number, blocks in by_page.items():
            page = document.pages[number - 1]
            if page.rotation != 0 or tuple(page.cropbox[:2]) != (0, 0):
                continue
            words = page.extract_words()
            typography[number] = _typography(page)
            native[number] = (
                words,
                _streams(words, blocks, page.extract_words(use_text_flow=True)),
            )
        for batch in batches:
            blocks = []
            for block in batch.blocks:
                if block.source.native_bbox is None and block.source.physical_page in native:
                    words, streams = native[block.source.physical_page]
                    box = _locate(
                        block.source.raw_text,
                        words,
                        streams,
                        bounds=_provider_box(block) if block.kind != "paragraph" else None,
                    )
                    if box:
                        block = _located(block, box, "source_recovery_location=ps1-v1:native")
                        receipt["located"] += 1
                        receipt["locations"].append(
                            dict(
                                parser_run_id=batch.parser_run_id,
                                source_native_id=block.source.source_native_id,
                                page=block.source.physical_page,
                                bbox=box,
                            )
                        )
                blocks.append(block)
            additions, edges = [], list(batch.edges)
            at = 0
            while at < len(blocks):
                group = [blocks[at]]
                text = group[0].source.raw_text
                box = None
                while at + len(group) < len(blocks) and _continues(
                    group[-1], blocks[at + len(group)]
                ):
                    right = blocks[at + len(group)]
                    layout = typography.get(right.source.physical_page)
                    if layout and (
                        _heading_like(group[-1].source.raw_text, layout)
                        or _heading_like(right.source.raw_text, layout)
                    ):
                        break
                    words, streams = native.get(right.source.physical_page, ([], []))
                    joined = text + "\n" + right.source.raw_text
                    candidate_box = _locate(joined, words, streams)
                    if candidate_box is None:
                        break
                    group.append(right)
                    text, box = joined, candidate_box
                if len(group) > 1:
                    identifier = (
                        "ps1-join-"
                        + sha256(
                            "|".join(b.source.source_native_id for b in group).encode()
                        ).hexdigest()[:24]
                    )
                    joined = _located(group[0], box, JOIN_CONTEXT)
                    joined = replace(
                        joined,
                        source=replace(
                            joined.source,
                            source_native_id=identifier,
                            raw_text=text,
                            char_start=0,
                            char_end=len(text),
                        ),
                        parser_bbox=None,
                        parser_to_canonical=None,
                    )
                    additions.append(joined)
                    edges.extend(
                        CandidateEdge(identifier, b.source.source_native_id, "derived_from")
                        for b in group
                    )
                    receipt["joined"] += 1
                    receipt["joins"].append(
                        dict(
                            parser_run_id=batch.parser_run_id,
                            source_native_id=identifier,
                            page=joined.source.physical_page,
                            fragments=[b.source.source_native_id for b in group],
                            quote=text,
                            bbox=box,
                        )
                    )
                at += len(group)
            result.append(replace(batch, blocks=tuple(blocks + additions), edges=tuple(edges)))
    return tuple(result), receipt
