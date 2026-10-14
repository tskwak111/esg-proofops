"""D2 reader: bind saved collections to the active reader and hold OCR failures per page."""

import os
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from http.client import HTTPException, HTTPSConnection
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from proofops.adapters.local import upstage_ocr_profile_v19 as v19
from proofops.adapters.local import upstage_ocr_profile_v20 as p3
from proofops.adapters.local.frozen_native_replay import _exec_private
from proofops.adapters.local.source_attestation_errors import ocr_acquisition_failure_code
from proofops.adapters.local.upstage_ocr_page import (
    MAX_RESPONSE_BYTES,
    MODEL,
    PRICE_RECHECK_AT,
    parse_response,
)
from proofops.adapters.local.upstage_ocr_page import (
    PageOCRStore as BasePageOCRStore,
)
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v21"
OCR_ACQUISITION_REASON_PREFIX = "ocr_acquisition_unresolved:"
_PAGE_OCR_SOURCE = Path(__file__).with_name("upstage_ocr_page.py")


def claim_source_policy():
    from proofops.adapters.local import source_attestation_errors

    return dict(
        p3.claim_source_policy(),
        profile=PROFILE,
        previous_reader_sha256=sha256(Path(p3.__file__).read_bytes()).hexdigest(),
        ocr_page_reader_sha256=sha256(_PAGE_OCR_SOURCE.read_bytes()).hexdigest(),
        failure_code_policy_sha256=sha256(
            Path(source_attestation_errors.__file__).read_bytes()
        ).hexdigest(),
        collection_replay="active-reader-instance-page-collections-v1",
        acquisition_failure="page-local-unresolved-with-sanitized-cause-v1",
        verifier_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
    )


def native_policy():
    return dict(p3.native_policy(), mode=PROFILE, i17=claim_source_policy())


def table_policy_sha256():
    return canonical_hash(
        dict(previous=v19.previous.table_policy_sha256(), i17=native_policy())
    )


def table_span_policy():
    return dict(v19.previous.table_span_policy(), profile=PROFILE, i17=claim_source_policy())


def _post_png(png):
    """Versioned transport that records a timeout as a fixed code, never its details."""
    if datetime.now(UTC) >= PRICE_RECHECK_AT:
        raise ValueError("PRICE_RECHECK_REQUIRED")
    key = os.environ.get("UPSTAGE_API_KEY", "")
    if not key or any(char.isspace() for char in key):
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
    connection = HTTPSConnection("api.upstage.ai", timeout=60)
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
            raise ValueError(f"UPSTAGE_HTTP_{response.status}")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("OCR_RESPONSE_TOO_LARGE")
        return raw, response.getheader("x-request-id") or response.getheader("request-id")
    except TimeoutError:
        raise ValueError("UPSTAGE_OCR_TIMEOUT") from None
    except (OSError, HTTPException):
        raise ValueError("UPSTAGE_OCR_REQUEST_FAILED") from None
    finally:
        connection.close()


def _checked_transport(transport):
    def checked(png):
        try:
            raw, provider_id = transport(png)
        except TimeoutError:
            raise ValueError("UPSTAGE_OCR_TIMEOUT") from None
        except (OSError, HTTPException):
            raise ValueError("UPSTAGE_OCR_REQUEST_FAILED") from None
        try:
            parse_response(raw)
        except (TypeError, ValueError):
            raise ValueError("UPSTAGE_OCR_INVALID_RESPONSE") from None
        return raw, provider_id

    return checked


class PageOCRStore(BasePageOCRStore):
    """The same ledger contract with D2-only timeout and response-format codes."""

    def __init__(self, ledger, spend, *, transport=None, cap_usd=None, max_calls=None):
        super().__init__(
            ledger,
            spend,
            transport=_checked_transport(transport or _post_png),
            **({} if cap_usd is None else {"cap_usd": cap_usd}),
            **({} if max_calls is None else {"max_calls": max_calls}),
        )

    @classmethod
    def from_env(cls):
        base = BasePageOCRStore.from_env()
        # Hosted/Q2 scopes inject a store instance whose _reserve method owns
        # the caller's ledger fence. Keep that instance and wrap only its
        # transport so its authorization and accounting remain authoritative.
        if hasattr(base, "transport") and not getattr(base, "_d2_checked_transport", False):
            transport = _post_png if type(base) is BasePageOCRStore else base.transport
            base.transport = _checked_transport(transport)
            base._d2_checked_transport = True
        return base


