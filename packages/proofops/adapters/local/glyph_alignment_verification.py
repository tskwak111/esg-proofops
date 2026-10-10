"""Opt-in, line-local deletion of proven artificial native word-join spaces.

The existing typography policy is the baseline, including its existing passes.
New recoveries require literal equality of the entire pinned crop after ONLY
proven word-join deletions. No OCR character substitution, inserted spaces,
line joining, alternate occurrence, page search or fuzzy match is admitted.
The existing policy envelope is retained for RunService compatibility; the
profile discriminator and exact policy digest select this distinct reader.
"""

import math
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import claim_source_verification as strict
from proofops.adapters.local import claim_span_typography as baseline
from proofops.application.evidence import span_citations
from proofops.application.evidence.citations import _normalized
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

PROFILE = "glyph-alignment-v1"
SCHEMA = "glyph_alignment_attestation_v1"
MAX_GAP_HEIGHT_RATIO = 0.2
MIN_REAL_SPACE_RATIO = 1.5


def claim_source_policy():
    return dict(
        schema=baseline.POLICY_SCHEMA,
        profile=PROFILE,
        base=baseline.claim_source_policy(),
        wrapper_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        max_gap_height_ratio=MAX_GAP_HEIGHT_RATIO,
        min_real_space_ratio=MIN_REAL_SPACE_RATIO,
    )


def _box_valid(box):
    return (
        isinstance(box, tuple | list)
        and len(box) == 4
        and all(type(x) in (int, float) and math.isfinite(x) for x in box)
        and box[0] < box[2]
        and box[1] < box[3]
    )


def _same_row(left, right):
    a, b = left["bbox"], right["bbox"]
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    return overlap >= 0.8 * max(a[3] - a[1], b[3] - b[1])


def _same_line(left, right):
    return _same_row(left, right) and right["bbox"][0] >= left["bbox"][2]


def align_reading(*, native, quote, reading, page_num, bbox, source_sha256):
    """Diagnostic gate on a trusted baseline reading, NOT an attestation API.

    Production calls this only after recomputing the baseline against original
    PDF bytes. Offline callers must independently pin and verify their archive.
    Maps are codepoint indices into native_text; refs/raw offsets never change.
    Rejected diagnostic decisions remain unresolved in published source records.
    """

    def refuse(reason, status="unresolved"):
        return dict(status=status, reason=reason)

    rendered = reading.get("rendered", {})
    if reading.get("reason") != "rendered_quote_unresolved" or rendered.get("status") != "read":
        return refuse("no_eligible_rendered_read")
    # Keep OCR codepoints literal; only the existing line/whitespace display
    # normalization is retained. No Unicode composition or typography fold here.
    rendered_text = " ".join(rendered.get("text", "").split())
    if not strict._unique_quote(native, quote):
        return refuse("native_quote_not_unique", "rejected")
    # Diagnostic veto only: this comparison can NEVER grant approval.
    if native.replace(" ", "") != rendered_text.replace(" ", ""):
        return refuse("character_veto", "rejected")
    proof = reading.get("glyph_geometry") or {}
    if not proof:
        return refuse("glyph_proof_missing")
    if proof.get("source_sha256") != source_sha256 or proof.get("physical_page") != page_num:
        return refuse("glyph_source_or_page_mismatch", "rejected")
    words = reading.get("words", [])
    if not words or " ".join(w["text"] for w in words) != native:
        return refuse("native_word_order_mismatch")
    if not _box_valid(bbox):
        return refuse("invalid_location", "rejected")
    matched = {m["native_word_index"]: m for m in proof.get("matched_words", [])}
    indices = []
    seen = set()
    for word in words:
        box = word["bbox"]
        mapped = matched.get(word["index"], {})
        glyphs = mapped.get("pdfium_char_indices", [])
        if not _box_valid(box) or not (
            bbox[0] - 0.001 <= box[0] < box[2] <= bbox[2] + 0.001
            and bbox[1] - 0.001 <= box[1] < box[3] <= bbox[3] + 0.001
        ):
            return refuse("glyph_outside_pinned_location", "rejected")
        if (
            mapped.get("ink_bbox") != box
            or len(glyphs) != len(word["text"])
            or not glyphs
            or any(type(i) is not int or i < 0 for i in glyphs)
            or glyphs != sorted(set(glyphs))
            or seen.intersection(glyphs)
        ):
            return refuse("glyph_mapping_unresolved")
        seen.update(glyphs)
        indices.append(glyphs)

    deletable = {}
    cross_line = set()
    offset = 0
    for i, (left, right) in enumerate(zip(words, words[1:])):
        offset += len(left["text"])
        if not _same_line(left, right):
            cross_line.add(offset)
        if (
            _same_line(left, right)
            and left["text"][-1].isalpha()
            and right["text"][0].isalpha()
            and indices[i][-1] + 1 == indices[i + 1][0]
        ):
            gap = right["bbox"][0] - left["bbox"][2]
            height = min(left["bbox"][3] - left["bbox"][1], right["bbox"][3] - right["bbox"][1])
            # Require a genuine spaced boundary on this same physical line as
            # a local control, as well as the absolute gap/height ceiling.
            controls = [
                b["bbox"][0] - a["bbox"][2]
                for j, (a, b) in enumerate(zip(words, words[1:]))
                if _same_line(a, b)
                and _same_row(left, a)
                and indices[j + 1][0] > indices[j][-1] + 1
            ]
            if (
                controls
                and 0 <= gap <= MAX_GAP_HEIGHT_RATIO * height
                and min(controls) > MIN_REAL_SPACE_RATIO * gap
            ):
                deletable[offset] = dict(
                    native_offset=offset,
                    left_word_index=left["index"],
                    right_word_index=right["index"],
                    glyph_indices=[indices[i][-1], indices[i + 1][0]],
                    gap_pt=gap,
                    minimum_control_gap_pt=min(controls),
                    left_bbox=left["bbox"],
                    right_bbox=right["bbox"],
                )
        offset += 1

    j = 0
    deleted, mapping = [], []
    for i, char in enumerate(native):
        if j < len(rendered_text) and char == rendered_text[j]:
            mapping.append(i)
            j += 1
        elif char == " " and i in deletable:
            deleted.append(i)
        else:
            if char == " " and i in cross_line:
                return refuse("cross_line_space_veto", "rejected")
            return refuse("spacing_not_proven")
    if j != len(rendered_text) or not deleted:
        return refuse("spacing_not_proven")
    start = native.index(quote)
    end = start + len(quote)
    aligned_quote = "".join(native[i] for i in mapping if start <= i < end)
    if not strict._unique_quote(rendered_text, aligned_quote):
        return refuse("aligned_quote_not_unique", "rejected")
    return dict(
        status="verified",
        reason="glyph_proven_artificial_space",
        native_text=native,
        aligned_text=rendered_text,
        aligned_quote=aligned_quote,
        deleted_native_offsets=deleted,
        aligned_to_native=mapping,
        boundaries=[deletable[i] for i in deleted],
        physical_page=page_num,
        bbox=list(bbox),
        source_sha256=source_sha256,
        glyph_proof_sha256=canonical_hash(proof),
        rendered_read_sha256=canonical_hash(rendered),
    )


