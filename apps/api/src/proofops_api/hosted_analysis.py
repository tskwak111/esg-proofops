"""Explicit operator opt-in and brokered R108 provider adapters."""

import fcntl
import io
import json
import os
import random
import signal
import subprocess
import sys
import time
from datetime import date
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
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

# Release-owned approval, never populated from operator JSON or environment.
RENDERED_READER_POLICY = json.loads(
    (Path(__file__).resolve().parents[4] / "config/hosted_rendered_readers.json").read_text()
)
GATE_PASSED_RENDERED_READERS = frozenset(RENDERED_READER_POLICY["gate_passed"])
KNOWN_RENDERED_READERS = frozenset(
    {
        "upstage-ocr-page-v1",
        "upstage-ocr-page-v2",
        "upstage-ocr-page-v3",
        "upstage-ocr-page-v4",
        "upstage-ocr-page-v5",
        "upstage-ocr-page-v6",
        "upstage-ocr-page-v9",
        "upstage-ocr-page-v10",
    }
)
PUBLIC_FINALS_PROFILES = ("finals-unattended-v1", "finals-unattended-v2")
FINALS_PROFILES = (
    *PUBLIC_FINALS_PROFILES,
    "finals-unattended-j3-v1",
    "finals-unattended-j7-v1",
    "finals-unattended-j8-v1",
)


def default_analysis_profile():
    # HS3 temporary choice. Coordinator finalizes it after QI2.
    return os.environ.get("HOSTED_ANALYSIS_PROFILE", "finals-unattended-v2")


def operator_profiles(config: dict) -> dict:
    from proofops.application.analysis_profile import publication_policy_for
    from proofops.application.claim_scope import MAX_EXTRACTION_BATCH_CALLS

    analysis = config.get("analysis_profile", default_analysis_profile())
    policy = (
        publication_policy_for(analysis, pinned_hash=config.get("analysis_policy_sha256"))
        if analysis in FINALS_PROFILES
        else {}
    )
    workers = config.get(
        "llm_max_workers",
        policy.get("provider_scheduler", {}).get(
            "default_workers", policy["max_http_workers"] if policy.get("tagging_budget") else 8
        ),
    )
    # Pre-scheduler F1/T1 pins retain their original accept-then-clamp behavior.
    max_workers = policy["max_http_workers"] if policy.get("provider_scheduler") else 16
    if type(workers) is not int or not 1 <= workers <= max_workers:
        raise ValueError("HOSTED_LLM_CONCURRENCY_INVALID")
    if policy.get("openai_retry_policy") == T1_RETRY_POLICY:
        workers = min(workers, policy["max_http_workers"])
    rps = config.get("llm_requests_per_second", 4)
    if type(rps) is not int or not 1 <= rps <= policy.get("provider_scheduler", {}).get(
        "max_rps", 8
    ):
        raise ValueError("HOSTED_LLM_RPS_INVALID")
    if "llm_requests_per_second" in config and not policy.get("provider_scheduler"):
        raise ValueError("PROVIDER_SCHEDULER_POLICY_REQUIRED")
    batch_calls = config.get("extract_batch_calls", policy.get("extract_batch_calls", 20))
    if type(batch_calls) is not int or not 1 <= batch_calls <= MAX_EXTRACTION_BATCH_CALLS:
        raise ValueError("HOSTED_EXTRACT_BATCH_INVALID")
    analysis = config.get("analysis_profile", default_analysis_profile())
    if analysis not in (
        "r108-default",
        "r108-finals-candidate",
        "r108-finals-candidate-v2",
        *FINALS_PROFILES,
    ):
        raise ValueError("HOSTED_ANALYSIS_PROFILE_INVALID")
    llm_provider = config.get("llm_provider", "openai")
    if llm_provider not in ("openai", "openrouter"):
        raise ValueError("HOSTED_LLM_PROVIDER_INVALID")
    if analysis in FINALS_PROFILES:
        llm_provider = "openai"
    if config.get("analysis_policy_sha256") is not None:
        from proofops.application.analysis_profile import publication_policy_for

        publication_policy_for(analysis, pinned_hash=config["analysis_policy_sha256"])
    requested = config.get("rendered_reader_profile")
    if requested is not None and requested not in KNOWN_RENDERED_READERS:
        raise ValueError("HOSTED_RENDERED_READER_PROFILE_INVALID")
    reader = (
        "apple-vision"
        if sys.platform == "darwin"
        else RENDERED_READER_POLICY.get(
            "default_linux_reader_v2", RENDERED_READER_POLICY["default_linux_reader"]
        )
        if analysis
        in (
            "finals-unattended-v2",
            "finals-unattended-j3-v1",
            "finals-unattended-j7-v1",
            "finals-unattended-j8-v1",
        )
        else RENDERED_READER_POLICY["default_linux_reader"]
    )
    if requested is not None or reader != "apple-vision":
        reader = requested or reader
        reader = reader if reader in GATE_PASSED_RENDERED_READERS else "unresolved"
    approval = RENDERED_READER_POLICY["gate_passed"].get(reader, {})
    return PROFILES | dict(
        llm_max_workers=workers,
        llm_requests_per_second=rps,
        extract_batch_calls=batch_calls,
        llm_provider=llm_provider,
        llm_provider_options=["openai", "openrouter"],
        analysis_profile=analysis,
        analysis_profile_options=[
            "r108-default",
            "r108-finals-candidate-v2",
            *PUBLIC_FINALS_PROFILES,
        ],
        analysis_profile_warning=(
            "E2E5 회귀 확인 — r108-finals-candidate-v2 또는 r108-default 사용 권장"
            if analysis == "r108-finals-candidate"
            else "v2 기본값은 잠정 설정이며 QI2 이후 확정합니다."
            if analysis in FINALS_PROFILES
            else None
        ),
        rendered_reader_requested=requested,
        source_reader=reader,
        claim_source=reader if reader in GATE_PASSED_RENDERED_READERS else "glyph-alignment-v1",
        rendered_reader_policy_sha256=canonical_hash(RENDERED_READER_POLICY),
        rendered_reader_gate_report_sha256=approval.get("report_sha256"),
    )


