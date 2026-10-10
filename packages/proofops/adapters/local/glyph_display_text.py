"""Original-PDF display writer; no source-quality promotion or model input trust.

A canonical block is mapped in its pinned crop only, never by searching a page
for a matching quote. Original glyph identities are independently recomputed.
"""

import io
import re
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from hashlib import sha256
from multiprocessing import get_context
from threading import RLock
from typing import Any

import pdfplumber
import pypdfium2 as pdfium
import pypdfium2.raw as pdfraw

from proofops.adapters.local.glyph_alignment_verification import _same_line, _same_row
from proofops.adapters.local.native_glyph_geometry import native_word_ink_geometry
from proofops.application.ingest.display_text import (
    POLICY,
    display_alignment,
    join_allowed,
    locate_display,
    mapping_pin,
)
from proofops.domain.provenance import canonical_hash


class GlyphDisplayCatalog:
    def __init__(self, graph, source: bytes):
        if source is None:
            raise ValueError("DISPLAY_SOURCE_UNAVAILABLE")
        if sha256(source).hexdigest() != graph.source_sha256:
            raise ValueError("DISPLAY_SOURCE_MISMATCH")
        self.graph, self.source = graph, source
        self.identity = dict(
            tenant_id=graph.tenant_id,
            document_version_id=graph.document_version_id,
            parse_manifest_id=graph.parse_manifest_id,
            source_sha256=graph.source_sha256,
            graph_sha256=canonical_hash(asdict(graph)),
        )
        self._blocks = {b.source_id: b for b in graph.blocks}
        self._cache: dict[str, Any] = {}
        self._pages: dict[int, Any] = {}
        self._lock = RLock()

    def _block(self, source_id):
        with self._lock:
            if source_id not in self._cache:
                self._cache[source_id] = self._build(self._blocks[source_id])
            return self._cache[source_id]

    def _build(self, block):
        raw, box = block.raw_text, block.bbox
        empty = ([], [])
        if block.winner is None or box is None or " " not in raw:
            return empty
        if block.page_num not in self._pages:
            self._pages[block.page_num] = self._page(block.page_num)
        native, matched, spaces, proof_sha = self._pages[block.page_num]
        words, crossing = [], []
        for w in native:
            m = matched.get(w["index"])
            wb = m["ink_bbox"] if m else w["bbox"]
            if wb[2] <= box[0] or wb[0] >= box[2] or wb[3] <= box[1] or wb[1] >= box[3]:
                continue
            if m is None:
                return empty
            if (
                box[0] - 0.001 <= wb[0] < wb[2] <= box[2] + 0.001
                and box[1] - 0.001 <= wb[1] < wb[3] <= box[3] + 0.001
            ):
                words.append(dict(w))
            else:
                crossing.append(wb)
        if crossing and (
            not words
            or any(
                wb[1] < max(matched[w["index"]]["ink_bbox"][3] for w in words)
                and wb[3] > min(matched[w["index"]]["ink_bbox"][1] for w in words)
                for wb in crossing
            )
        ):
            return empty
        tokens = list(re.finditer(r"\S+", raw))
        if not words or [m[0] for m in tokens] != [w["text"] for w in words]:
            return empty
        for w in words:
            m = matched.get(w["index"])
            if m is None:
                return empty
            w["bbox"], w["glyphs"] = m["ink_bbox"], m["pdfium_char_indices"]
            if len(w["glyphs"]) != len(w["text"]) or any(
                b != a + 1 for a, b in zip(w["glyphs"], w["glyphs"][1:])
            ):
                return empty
        controls = []
        for a, b in zip(words, words[1:]):
            between = set(range(a["glyphs"][-1] + 1, b["glyphs"][0]))
            if _same_line(a, b) and between and between <= spaces:
                controls.append((a, b["bbox"][0] - a["bbox"][2], b, sorted(between)))
        deleted, boundaries = [], []
        for i, (a, b) in enumerate(zip(words, words[1:])):
            offset = tokens[i].end()
            if (
                raw[offset : tokens[i + 1].start()] != " "
                or not join_allowed(raw, offset)
                or not _same_line(a, b)
                or a["glyphs"][-1] + 1 != b["glyphs"][0]
            ):
                continue
            gap = b["bbox"][0] - a["bbox"][2]
            height = min(a["bbox"][3] - a["bbox"][1], b["bbox"][3] - b["bbox"][1])
            local = [control for control in controls if _same_row(a, control[0])]
            control_gaps = [control[1] for control in local]
            if local and 0 <= gap <= 0.2 * height and min(control_gaps) > 1.5 * gap:
                deleted.append(offset)
                boundaries.append(
                    dict(
                        raw_offset=offset,
                        glyph_indices=[a["glyphs"][-1], b["glyphs"][0]],
                        left_bbox=a["bbox"],
                        right_bbox=b["bbox"],
                        gap_pt=gap,
                        height_pt=height,
                        minimum_control_gap_pt=min(control_gaps),
                        controls=[
                            dict(
                                space_glyph_indices=control[3],
                                left_bbox=control[0]["bbox"],
                                right_bbox=control[2]["bbox"],
                                gap_pt=control[1],
                            )
                            for control in local
                        ],
                        glyph_proof_sha256=proof_sha,
                    )
                )
        return deleted, boundaries

    def _page(self, page_num):
        return _read_display_page(self.source, page_num)

    def prefetch_pages(self, pages, *, max_workers=1):
        """Opt-in CPU reads in isolated processes; the normal page reader is unchanged.

        No model requests or source-quality promotion. Spawn keeps PDFium handles
        isolated. A failed read propagates and never seeds a fabricated page.
        """
        if type(max_workers) is not int or not 1 <= max_workers <= 4:
            raise ValueError("DISPLAY_PREFETCH_WORKERS_INVALID")
        if max_workers == 1:
            return
        with self._lock:
            pending = sorted(set(pages) - self._pages.keys())
            if not pending:
                return
            with ProcessPoolExecutor(
                max_workers=max_workers, mp_context=get_context("spawn")
            ) as pool:
                readings = list(pool.map(_read_display_page, [self.source] * len(pending), pending))
            self._pages.update(zip(pending, readings, strict=True))

    def pin(self, ref: dict) -> dict:
        block = self._blocks[ref["source_id"]]
        start, end = ref["char_start"], ref["char_end"]
        if (
            ref["document_version_id"] != self.graph.document_version_id
            or ref["page_num"] != block.page_num
            or tuple(ref["bbox"] or ()) != tuple(block.bbox or ())
            or not 0 <= start < end <= len(block.raw_text)
            or block.raw_text[start:end] != ref["quote"]
        ):
            raise ValueError("DISPLAY_REF_MISMATCH")
        deleted, boundaries = self._block(block.source_id)
        local = [
            i - start
            for i in deleted
            if start < i < end - 1 and join_allowed(ref["quote"], i - start)
        ]
        mapping = display_alignment(ref["quote"], local)
        return mapping_pin(
            mapping,
            identity=self.identity
            | dict(
                source_id=block.source_id,
                page_num=block.page_num,
                bbox=list(block.bbox) if block.bbox else None,
                char_start=start,
                char_end=end,
            ),
            boundaries=[b for b in boundaries if b["raw_offset"] - start in local],
        )

    def block_pin(self, source_id):
        return self.pin(asdict(self._blocks[source_id].source_ref()))

    @staticmethod
    def restore(selection, original, pin, *, policy=None):
        mapping = display_alignment(original["quote"], pin["deleted_offsets"])
        if (
            pin["policy"] != POLICY
            or pin["raw_sha256"] != canonical_hash(original["quote"])
            or pin["text"] != mapping.text
            or pin["raw_boundaries"] != list(mapping.raw_boundaries)
        ):
            raise ValueError("DISPLAY_MAP_MISMATCH")
        if policy is None:
            start, end, quote = locate_display(selection, mapping)
        else:
            from proofops.application.tagging.citation_restore import POLICY as RESTORE_POLICY
            from proofops.application.tagging.citation_restore import restore_whitespace
            from proofops.application.tagging.pb2_citation_restore import POLICY as TABLE_POLICY
            from proofops.application.tagging.pb2_citation_restore import restore_table

            if policy not in (RESTORE_POLICY, TABLE_POLICY):
                raise ValueError("CITATION_RESTORE_POLICY_UNKNOWN")
            restore = restore_table if policy == TABLE_POLICY else restore_whitespace
            selected = restore(selection, dict(quote=mapping.text, char_start=0))
            start, end = mapping.raw_span(selected["char_start"], selected["char_end"])
            quote = mapping.raw[start:end]
        return original | dict(
            quote=quote,
            char_start=original["char_start"] + start,
            char_end=original["char_start"] + end,
        )

    def element_pins(self, data):
        refs = [
            *data["claim_source_refs"],
            *(r for c in data["evidence_candidates"] for r in c["source_refs"]),
        ]
        return dict(policy=POLICY, sources=[self.pin(r) for r in refs])

    def context_pin(self, entry):
        return self.pin(entry["source_ref"] | dict(quote=entry["text"]))

    def preliminary_pins(self, packet, sources):
        data = packet["untrusted_document_data"]
        for block in data.get("context_blocks", []):
            pin = self.context_pin(block)
            if canonical_hash(block["text"]) != pin["raw_sha256"]:
                raise ValueError("DISPLAY_CONTEXT_MISMATCH")
        return dict(
            policy=POLICY,
            sources=[self.pin(asdict(r)) for r in sources],
            context=[self.context_pin(b) for b in data.get("context_blocks", [])],
        )

    def restore_preliminary(self, response, packet):
        from copy import deepcopy

        restored = deepcopy(response)
        pins = packet["display_text"]["sources"]
        sources = packet["untrusted_document_data"]["sources"]
        for span in restored.get("dimensions", {}).values():
            if span is None:
                continue
            if set(span) != {"source_index", "quote"} or type(span["source_index"]) is not int:
                raise ValueError("DISPLAY_PRELIMINARY_SELECTION")
            index = span["source_index"]
            if not 0 <= index < len(pins):
                raise ValueError("DISPLAY_PRELIMINARY_SELECTION")
            pin = pins[index]
            mapping = display_alignment(sources[index]["text"], pin["deleted_offsets"])
            start, end, quote = locate_display(span["quote"], mapping)
            span.update(quote=quote, start=start, end=end)
        return restored


def _read_display_page(source, page_num):
    with pdfplumber.open(io.BytesIO(source)) as doc:
        page = doc.pages[page_num - 1]
        native = [
            dict(index=i, text=w["text"], bbox=[w["x0"], w["top"], w["x1"], w["bottom"]])
            for i, w in enumerate(page.extract_words(return_chars=True))
        ]
    if not native or len(native) > 1000:
        return native, {}, set(), None
    try:
        proof = native_word_ink_geometry(source, page_num, list(range(len(native))))
    except ValueError:
        return native, {}, set(), None
    with pdfium.PdfDocument(source) as doc:
        page = doc[page_num - 1]
        textpage = page.get_textpage()
        try:
            spaces = {
                j
                for j in range(textpage.count_chars())
                if pdfraw.FPDFText_GetUnicode(textpage, j) == 32
                and pdfraw.FPDFText_IsGenerated(textpage, j) == 0
            }
        finally:
            textpage.close()
            page.close()
    return (
        native,
        {w["native_word_index"]: w for w in proof["matched_words"]},
        spaces,
        proof["proof_sha256"],
    )
