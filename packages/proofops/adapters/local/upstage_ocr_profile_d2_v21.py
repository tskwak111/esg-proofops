"""D2 reader: bind saved collections to the active reader and hold OCR failures per page."""

import os
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from http.client import HTTPException, HTTPSConnection
from math import isfinite
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
# Receipts created before the residual fix used this table-policy preimage.
# Their embedded reader policy still identifies the exact D2 reader; replay
# accepts this digest only after recomputing and matching the complete receipt.
_HISTORICAL_TABLE_POLICY_SHA256 = frozenset(
    {
        "baf6b4ae937e1b66f626e838986b952804ca7303872e7d4a9d7577257d415eaf",
        # D2 receipt policy before page-local claim attestations kept their
        # nested baseline receipt hashes intact.
        "38ee915518756b6578573d93bc9c80a1fb85bb1f9ce3e1d0cdae50ab6bf5c337",
    }
)
_HISTORICAL_READER_POLICY_SHA256 = frozenset(
    {
        "dd40a1c77c4dbb26c7f5047e07028cc272f6ae8381dadcb0073c002f1b00613b",
        "f80c93a6b7efccb3130c94c7faab9f33bbcc0760a70f824d5b58dc8cce938350",
    }
)
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

    def _modules(self, graph, source, tenant_id, collections=None):
        modules, seen = super()._modules(graph, source, tenant_id, collections)
        if not getattr(self, "_d2_table_attestation", False):
            return modules, seen
        holds = self._d2_table_acquisition_holds
        replay_holds = self._d2_table_replay_holds
        for module in modules.values():
            read = getattr(module, "_rendered_cell", None)
            if callable(read):
                module._rendered_cell = _hold_table_acquisition_failure(
                    read, holds, replay_holds
                )
        return modules, seen


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
    if isinstance(base, dict) and base.get("schema") == "claim_source_hx5_page_attestation_v1":
        collections = []
        for entry in base.get("page_receipts", []):
            item = entry.get("receipt", {}) if isinstance(entry, dict) else {}
            if isinstance(item, dict):
                collections.extend(item.get("page_collections", []))
        return _unique(collections)
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


def _ref_key(ref):
    return (ref["source_id"], ref["page_num"], ref["char_start"], ref["char_end"])


def _table_hold_key(page, box):
    page_num = getattr(page, "page_number", None)
    if type(page_num) is not int or page_num < 1:
        return None
    try:
        values = tuple(float(value) for value in box)
    except (TypeError, ValueError):
        return None
    if len(values) != 4 or not all(isfinite(value) for value in values):
        return None
    return page_num, values


def _hold_table_acquisition_failure(read, holds, replay_holds):
    """Keep a failed rendered-cell OCR read local to the verifier selection."""
    def checked(page, box, **kwargs):
        key = _table_hold_key(page, box)
        try:
            return read(page, box, **kwargs)
        except ValueError as error:
            code = ocr_acquisition_failure_code(error)
            if code is None and str(error) == "OCR_REPLAY_PAGE_MISSING":
                if key in replay_holds:
                    reason = replay_holds[key]
                    holds[key] = reason
                    raise ValueError(reason) from None
                code = "OCR_PENDING_OR_FAILED"
            if code is None:
                raise
            reason = OCR_ACQUISITION_REASON_PREFIX + code
            if key is not None:
                holds[key] = reason
            raise ValueError(reason) from None

    return checked


@contextmanager
def _table_attestation(reader, replay_holds=None):
    previous = getattr(reader, "_d2_table_attestation", None)
    previous_holds = getattr(reader, "_d2_table_acquisition_holds", None)
    previous_replay_holds = getattr(reader, "_d2_table_replay_holds", None)
    reader._d2_table_attestation = True
    reader._d2_table_acquisition_holds = {}
    reader._d2_table_replay_holds = (
        {} if replay_holds is None else replay_holds
    )
    try:
        yield reader._d2_table_acquisition_holds
    finally:
        if previous is not None:
            reader._d2_table_attestation = previous
        else:
            delattr(reader, "_d2_table_attestation")
        for name, value in (
            ("_d2_table_acquisition_holds", previous_holds),
            ("_d2_table_replay_holds", previous_replay_holds),
        ):
            if value is None:
                delattr(reader, name)
            else:
                setattr(reader, name, value)