def runtime_profiles(settings):
    config = {} if settings.live_disabled else read_operator_config(settings.live_config)
    return operator_profiles(config)


def read_operator_config(path: Path | None) -> dict:
    if path is None or not path.is_absolute() or not path.is_file():
        raise ValueError("HOSTED_LIVE_CONFIG_REQUIRED")
    config = json.loads(path.read_text())
    if config.get("enabled") is not True:
        raise ValueError("HOSTED_OPERATOR_OPT_IN_REQUIRED")
    profiles = operator_profiles(config)
    provider = profiles["llm_provider"]
    config["llm_provider"] = provider
    key_name = "openai_key_file" if provider == "openai" else "openrouter_key_file"
    from proofops.application.analysis_profile import policy_for

    selected = (
        policy_for(profiles["analysis_profile"], pinned_hash=config.get("analysis_policy_sha256"))
        if profiles["analysis_profile"] in FINALS_PROFILES
        else {}
    )
    keys = [key_name, "upstage_key_file"]
    if selected.get("ops2_provider_fallback"):
        keys.append("openrouter_key_file")
    for name in keys:
        key_path = Path(config.get(name, ""))
        if not key_path.is_absolute() or not key_path.is_file():
            raise ValueError("HOSTED_KEY_FILE_REQUIRED")
    if type(config["report_year"]) is not int or not 1900 <= config["report_year"] <= 2100:
        raise ValueError("HOSTED_REPORTING_SCOPE_REQUIRED")
    if date.fromisoformat(config["period_start"]) > date.fromisoformat(config["period_end"]):
        raise ValueError("HOSTED_REPORTING_SCOPE_INVALID")
    return config


def read_key(path: str, name: str) -> str:
    for line in Path(path).read_text().splitlines():
        if line.startswith(name + "="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if key and not any(c.isspace() for c in key):
                return key
    raise ValueError("HOSTED_KEY_FILE_INVALID")


def rounded_cost(value) -> str:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("PROVIDER_COST_INVALID")
    return str(amount.quantize(Decimal("0.000001"), rounding=ROUND_CEILING))


def broker_dispatch(store, *args, **kwargs):
    from proofops.application.budget import BudgetExceeded

    from proofops_api.hosted_store import HostedError

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
        from proofops_api.hosted_store import HostedError

        now = time.time()
        with self.store.transaction() as db:
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
        from proofops.adapters.local.openai_connections import OpenAIConnectNotSent
        from proofops.adapters.local.provider_concurrency import ProviderCircuitOpen
        from proofops.adapters.local.provider_scheduler import ProviderAdmissionDeferred
        from proofops.application.i27_inventory import POLICY as I27_POLICY

        inventory = current.get()
        scope = self._dispatch_context.get()
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
                    )
                if self.transport_policy:
                    self._finish_transport_attempt(call_id, "response_received", None)
                if inventory is not None:
                    inventory["terminal_code"] = None
                return response["payload"]
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


# Wall-clock cap for one analysis subprocess; the per-run USD cap still bounds spend.
ANALYSIS_TIMEOUT_SECONDS = int(os.environ.get("HOSTED_ANALYSIS_TIMEOUT_SECONDS", "2700"))
HEARTBEAT_SECONDS = 30
TWO_SLOT_MEMORY_BYTES = 1100 * 1024 * 1024


