"""Provider probes with one durable hosted reservation per physical attempt."""

import io
import json
import random
import time
from decimal import ROUND_CEILING, Decimal
from uuid import uuid4

from proofops.adapters.local.openai import (
    MODEL as OPENAI_MODEL,
)
from proofops.adapters.local.openai import (
    PRICE_RECHECK_AT,
    OpenAIProbe,
    OpenAITransient403,
    token_cost,
)
from proofops.adapters.local.openai import (
    WIRE_POLICY as OPENAI_WIRE_POLICY,
)
from proofops.adapters.local.openrouter import MODEL, WIRE_POLICY, OpenRouterProbe
from proofops.adapters.local.upstage_parse import (
    ALLOWED_MODELS,
    COST_PER_PAGE,
    UpstageParseProbe,
)
from proofops.application.openai_retry import POLICY as T1_RETRY_POLICY
from proofops.application.openai_retry import POLICY_HASH as T1_RETRY_POLICY_HASH
from proofops.domain.provenance import canonical_hash
from pypdf import PdfReader, PdfWriter


def rounded_cost(value) -> str:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("PROVIDER_COST_INVALID")
    return str(amount.quantize(Decimal("0.000001"), rounding=ROUND_CEILING))


def broker_dispatch(store, *args, **kwargs):
    from proofops.application.budget import BudgetExceeded

    from proofops_api.hosted_contracts import HostedError

    try:
        return store.dispatch(*args, **kwargs)
    except HostedError as error:
        if error.code == "BUDGET_EXCEEDED":
            raise BudgetExceeded("BUDGET_EXHAUSTED") from None
        raise