def _saved_table_acquisition_holds(receipt):
    holds = {}
    items = receipt.get("table_acquisition_holds", []) if isinstance(receipt, dict) else []
    if not isinstance(items, list):
        raise ValueError("OCR_TABLE_RECEIPT_MISMATCH")
    for item in items:
        if not isinstance(item, dict) or set(item) != {"page", "box", "reason"}:
            raise ValueError("OCR_TABLE_RECEIPT_MISMATCH")
        page, box, reason = item["page"], item["box"], item["reason"]
        if type(page) is not int or page < 1 or not isinstance(box, list):
            raise ValueError("OCR_TABLE_RECEIPT_MISMATCH")
        key = _table_hold_key(SimpleNamespace(page_number=page), box)
        if (
            key is None
            or not isinstance(reason, str)
            or not reason.startswith(OCR_ACQUISITION_REASON_PREFIX)
            or ocr_acquisition_failure_code(
                ValueError(reason[len(OCR_ACQUISITION_REASON_PREFIX) :])
            )
            != reason[len(OCR_ACQUISITION_REASON_PREFIX) :]
            or key in holds
        ):
            raise ValueError("OCR_TABLE_RECEIPT_MISMATCH")
        holds[key] = reason
    return holds


def _record_table_acquisition_holds(receipt, holds):
    if not holds:
        return receipt
    receipt["table_acquisition_holds"] = [
        dict(page=page, box=list(box), reason=reason)
        for (page, box), reason in sorted(holds.items())
    ]
    receipt["artifact_sha256"] = canonical_hash(
        {key: value for key, value in receipt.items() if key != "artifact_sha256"}
    )
    return receipt


class Reader(_ReaderBase):
    def replay_native_sources(self, receipt, graph, source, *, tenant_id):
        with _retained_collections(self, receipt):
            return _ReaderBase.replay_native_sources(
                self, receipt, graph, source, tenant_id=tenant_id
            )

    def replay_tables(self, receipt, graph, source, *, tenant_id):
        with _retained_collections(self, receipt):
            with _table_attestation(
                self.previous, _saved_table_acquisition_holds(receipt)
            ):
                expected = self.attest_tables(graph, source, tenant_id=tenant_id)
                if canonical_hash(receipt) != canonical_hash(expected):
                    if not self._matches_historical_table_receipt(receipt, expected):
                        raise ValueError("OCR_TABLE_RECEIPT_MISMATCH")
                if self._large(graph, source, tenant_id):
                    return graph
                return self.previous.replay_tables(
                    receipt["base_receipt"], graph, source, tenant_id=tenant_id
                )

    def attest_tables(self, graph, source, *, tenant_id):
        return self._attest_tables(graph, source, tenant_id=tenant_id)

    def _attest_tables(self, graph, source, *, tenant_id, replay_holds=None):
        if replay_holds is None:
            replay_holds = getattr(self.previous, "_d2_table_replay_holds", None)
        with _table_attestation(self.previous, replay_holds) as holds:
            receipt = _ReaderBase.attest_tables(self, graph, source, tenant_id=tenant_id)
        return _record_table_acquisition_holds(receipt, holds)

    def _matches_historical_table_receipt(self, receipt, expected):
        if (
            receipt.get("rendered_reader_profile") != PROFILE
            or receipt.get("run_id") != self.run_id
            or canonical_hash(receipt.get("reader_policy"))
            not in _HISTORICAL_READER_POLICY_SHA256
            or receipt.get("policy_sha256") not in _HISTORICAL_TABLE_POLICY_SHA256
        ):
            return False
        historical = deepcopy(expected)
        historical["reader_policy"] = deepcopy(receipt["reader_policy"])
        historical["policy_sha256"] = receipt["policy_sha256"]
        historical["artifact_sha256"] = canonical_hash(
            {key: value for key, value in historical.items() if key != "artifact_sha256"}
        )
        return canonical_hash(receipt) == canonical_hash(historical)

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
        page_receipts, records, cell_proofs, failed = [], [], [], []
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
                    item = self.previous.attest_claim_spans(
                        graph, source, work_refs, tenant_id=tenant_id
                    )
                    page_receipts.append(dict(page_num=page, receipt=item))
                    records.extend(item.get("records", []))
                    cell_proofs.extend(item.get("pb1_cell_proofs", []))
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

        base = dict(
            **self._identity(graph),
            schema="claim_source_hx5_page_attestation_v1",
            pb1_cell_proofs=_unique(cell_proofs),
            records=_unique(records + failed),
            page_receipts=page_receipts,
        )
        return self._receipt(base)

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
# The re-exported function is nested in its own private replay module, so the
# assignment above does not replace that function's global reader factory.
_replay.replay_claim_spans.__globals__["for_run"] = for_run
replay_claim_spans = _replay.replay_claim_spans