def process_tree_bytes(pid):
    """RSS of the isolated analysis and its parser/OCR descendants."""
    output = subprocess.check_output(["ps", "-eo", "pid=,ppid=,rss="], text=True, timeout=5)
    rows = [tuple(map(int, line.split())) for line in output.splitlines()]
    descendants = {pid}
    while True:
        expanded = descendants | {child for child, parent, _ in rows if parent in descendants}
        if expanded == descendants:
            return sum(rss * 1024 for child, _, rss in rows if child in descendants)
        descendants = expanded


def acquire_analysis_lock(lock, *, timeout=2):
    from proofops_api.hosted_store import HostedError

    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise HostedError("ANALYSIS_LOCK_BUSY") from None
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def run_analysis_process(command, store, job, lock, *, publication_fd=None):
    from proofops_api.hosted_store import HostedError

    deadline = time.monotonic() + ANALYSIS_TIMEOUT_SECONDS
    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
    bounded = store.settings.max_active_runs == 2
    if publication_fd is not None:
        command = [*command, str(publication_fd)]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        pass_fds=(lock.fileno(),) + ((publication_fd,) if publication_fd is not None else ()),
        start_new_session=True,
        env=os.environ | {"PROOFOPS_RB3_HARD_DEADLINE": str(deadline)},
    )
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, ANALYSIS_TIMEOUT_SECONDS)
            try:
                code = process.wait(
                    timeout=min(
                        2 if bounded else HEARTBEAT_SECONDS,
                        remaining,
                        max(0.05, next_heartbeat - time.monotonic()),
                    )
                )
                if code:
                    raise subprocess.CalledProcessError(code, command)
                return
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise
                if bounded and process_tree_bytes(process.pid) > TWO_SLOT_MEMORY_BYTES:
                    raise HostedError("ANALYSIS_MEMORY_LIMIT") from None
                if time.monotonic() >= next_heartbeat:
                    from proofops_api.hosted_sqlite import is_busy

                    try:
                        store.renew_lease(job, now=time.time())
                    except Exception as exc:
                        if not is_busy(exc):
                            raise
                        if time.time() >= job["lease_until"]:
                            raise HostedError("LEASE_LOST") from None
                        # The existing fence is still valid: keep this child,
                        # never launch a replacement or repeat a provider call.
                        next_heartbeat = time.monotonic() + 1
                    else:
                        next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
    finally:
        # Reap the entire private session, including a parser/OCR child after an
        # interrupted parent. Its inherited document lock must not outlive the slot.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def execute_analysis(store, job, prepared):
    config = read_operator_config(store.settings.live_config)
    profiles = operator_profiles(config)
    with store.transaction() as db:
        store._fenced(db, job, time.time())
        directory = store.document_dir(job["tenant_id"], job["document_id"])
        lock = (directory / "analysis.lock").open("a+b")
        os.fchmod(lock.fileno(), 0o600)
    try:
        acquire_analysis_lock(lock)
        store.renew_lease(job, now=time.time())
        with TemporaryDirectory(prefix="analysis-work-", dir=directory) as scratch:
            workspace = Path(scratch)
            os.chmod(workspace, 0o700)
            (workspace / "selected.pdf").write_bytes(prepared.read_bytes())
            if profiles["source_reader"] == "unresolved":
                state = workspace / "state"
                state.mkdir(mode=0o700)
                (state / "outcome.json").write_text(
                    json.dumps(
                        dict(
                            status="partial_blocked",
                            reason="LINUX_SOURCE_READER_UNRESOLVED",
                            profiles=profiles,
                            stages=[],
                            provider_calls=0,
                        )
                    )
                )
                store.publish_analysis(
                    job, state, "partial_blocked", "LINUX_SOURCE_READER_UNRESOLVED"
                )
                return
            # Anonymous, parent-owned FD: no workspace file can impersonate a
            # child attestation. Keep analysis.lock through byte-pin comparison.
            from proofops_api.hosted_publication import MAX_BYTES

            with TemporaryFile() as publication:
                run_analysis_process(
                    [
                        sys.executable,
                        "-m",
                        "evaluation.hosted_r108",
                        job["run_id"],
                        str(job["fence"]),
                        str(workspace),
                    ],
                    store,
                    job,
                    lock,
                    publication_fd=publication.fileno(),
                )
                publication.seek(0)
                packet = publication.read(MAX_BYTES + 1)
            outcome = json.loads((workspace / "state" / "outcome.json").read_text())
            store.publish_analysis(
                job,
                workspace / "state",
                outcome["status"],
                outcome.get("reason"),
                publication_handoff=packet,
            )
    finally:
        lock.close()


PROFILES = dict(
    parser="upstage",
    llm=MODEL,
    relation="occurrence-v3",
    display="glyph-joined-display-v1",
    claim_source="glyph-alignment-v1",
    source_reader="apple-vision" if sys.platform == "darwin" else "unresolved",
)
