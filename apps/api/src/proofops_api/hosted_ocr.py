"""Hosted OCR money boundary and document-scoped replay over unchanged reader bytes."""

import http.client
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from proofops.adapters.local.upstage_ocr_page import (
    COST,
    MAX_RESPONSE_BYTES,
    MODEL,
    PageOCRStore,
    parse_response,
    reader_policy,
)
from proofops.adapters.local.upstage_parse import COST_PER_PAGE
from proofops.domain.provenance import canonical_hash

_binding_lock = threading.RLock()


def post_png(png):
    """Hosted error decoding without changing the byte-pinned historical OCR reader."""
    from datetime import UTC, datetime

    from proofops.adapters.local.provider_errors import upstage_http_error
    from proofops.adapters.local.upstage_ocr_page import PRICE_RECHECK_AT

    if datetime.now(UTC) >= PRICE_RECHECK_AT:
        raise ValueError("PRICE_RECHECK_REQUIRED")
    key = os.environ.get("UPSTAGE_API_KEY", "")
    if not key or any(c.isspace() for c in key):
        raise ValueError("UPSTAGE_API_KEY_MISSING_OR_INVALID")
    boundary = uuid4().hex
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
            f"{MODEL}\r\n--{boundary}\r\nContent-Disposition: form-data; "
            'name="document"; filename="page.png"\r\nContent-Type: image/png\r\n\r\n'
        ).encode()
        + png
        + f"\r\n--{boundary}--\r\n".encode()
    )
    connection = http.client.HTTPSConnection("api.upstage.ai", timeout=60)
    try:
        connection.request(
            "POST",
            "/v1/document-digitization",
            body=body,
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise upstage_http_error(response)
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("OCR_RESPONSE_TOO_LARGE")
        return raw, response.getheader("x-request-id") or response.getheader("request-id")
    except (OSError, http.client.HTTPException):
        raise ValueError("UPSTAGE_OCR_REQUEST_FAILED") from None
    finally:
        connection.close()


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
        self._fallback = threading.local()
        self._fallback_pages = set()
        self._fallback_lock = threading.Lock()
        options = store.run_options(job)
        pages = json.loads(job["pages"])
        claims = options.get("claim_pages", pages)
        self._claim_pages = {i for i, page in enumerate(pages, 1) if page in claims}
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

    @contextmanager
    def claim_fallback_scope(self, page):
        # The prepared PDF's original-page map identifies claim pages. Evidence
        # pages never enter the new paid fallback, even when selected for parsing.
        with self._fallback_lock:
            if page not in self._claim_pages or (
                page not in self._fallback_pages and len(self._fallback_pages) >= 10
            ):
                raise ValueError("OCR_CLAIM_FALLBACK_SCOPE_INVALID")
            self._fallback_pages.add(page)
        previous = getattr(self._fallback, "active", False)
        self._fallback.active = True
        try:
            yield
        finally:
            self._fallback.active = previous

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
            COST_PER_PAGE["standard"] if getattr(self._fallback, "active", False) else COST,
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