def _extend_receipt(receipt, refs):
    """Internal pure extension, called only with freshly verified baseline inputs."""
    records, alignments = [], {}
    for index, (record, ref) in enumerate(zip(receipt["records"], refs, strict=True)):
        copied = dict(record)
        if record["status"] == "unresolved" and record["reason"] == "rendered_quote_unresolved":
            reading = receipt["readings"].get(ref.source_id, {})
            result = align_reading(
                native=_normalized(" ".join(w["text"] for w in reading.get("words", []))),
                quote=_normalized(ref.quote),
                reading=reading,
                page_num=ref.page_num,
                bbox=ref.bbox,
                source_sha256=receipt["source_sha256"],
            )
            alignments[str(index)] = result
            if result["status"] == "verified":
                copied.update(status="verified", reason=None)
        records.append(copied)
    result = dict(
        schema=SCHEMA,
        policy=claim_source_policy(),
        tenant_id=receipt["tenant_id"],
        document_version_id=receipt["document_version_id"],
        parse_manifest_id=receipt["parse_manifest_id"],
        source_sha256=receipt["source_sha256"],
        graph_sha256=receipt["graph_sha256"],
        baseline_receipt=receipt,
        records=records,
        readings=receipt["readings"],
        glyph_alignments=alignments,
    )
    result["artifact_sha256"] = canonical_hash(result)
    return result


def attest_claim_spans(graph, source, refs, *, tenant_id):
    refs = tuple(refs)
    receipt = baseline.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
    return _extend_receipt(receipt, refs)


def replay_claim_spans(receipt, graph, source, discovery, *, tenant_id):
    refs = strict.discovery_refs(discovery)
    expected = attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
    if canonical_hash(receipt) != canonical_hash(expected):
        raise ValueError("GLYPH_ALIGNMENT_RECEIPT_MISMATCH")
    newly = tuple(
        replace(SourceRef(**r["ref"]), verification_state="verified")
        for r in expected["records"]
        if r["status"] == "verified"
    )
    existing = tuple(getattr(graph, "verified_spans", ()) or ())
    seen = {(r.source_id, r.char_start, r.char_end) for r in existing}
    merged = existing + tuple(
        r for r in newly if (r.source_id, r.char_start, r.char_end) not in seen
    )
    scoped = span_citations.span_verified_graph(graph, merged, expected["artifact_sha256"])
    claims = []
    for claim in discovery.claims:
        if claim.source_quality != "unverified":
            claims.append(claim)
            continue
        checked = tuple(
            span_citations.verify_source_ref(r, scoped, tenant_id=tenant_id)
            for r in claim.source_refs
        )
        claims.append(
            replace(claim, source_quality="verified", source_refs=checked)
            if checked and all(r.verification_state == "verified" for r in checked)
            else claim
        )
    return replace(discovery, claims=tuple(claims)), scoped
