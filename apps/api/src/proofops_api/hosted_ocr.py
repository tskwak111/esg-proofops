"""Hosted OCR money boundary and document-scoped replay over unchanged reader bytes."""

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from proofops.adapters.local.upstage_ocr_page import (
    COST,
    MODEL,
    PageOCRStore,
    parse_response,
    post_png,
    reader_policy,
)
from proofops.domain.provenance import canonical_hash

_binding_lock = threading.RLock()


@contextmanager
def reader_scope(store):
    # Frozen version compositions all reuse this factory. Serialize hosted reads
    # and restore it, so concurrent tenants never share a document's ledger.
    with _binding_lock:
        previous = PageOCRStore.__dict__["from_env"]
        PageOCRStore.from_env = classmethod(lambda cls: store)
        try:
            yield
        finally:
            PageOCRStore.from_env = previous


class HostedOCRStore(PageOCRStore):
    def __init__(self, ledger, spend, *, store, job, local_run_id, post=None):
        self.hosted, self.job, self.local_run_id, self.post = store, job, local_run_id, post
        # This private bookkeeping grants no money; HostedStore.dispatch is the
        # authority and fences/reserves each actual PNG transport separately.
        Path(spend).write_text(json.dumps(dict(limit_usd="0.50", cumulative_usd="0")))
        Path(spend).chmod(0o600)
        # Legacy two-page jobs keep their allowance. Expanded scope is bounded
        # by the frozen prepared PDF, with the same broker enforcing all money.
        pages = json.loads(job["pages"])
        if not 1 <= len(pages) <= 30:
            raise ValueError("OCR_SOURCE_SCOPE_INVALID")
        super().__init__(ledger, spend, transport=self._post, max_calls=max(2, len(pages)))

    def _reserve(self, image, tenant_id, run_id, force):
        if tenant_id != self.job["tenant_id"] or run_id != self.local_run_id:
            raise ValueError("OCR_SOURCE_SCOPE_INVALID")
        return super()._reserve(image, tenant_id, run_id, force)

    def _post(self, png):
        def transport(request):
            raw, provider_id = self.post(png) if self.post else post_png(png)
            parse_response(raw)  # model/API1.1/exactly one billed page, bounded response
            return request | dict(actual_usd=str(COST), payload=(raw, provider_id))

        return self.hosted.dispatch(
            self.job,
            "upstage-ocr",
            str(uuid4()),
            canonical_hash(dict(model=MODEL, png_sha256=sha256(png).hexdigest())),
            COST,
            transport,
            now=time.time(),
        )["payload"]


class ReplayOCRStore(PageOCRStore):
    def __init__(self, ledger):
        self.ledger = Path(ledger)

    def fetch(self, image, *, tenant_id, run_id, force=False):
        # API results and supplementary human reads may reuse a trusted page;
        # they cannot reserve, fetch a new page, or call a provider.
        if force:
            raise ValueError("OCR_COLLECTION_UNTRUSTED")
        key = canonical_hash(dict(manifest=image["manifest"], policy=reader_policy()))
        try:
            with sqlite3.connect(self.ledger.resolve().as_uri() + "?mode=ro", uri=True) as db:
                row = db.execute(
                    "SELECT c.collection FROM ocr_page_cache p JOIN ocr_calls c "
                    "ON p.request_id=c.request_id WHERE p.tenant=? AND p.cache_key=? "
                    "AND c.state='collected'",
                    (tenant_id, key),
                ).fetchone()
        except sqlite3.Error:
            raise ValueError("OCR_COLLECTION_UNTRUSTED") from None
        if not row:
            raise ValueError("OCR_COLLECTION_UNTRUSTED")
        return self.validate(json.loads(row[0]), image, tenant_id=tenant_id)