class _D2AvailableStore:
    """Turn known acquisition errors into typed page holds; integrity errors bubble."""

    def __init__(self, store):
        self.store = store

    def __getattr__(self, name):
        return getattr(self.store, name)

    def fetch(self, *args, **kwargs):
        try:
            return self.store.fetch(*args, **kwargs)
        except ValueError as error:
            code = ocr_acquisition_failure_code(error)
            if code is None:
                raise
            raise ValueError("OCR_PAGE_ACQUISITION_FAILED:" + code) from None


class CompleteReader(p3._reader.CompleteReader):
    def __init__(self, store, *, run_id):
        super().__init__(_D2AvailableStore(store), run_id=run_id)


_previous = SimpleNamespace(
    for_run=lambda run_id: CompleteReader(PageOCRStore.from_env(), run_id=run_id),
    native_policy=p3.native_policy,
    table_policy_sha256=v19.previous.table_policy_sha256,
    table_span_policy=v19.previous.table_span_policy,
)
_reader = _exec_private(
    Path(__file__).parent,
    "upstage_ocr_profile_hx5_v16.py",
    "proofops.adapters.local._d2_hx5_size",
)
_reader.PROFILE = PROFILE
_reader.previous = _previous
_reader.claim_source_policy = claim_source_policy
_reader.native_policy = native_policy
_reader.table_policy_sha256 = table_policy_sha256
_reader.table_span_policy = table_span_policy
_ReaderBase = _reader.Reader


def _saved_page_collections(receipt):
    base = receipt.get("base_receipt", {}) if isinstance(receipt, dict) else {}
    return base.get("page_collections", []) if isinstance(base, dict) else []


@contextmanager
def _retained_collections(reader, receipt):
    # AuthorizedNormalOCR._modules reads this from the CompleteReader instance
    # that is actually invoking it; the historical helper descended too far.
    active = reader.previous
    old = getattr(active, "_saved_collections", None)
    active._saved_collections = _saved_page_collections(receipt)
    try:
        yield
    finally:
        if old is None:
            delattr(active, "_saved_collections")
        else:
            active._saved_collections = old


def _unique(values):
    result, seen = [], set()
    for value in values:
        digest = canonical_hash(value)
        if digest not in seen:
            seen.add(digest)
            result.append(deepcopy(value))
    return result


def _merge_receipt(left, right):
    merged = deepcopy(left)
    for key, value in right.items():
        if key == "artifact_sha256":
            continue
        if key not in merged:
            merged[key] = deepcopy(value)
        elif isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_receipt(merged[key], value)
        elif isinstance(merged[key], list) and isinstance(value, list):
            values = merged[key] + value
            merged[key] = sorted(set(values)) if key == "physical_pages" else _unique(values)
        elif merged[key] != value:
            raise ValueError("OCR_PAGE_ATTESTATION_MERGE_MISMATCH")
    if "artifact_sha256" in left or "artifact_sha256" in right:
        merged["artifact_sha256"] = canonical_hash(
            {key: value for key, value in merged.items() if key != "artifact_sha256"}
        )
    return merged


def _ref_key(ref):
    return (ref["source_id"], ref["page_num"], ref["char_start"], ref["char_end"])