class HostedLunaProbe(OpenRouterProbe):
    def __init__(self, *args, store, job, post=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.store, self.job, self.post = store, job, post

    def _post(self, body):
        # Includes every schema retry: each attempt gets a separate reservation.
        if body.get("model") != MODEL or body.get("provider") != WIRE_POLICY["provider"]:
            raise ValueError("HOSTED_WIRE_POLICY_REQUIRED")

        def transport(request):
            data = self.post(body) if self.post else super(HostedLunaProbe, self)._post(body)
            if data.get("model") != MODEL:
                raise ValueError("HOSTED_MODEL_MISMATCH")
            return request | dict(actual_usd=rounded_cost(data["usage"]["cost"]), payload=data)

        response = broker_dispatch(
            self.store,
            self.job,
            "openrouter",
            str(uuid4()),
            canonical_hash(body),
            Decimal("0.011"),
            transport,
            now=time.time(),
        )
        return response["payload"]


class HostedOpenAILunaProbe(OpenAIProbe):
    def __init__(self, *args, store, job, post=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.store, self.job, self.post = store, job, post
        # Sanitized errors survive scratch cleanup, under the document's purge ownership.
        self.http_error_directory = (
            store.document_dir(job["tenant_id"], job["document_id"]) / "provider-http-errors"
        )

    def _authorize_response_request(self):
        from proofops_api.hosted_contracts import HostedError

        with self.store.transaction(readonly=True, operation="response_authorize") as db:
            now = time.time()
            self.store._fenced(db, self.job, now)
            doc = self.store._document(db, self.job["tenant_id"], self.job["document_id"])
            if now >= doc["expires"]:
                raise HostedError("SOURCE_EXPIRED")

    def _post(self, body):
        if body.get("model") != OPENAI_MODEL or OPENAI_WIRE_POLICY["endpoint"] != (
            "https://api.openai.com/v1/chat/completions"
        ):
            raise ValueError("HOSTED_WIRE_POLICY_REQUIRED")

        def transport(request):
            with control_before_send():
                if self.post and getattr(self, "provider_scheduler", None):
                    self.http_transport_pacing()
            try:
                data = (
                    self.post(body)
                    if self.post
                    else super(HostedOpenAILunaProbe, self)._post(
                        body, client_request_id=request["request_id"]
                    )
                )
            except TimeoutError:
                if inventory is not None:
                    inventory["terminal_code"] = "SC1_PROVIDER_TIMEOUT"
                raise
            if data.get("model") != OPENAI_MODEL:
                raise ValueError("HOSTED_MODEL_MISMATCH")
            return request | dict(actual_usd=rounded_cost(token_cost(data["usage"])), payload=data)

        from proofops.adapters.local.i27_inventory_execution import current, transient_code
        from proofops.adapters.local.openai_connections import (
            OpenAIConnectNotSent,
            OpenAIControlNotSent,
            control_before_send,
        )
        from proofops.adapters.local.provider_concurrency import ProviderCircuitOpen
        from proofops.adapters.local.provider_scheduler import ProviderAdmissionDeferred
        from proofops.application.i27_inventory import POLICY as I27_POLICY

        inventory = current.get()
        scope = self._dispatch_context.get()
        diagnostic_context = dict(
            state=self.ledger.parent,
            role=(self._response_context.get() or (getattr(self, "response_role", None), 0))[0],
            request_bytes=len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()),
        )
        for attempt in range(2):
            if inventory is not None:
                inventory["terminal_code"] = None
            allow = (
                self.http_retry_policy == T1_RETRY_POLICY
                and scope is not None
                and not scope["transport_retries"]
                and attempt == 0
            )
            call_id = str(uuid4())
            if self.transport_policy:
                import sqlite3

                with sqlite3.connect(self.ledger, timeout=30) as db:
                    db.execute(
                        "INSERT INTO probe_transport_attempts VALUES (?,?,?,'reserved',NULL)",
                        (call_id, scope["request_id"], "0.02"),
                    )
            try:
                if self.http_dispatch_guard and not getattr(self, "provider_scheduler", None):
                    admission = getattr(self, "http_dispatch_admission", None)
                    if admission is not None:
                        admission()
                with self.physical_attempt_scope():
                    response = broker_dispatch(
                        self.store,
                        self.job,
                        "openai",
                        call_id,
                        canonical_hash(body),
                        Decimal("0.011"),
                        transport,
                        now=time.time(),
                        allow_transient_403=allow,
                        allow_model_partial=self.provider_resilience is not None,
                        allow_response_uncertainty=self.response_uncertainty_policy is not None,
                        allow_connect_not_sent=self.transport_policy is not None,
                        allow_ops2_fallback=getattr(self, "ops2_enabled", False),
                        diagnostic_context=diagnostic_context,
                    )
                if self.transport_policy:
                    self._finish_transport_attempt(call_id, "response_received", None)
                if inventory is not None:
                    inventory["terminal_code"] = None
                return response["payload"]
            except OpenAIControlNotSent as error:
                if self.transport_policy:
                    self._finish_transport_attempt(call_id, "never_sent", None)
                    self._settle_never_sent(scope["request_id"])
                raise error.signal from None
            except OpenAIConnectNotSent as error:
                if not self.transport_policy:
                    raise
                self._finish_transport_attempt(
                    call_id, "never_sent", json.dumps(error.diagnostic, sort_keys=True)
                )
                if getattr(self, "ops2_enabled", False):
                    self._settle_never_sent(scope["request_id"])
                    raise
                if attempt != 0 or scope["transport_retries"]:
                    self._settle_never_sent(scope["request_id"])
                    raise ValueError("PROVIDER_PROCESSING_FAILED") from None
                scope["transport_retries"].append(
                    dict(
                        policy_sha256=canonical_hash(self.transport_policy),
                        failed_call_id=call_id,
                        dispatch_state="never_sent",
                        diagnostic_sha256=canonical_hash(error.diagnostic),
                    )
                )
                self._authorize_response_request()
                from proofops.adapters.local.openai import now as price_now

                if price_now() >= PRICE_RECHECK_AT:
                    self._settle_never_sent(scope["request_id"])
                    raise ValueError("PRICE_RECHECK_REQUIRED")
            except OpenAITransient403 as error:
                if not allow:
                    raise
                delay = min(
                    T1_RETRY_POLICY["max_delay_seconds"],
                    max(T1_RETRY_POLICY["min_delay_seconds"], error.retry_after_seconds)
                    + random.uniform(0, T1_RETRY_POLICY["jitter_seconds"]),
                )
                scope["transport_retries"].append(
                    dict(
                        policy_sha256=T1_RETRY_POLICY_HASH,
                        failed_call_id=call_id,
                        diagnostic_sha256=canonical_hash(error.diagnostic),
                        delay_seconds=delay,
                        http_request_id=error.diagnostic["http_request_id"],
                    )
                )
                time.sleep(delay)
                from proofops.adapters.local.openai import now as price_now

                if price_now() >= PRICE_RECHECK_AT:
                    raise ValueError("PRICE_RECHECK_REQUIRED")
                self._authorize_response_request()
            except (ProviderCircuitOpen, ProviderAdmissionDeferred):
                if self.transport_policy:
                    self._finish_transport_attempt(call_id, "never_sent", None)
                    self._settle_never_sent(scope["request_id"])
                raise
            except BaseException as error:
                from proofops_api.hosted_diagnostics import record_dispatch_failure

                # Also cover scheduler/probe bookkeeping outside broker_dispatch.
                # A more precise broker diagnostic for this call_id wins O_EXCL.
                record_dispatch_failure(
                    self.store,
                    self.job,
                    call_id,
                    "openai",
                    canonical_hash(body),
                    "probe_attempt",
                    error,
                    diagnostic_context,
                )
                if self.transport_policy:
                    self._finish_transport_attempt(call_id, "unknown", None)
                code = transient_code(error) if inventory is not None else None
                if (
                    inventory is not None
                    and str(error) == "PROCESSING_UNCERTAIN"
                    and inventory["terminal_code"] == "SC1_PROVIDER_TIMEOUT"
                ):
                    code = "SC1_PROVIDER_TIMEOUT"
                if inventory is not None:
                    inventory["terminal_code"] = code
                if code is not None:
                    inventory["attempts"].append(dict(call_id=call_id, code=code))
                    if (
                        code.startswith("OPENAI_HTTP_5")
                        and attempt == 0
                        and inventory["retries"] < I27_POLICY["max_retries"]
                        and scope is not None
                        and not scope["transport_retries"]
                    ):
                        delay = I27_POLICY["backoff_base_seconds"] * (
                            I27_POLICY["backoff_multiplier"] ** inventory["retries"]
                        )
                        inventory["retries"] += 1
                        scope["transport_retries"].append(
                            dict(
                                policy_sha256=canonical_hash(I27_POLICY),
                                failed_call_id=call_id,
                                delay_seconds=delay,
                            )
                        )
                        time.sleep(delay)
                        from proofops.adapters.local.openai import now as price_now

                        if price_now() >= PRICE_RECHECK_AT:
                            inventory["terminal_code"] = None
                            raise ValueError("PRICE_RECHECK_REQUIRED")
                        inventory["terminal_code"] = None
                        self._authorize_response_request()
                        continue
                raise
        raise ValueError("OPENAI_HTTP_403")


class HostedParseProbe(UpstageParseProbe):
    def __init__(self, *args, store, job, post=None, integrated=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.store, self.job, self.post = store, job, post
        self.integrated = integrated

    def _post_parse(self, pdf_bytes, mode, path="/v1/document-digitization"):
        if self.integrated:
            # parse_async owns the single hosted reservation around POST + GET collection.
            if path != "/v1/document-digitization/async":
                raise ValueError("HOSTED_PARSE_TRANSPORT_INVALID")
            return (
                self.post(pdf_bytes, mode)
                if self.post
                else super()._post_parse(pdf_bytes, mode, path)
            )
        pages = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
        if path != "/v1/document-digitization" or not 1 <= pages <= 2:
            raise ValueError("HOSTED_PARSE_SCOPE_INVALID")
        cost = COST_PER_PAGE[mode] * pages

        def transport(request):
            data = (
                self.post(pdf_bytes, mode)
                if self.post
                else super(HostedParseProbe, self)._post_parse(pdf_bytes, mode)
            )
            usage = data.get("usage", {})
            if (
                data.get("model") not in ALLOWED_MODELS
                or usage.get("pages") != pages
                or usage.get(mode) != list(range(1, pages + 1))
                or usage.get("enhanced" if mode == "standard" else "standard", [])
            ):
                raise ValueError("HOSTED_PARSE_RECEIPT_INVALID")
            return request | dict(actual_usd=str(cost), payload=data)

        return broker_dispatch(
            self.store,
            self.job,
            "upstage-parse",
            str(uuid4()),
            canonical_hash(dict(sha256=canonical_hash(pdf_bytes.hex()), mode=mode, pages=pages)),
            cost,
            transport,
            now=time.time(),
        )["payload"]

    def parse_async(self, pdf_bytes, *, request_id, mode="standard"):
        if self.integrated:
            pages = len(PdfReader(io.BytesIO(pdf_bytes), strict=True).pages)
            if mode not in COST_PER_PAGE or not 1 <= pages <= 30:
                raise ValueError("HOSTED_PARSE_SCOPE_INVALID")
            bound = COST_PER_PAGE[mode] * pages

            def transport(request):
                result = super(HostedParseProbe, self).parse_async(
                    pdf_bytes, request_id=request_id, mode=mode
                )
                return request | dict(actual_usd=str(bound), payload=result)

            return broker_dispatch(
                self.store,
                self.job,
                "upstage-parse",
                request_id,
                canonical_hash(dict(pdf=canonical_hash(pdf_bytes.hex()), mode=mode, pages=pages)),
                bound,
                transport,
                now=time.time(),
            )["payload"]
        # Keep synchronous, brokered <=2-page calls; map each receipt to the
        # prepared subset before canonical graph conversion. MP1 can replace this
        # factory later using the same pinned claim/evidence selection.
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 30:
            raise ValueError("HOSTED_PARSE_SCOPE_INVALID")
        batches, receipts = [], []
        for start in range(0, len(reader.pages), 2):
            writer, buffer = PdfWriter(), io.BytesIO()
            for page in reader.pages[start : start + 2]:
                writer.add_page(page)
            writer.write(buffer)
            result = self.parse(buffer.getvalue(), request_id=f"{request_id}-{start}", mode=mode)
            batch = json.loads(json.dumps(result["raw_response"]))
            batch["usage"][mode] = [p + start for p in batch["usage"][mode]]
            for element in batch["elements"]:
                if type(element.get("page")) is not int or not 1 <= element["page"] <= len(
                    writer.pages
                ):
                    raise ValueError("HOSTED_PARSE_PAGE_INVALID")
                element["page"] += start
            batches.append(batch)
            receipts.append({k: v for k, v in result.items() if k != "raw_response"})
        return dict(
            raw_batches=batches,
            response_sha256=canonical_hash(batches),
            receipts=receipts,
            model=receipts[0]["model"],
            pages=len(reader.pages),
            mode=mode,
            cost_with_vat_reserve_usd=str(COST_PER_PAGE[mode] * len(reader.pages)),
        )
