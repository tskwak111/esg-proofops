"""Hosted OCR money boundary and document-scoped replay over unchanged reader bytes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from proofops_api.hosted_store import HostedStore
import http.client
import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
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


def post_png(png: bytes) -> tuple[bytes, str | None]:
    """Hosted error decoding without changing the byte-pinned historical OCR reader."""
    from datetime import UTC, datetime

    from proofops.adapters.local.provider_errors import upstage_http_error

    # Byte-pinned OCR factory/export; retain the existing locked binding and restoration.
    from proofops.adapters.local.upstage_ocr_page import (  # type: ignore[attr-defined]
        PRICE_RECHECK_AT,
    )

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
def reader_scope(store: PageOCRStore) -> Iterator[None]:
    # Frozen version compositions all reuse this factory. Serialize hosted reads
    # and restore it, so concurrent tenants never share a document's ledger.
    with _binding_lock:
        previous = PageOCRStore.__dict__["from_env"]
        # Byte-pinned OCR factory/export; retain the existing locked binding and restoration.
        PageOCRStore.from_env = classmethod(lambda cls: store)  # type: ignore[assignment, method-assign]
        try:
            yield
        finally:
            # Byte-pinned OCR factory/export; retain the existing locked binding and restoration.
            PageOCRStore.from_env = previous  # type: ignore[method-assign]


class HostedOCRStore(PageOCRStore):
    def __init__(
        self,
        ledger: Path,
        spend: Path,
        *,
        store: HostedStore,
        job: dict[str, Any],
        local_run_id: str,
        post: Callable[[bytes], tuple[bytes, str | None]] | None = None,
    ) -> None:
        self.hosted, self.job, self.local_run_id, self.post = store, job, local_run_id, post
        self._fallback = threading.local()
        self._fallback_pages: set[int] = set()
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

    def _reserve(
        self, image: dict[str, Any], tenant_id: str, run_id: str, force: bool
    ) -> tuple[str, bool]:
        if tenant_id != self.job["tenant_id"] or run_id != self.local_run_id:
            raise ValueError("OCR_SOURCE_SCOPE_INVALID")
        # The inherited implementation is byte-pinned in upstage_ocr_page.
        return cast(tuple[str, bool], super()._reserve(image, tenant_id, run_id, force))  # type: ignore[no-untyped-call]

    @contextmanager
    def original_page_scope(self) -> Iterator[None]:
        """C3 parses the original; keep fallback admission in prepared-page space."""
        previous = getattr(self._fallback, "original_pages", None)
        self._fallback.original_pages = {
            page: index for index, page in enumerate(json.loads(self.job["pages"]), 1)
        }
        try:
            yield
        finally:
            self._fallback.original_pages = previous

    @contextmanager
    def claim_fallback_scope(self, page: int) -> Iterator[None]:
        # The prepared PDF's original-page map identifies claim pages. Evidence
        # pages never enter the new paid fallback, even when selected for parsing.
        original_pages = getattr(self._fallback, "original_pages", None)
        if original_pages is not None:
            if type(page) is not int or page not in original_pages:
                raise ValueError("OCR_CLAIM_FALLBACK_SCOPE_INVALID")
            page = original_pages[page]
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

    def _post(self, png: bytes) -> tuple[bytes, str | None]:
        def transport(request: dict[str, Any]) -> dict[str, Any]:
            raw, provider_id = self.post(png) if self.post else post_png(png)
            parse_response(raw)  # model/API1.1/exactly one billed page, bounded response
            return request | dict(actual_usd=str(COST), payload=(raw, provider_id))

        return cast(
            tuple[bytes, str | None],
            self.hosted.dispatch(
                self.job,
                "upstage-ocr",
                str(uuid4()),
                canonical_hash(dict(model=MODEL, png_sha256=sha256(png).hexdigest())),
                COST_PER_PAGE["standard"] if getattr(self._fallback, "active", False) else COST,
                transport,
                now=time.time(),
            )["payload"],
        )


class ReplayOCRStore(PageOCRStore):
    def __init__(self, ledger: Path) -> None:
        self.ledger = Path(ledger)

    def fetch(
        self, image: dict[str, Any], *, tenant_id: str, run_id: str, force: bool = False
    ) -> dict[str, Any]:
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
        # The inherited validation method is byte-pinned in upstage_ocr_page.
        return cast(dict[str, Any], self.validate(json.loads(row[0]), image, tenant_id=tenant_id))  # type: ignore[no-untyped-call]