class Reader(_ReaderBase):
    def replay_native_sources(self, receipt, graph, source, *, tenant_id):
        with _retained_collections(self, receipt):
            return _ReaderBase.replay_native_sources(
                self, receipt, graph, source, tenant_id=tenant_id
            )

    def replay_tables(self, receipt, graph, source, *, tenant_id):
        with _retained_collections(self, receipt):
            return _ReaderBase.replay_tables(self, receipt, graph, source, tenant_id=tenant_id)

    def attest_claim_spans(self, graph, source, refs, *, tenant_id):
        refs = tuple(refs)
        if self._large(graph, source, tenant_id):
            return _ReaderBase.attest_claim_spans(
                self, graph, source, refs, tenant_id=tenant_id
            )
        saved_failures = getattr(self, "_replay_failed_refs", {})
        active_collections = getattr(self.previous, "_saved_collections", None)
        saved_pages = {
            item.get("manifest", {}).get("physical_page")
            for item in (active_collections or [])
            if isinstance(item, dict)
        }
        successful, failed = [], []
        for page in sorted({ref.page_num for ref in refs}):
            page_refs = tuple(ref for ref in refs if ref.page_num == page)
            held_refs = [saved_failures.get(_ref_key(asdict(ref))) for ref in page_refs]
            held = [record for record in held_refs if record is not None]
            work_refs = tuple(ref for ref, record in zip(page_refs, held_refs) if record is None)
            if active_collections is not None and page not in saved_pages:
                failed.extend(deepcopy(record) for record in held)
                if not work_refs:
                    continue
            try:
                if work_refs:
                    successful.append(
                        self.previous.attest_claim_spans(
                            graph, source, work_refs, tenant_id=tenant_id
                        )
                    )
            except ValueError as error:
                code = ocr_acquisition_failure_code(error)
                if code is None and str(error) == "OCR_REPLAY_PAGE_MISSING":
                    if held and len(held) == len(page_refs):
                        failed.extend(deepcopy(record) for record in held)
                        continue
                    code = "OCR_PENDING_OR_FAILED"
                if code is None:
                    raise
                failed.extend(
                    dict(
                        ref=asdict(ref),
                        status="unresolved",
                        reason=OCR_ACQUISITION_REASON_PREFIX + code,
                    )
                    for ref in work_refs
                )
            failed.extend(deepcopy(record) for record in held if record not in failed)

        if successful:
            merged = successful[0]
            for item in successful[1:]:
                merged = _merge_receipt(merged, item)
        else:
            merged = dict(
                **self._identity(graph),
                schema="claim_source_hx5_attestation_v1",
                pb1_cell_proofs=[],
                records=[],
            )
        if failed:
            merged["records"] = _unique(merged.get("records", []) + failed)
        return self._receipt(merged)

    def recompute_claim_receipt(self, receipt, graph, source, refs, *, tenant_id):
        if receipt.get("policy") != claim_source_policy() or receipt.get("run_id") != self.run_id:
            raise ValueError("OCR_POLICY_OR_RUN_MISMATCH")
        base = receipt.get("base_receipt", {})
        failed_refs = {}
        if isinstance(base, dict):
            for record in base.get("records", []):
                ref, reason = record.get("ref"), record.get("reason")
                if (
                    isinstance(ref, dict)
                    and record.get("status") == "unresolved"
                    and isinstance(reason, str)
                    and reason.startswith(OCR_ACQUISITION_REASON_PREFIX)
                    and ocr_acquisition_failure_code(
                        ValueError(reason[len(OCR_ACQUISITION_REASON_PREFIX) :])
                    )
                    == reason[len(OCR_ACQUISITION_REASON_PREFIX) :]
                ):
                    failed_refs[_ref_key(ref)] = record
        previous_failures = getattr(self, "_replay_failed_refs", None)
        self._replay_failed_refs = failed_refs
        try:
            with _retained_collections(self, receipt):
                expected = self.attest_claim_spans(
                    graph, source, tuple(refs), tenant_id=tenant_id
                )
        finally:
            if previous_failures is None:
                delattr(self, "_replay_failed_refs")
            else:
                self._replay_failed_refs = previous_failures
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")
        return expected

    def recompute_table_span_receipt(self, receipt, graph, source, refs, *, tenant_id):
        expected = self.attest_table_spans(
            graph,
            source,
            refs,
            tenant_id=tenant_id,
            collections=receipt.get("base_receipt", {}).get("page_collections", []),
        )
        if canonical_hash(receipt) != canonical_hash(expected):
            raise ValueError("OCR_TABLE_SPAN_RECEIPT_MISMATCH")
        return expected

    def attest_table_spans(self, graph, source, refs, *, tenant_id, collections=None):
        refs = tuple(refs)
        if self._large(graph, source, tenant_id):
            base = dict(
                **self._identity(graph),
                schema="table_span_i17_attestation_v1",
                records=[
                    dict(ref=asdict(ref), status="unresolved", reason="SOURCE_PROOF_INPUT_LIMIT")
                    for ref in refs
                ],
            )
        else:
            base = self.previous.attest_table_spans(
                graph, source, refs, tenant_id=tenant_id, collections=collections
            )
        return self._receipt(base, table=True)


_reader.Reader = Reader


def for_run(run_id):
    return Reader(run_id=run_id)


def attest_claim_spans(graph, source, refs, *, tenant_id, run_id=None):
    return for_run(run_id).attest_claim_spans(graph, source, refs, tenant_id=tenant_id)


def attest_tables(graph, source, *, tenant_id, run_id=None):
    return for_run(run_id).attest_tables(graph, source, tenant_id=tenant_id)


def replay_tables(receipt, graph, source, *, tenant_id):
    return for_run(receipt["run_id"]).replay_tables(receipt, graph, source, tenant_id=tenant_id)


_replay = _exec_private(
    Path(__file__).parent,
    "upstage_ocr_profile_hx5_v16.py",
    "proofops.adapters.local._d2_hx5_replay",
)
_replay.for_run = for_run
replay_claim_spans = _replay.replay_claim_spans
