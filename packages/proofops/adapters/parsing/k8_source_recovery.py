"""Opt-in native-grounded 있/도록 continuation; historical PS1 bytes stay intact."""

import io
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pdfplumber
from proofops.adapters.parsing.source_recovery import (
    JOIN_CONTEXT,
    _heading_like,
    _locate,
    _located,
    _provider_box,
    _streams,
    _typography,
)
from proofops.application.ingest.graph_fusion import CandidateEdge

PROFILE = "native-continuation-k8-v1"


def _continues(left, right):
    a, b = left.bbox, right.bbox
    return (
        left.kind == right.kind == "paragraph"
        and left.source.raw_text.rstrip().endswith("있")
        and right.source.raw_text.lstrip().startswith("도록 ")
        and a is not None
        and b is not None
        and left.source.physical_page == right.source.physical_page
        and left.geometry == right.geometry
        and [c for c in left.context if c.startswith("section=")]
        == [c for c in right.context if c.startswith("section=")]
        and abs(a[0] - b[0]) <= 6
        and b[1] > a[1]
        and -2 <= b[1] - a[3] <= 12
        and min(a[2], b[2]) - max(a[0], b[0]) >= min(a[2] - a[0], b[2] - b[0]) * 0.8
    )


def recover_sources(source, batches, *, references=()):
    if sha256(source.content).hexdigest() != source.sha256:
        raise ValueError("SOURCE_RECOVERY_SOURCE_MISMATCH")
    if not batches or len({b.parse_manifest_id for b in (*batches, *references)}) != 1:
        raise ValueError("SOURCE_RECOVERY_IDENTITY_MISMATCH")
    if any(
        (b.tenant_id, b.document_version_id, b.source_sha256)
        != (source.tenant_id, source.document_version_id, source.sha256)
        for b in (*batches, *references)
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
    result = []
    with pdfplumber.open(io.BytesIO(source.content)) as pdf:
        for batch in batches:
            additions, edges = [], list(batch.edges)
            for left in batch.blocks:
                choices = [right for right in batch.blocks if _continues(left, right)]
                if len(choices) != 1:
                    continue
                right = choices[0]
                if sum(_continues(other, right) for other in batch.blocks) != 1:
                    continue
                page = pdf.pages[left.source.physical_page - 1]
                if page.rotation != 0 or tuple(page.cropbox[:2]) != (0, 0):
                    continue
                typography = _typography(page)
                if any(_heading_like(b.source.raw_text, typography) for b in (left, right)):
                    continue
                words = page.extract_words()
                streams = _streams(words, batch.blocks, page.extract_words(use_text_flow=True))
                text = left.source.raw_text + "\n" + right.source.raw_text
                box = _locate(text, words, streams)
                # Both literal fragments and the complete native sequence must be unique.
                if box is None or any(
                    _locate(b.source.raw_text, words, streams, bounds=_provider_box(b)) is None
                    for b in (left, right)
                ):
                    continue
                ident = (
                    "k8-join-"
                    + sha256(
                        (
                            left.source.source_native_id + "|" + right.source.source_native_id
                        ).encode()
                    ).hexdigest()[:24]
                )
                joined = _located(left, box, JOIN_CONTEXT)
                joined = replace(
                    joined,
                    source=replace(
                        joined.source,
                        source_native_id=ident,
                        raw_text=text,
                        char_start=0,
                        char_end=len(text),
                    ),
                )
                additions.append(joined)
                edges.extend(
                    CandidateEdge(ident, b.source.source_native_id, "derived_from")
                    for b in (left, right)
                )
                receipt["joins"].append(
                    dict(
                        parser_run_id=batch.parser_run_id,
                        source_native_id=ident,
                        page=left.source.physical_page,
                        fragments=[left.source.source_native_id, right.source.source_native_id],
                        quote=text,
                        bbox=box,
                    )
                )
                receipt["joined"] += 1
            result.append(replace(batch, blocks=(*batch.blocks, *additions), edges=tuple(edges)))
    return tuple(result), receipt
