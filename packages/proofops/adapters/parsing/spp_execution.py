"""Opt-in parser execution; original source and receipt admission remain unchanged."""

import json
import os
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import copy_context
from hashlib import sha256
from threading import Lock
from uuid import uuid4

PROFILE = "spp-parse-v1"


def enabled(profile):
    value = (
        profile.get("execution_policy") if isinstance(profile, dict) else profile.execution_policy
    )
    return value == PROFILE


def table_verifier(policy_hash):
    # SPP composes v29b's v21 native/table policy, including its frozen readers.
    # Recompute that entire policy on every boundary; no cached approval/hash.
    from proofops.adapters.local import upstage_ocr_profile_v21 as reader

    if policy_hash != reader.table_policy_sha256():
        raise ValueError("TABLE_SOURCE_POLICY_MISMATCH")
    return reader


class LocalPageCache:
    """One isolated parser child and one source; never shared across runs/tenants.

    pdfplumber's parsed page objects retain the exact words and table inputs for
    the repair, auxiliary extraction and ink-location passes. Close every handle
    at the child boundary. This caches page decoding, never verification results.
    """

    def __init__(self):
        self.documents = {}

    @contextmanager
    def open(self, path):
        import pdfplumber

        key = str(path)
        if key not in self.documents:
            self.documents[key] = pdfplumber.open(path)
        yield self.documents[key]

    def close(self):
        for document in self.documents.values():
            document.close()


class PageRequests:
    """Overlap only the guaranteed first claim-page wave with the isolated JVM.

    Prepare PDFium subsets serially before local execution starts. Every actual
    request still passes through the same probe and its reservation/lease guards.
    Drain this wave before grounding. Retain exceptions for HX6's existing stop,
    retry and fallback rules; never launch a speculative second wave.
    """

    def __init__(self, source, profile, selected, cache_dir, probe):
        self.source, self.profile, self.selected = source, profile, selected
        self.cache_dir, self.probe = cache_dir, probe
        self.lock = Lock()
        self.prefetched = {}

    def _path(self, pages, mode):
        from proofops.adapters.parsing.opendataloader import _json
        from proofops.adapters.parsing.upstage_document import MODEL

        key = sha256(
            _json(
                dict(
                    source_sha256=self.source.sha256,
                    pages=pages,
                    model=MODEL,
                    mode=mode,
                    subset_policy="selected-pdf-h6-v1",
                )
            )
        ).hexdigest()
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self.cache_dir / (key + ".json")

    def _cached(self, path):
        from proofops.domain.provenance import canonical_hash

        if not path.exists():
            return None
        result = json.loads(path.read_bytes())
        if canonical_hash(result["raw_batches"]) != result["response_sha256"]:
            raise ValueError("UPSTAGE_CACHE_INTEGRITY_MISMATCH")
        return result, True

    def _send(self, path, payload, mode):
        from proofops.adapters.parsing.opendataloader import _json

        result = self.probe.parse_async(payload, request_id=str(uuid4()), mode=mode)
        temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
        temporary.write_bytes(_json(result))
        os.replace(temporary, path)
        return result, False

    def execute_local(self, execute):
        from proofops.adapters.parsing.h6_local_pages_v2 import subset

        # An evidence page may need paid OCR only after local readability is
        # known. Stop at that boundary so this is exactly HX6's first wave.
        prefix = []
        for page in self.selected[:4]:
            if page not in self.profile.claim_physical_pages:
                break
            prefix.append(page)
        prepared = []
        for page in prefix:
            path = self._path((page,), "standard")
            # Existing cache entries (including invalid ones) must reach the
            # original per-page recovery boundary, not abort local parsing here.
            if path.exists():
                continue
            try:
                payload = subset(self.source.content, (page,))
            except ValueError as error:
                future = Future()
                future.set_exception(error)
                self.prefetched[page] = future
            else:
                prepared.append((page, path, payload))
        if not prepared:
            return execute()
        with ThreadPoolExecutor(max_workers=4) as pool:
            for page, path, payload in prepared:
                self.prefetched[page] = pool.submit(
                    copy_context().run, self._send, path, payload, "standard"
                )
            return execute()

    def __call__(self, pages, mode):
        from proofops.adapters.parsing.h6_local_pages_v2 import subset

        with self.lock:
            future = self.prefetched.pop(pages[0], None) if len(pages) == 1 else None
        if future is not None:
            return future.result()
        path = self._path(pages, mode)
        cached = self._cached(path)
        if cached is not None:
            return cached
        with self.lock:
            payload = subset(self.source.content, pages)
        return self._send(path, payload, mode)
