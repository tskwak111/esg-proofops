"""Original glyph/font proof for a narrow mislabeled strategy section title."""

import io
from hashlib import sha256
from statistics import median

import pdfplumber
import pypdfium2 as pdfium

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
