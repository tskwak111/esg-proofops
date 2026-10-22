"""Caller-authorized local Upstage tagging transport; never approves sources or grades.

The probe owns the only monetary reservation. This adapter is not implicitly
installed in LocalTagRunner (which still requires its synthetic runtime contract).
Receipts are immutable; a failed/unknown transport durably stops this operation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from threading import Lock
from time import monotonic_ns

from proofops.adapters.local.openrouter import OpenRouterProbe
from proofops.adapters.local.upstage import UPSTAGE_TRANSPORT_STOP_CODES, UpstageProbe
from proofops.application.budget import TokenUsage
from proofops.application.preflight import Preflight, PreflightBlocked
from proofops.application.tagging.service import RawTagResponse, TaggingSettings
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json
from proofops.domain.values import _require_sha256, _require_uuid

from proofops_agent.tagging_parts.wire import (
    CONSISTENCY_PROFILE as CONSISTENCY_PROFILE,
)
from proofops_agent.tagging_parts.wire import (
    COVERAGE_PROFILE as COVERAGE_PROFILE,
)
from proofops_agent.tagging_parts.wire import (
    MODEL_PROFILE as MODEL_PROFILE,
)
from proofops_agent.tagging_parts.wire import (
    QUOTE_PROFILE as QUOTE_PROFILE,
)
from proofops_agent.tagging_parts.wire import (
    QUOTE_V4_PROFILE as QUOTE_V4_PROFILE,
)
from proofops_agent.tagging_parts.wire import (
    QUOTE_V5_PROFILE as QUOTE_V5_PROFILE,
)
from proofops_agent.tagging_parts.wire import (
    build_wire_request,
    refine_g1_year,
    restore_payload,
    restore_ref,
)
from proofops_agent.upstage_extraction import UpstageClaimExtractor

# The only transport error codes that a locally suppressed, pre-dispatch outcome is
# allowed to carry. This is an explicit allow-list, never an inference from timing:
# a genuinely fast provider failure can round its latency to 0ms and can be missing
# a provider_request_id, so zero metadata alone proves nothing about billing.
#
# The decisive evidence is structural rather than numeric. Every short-circuit in
# `_invoke` returns *before* `directory.mkdir()`, and `invoke`'s lock contention
# returns before `_invoke` runs at all, so a suppressed request leaves no receipt
# directory whatsoever. A request that reached `self._probe.complete` always has
# one, because its `request.json` is written first. Absence of a receipt directory
# therefore proves the provider was never contacted; this allow-list only stops an
# unrelated settled failure from being read as a suppression.
NEVER_SENT_ERROR_CODES = frozenset({"UPSTREAM_UNAVAILABLE"})
SUPPRESSED_ERROR_CODE = "UPSTREAM_UNAVAILABLE"


class TransportResume:
    """Explicitly acknowledged, bounded re-arm of a stopped receipt root.

    A stop is never deleted, rewritten or bypassed. Arming requires that every
    durable failure the root already holds is acknowledged by its exact
    ``request_id``: an acknowledged outcome stays unresolved and is never
    retried, and its receipt, stop file and ledger row are left untouched. Only
    a bounded number of *new* ``request_id`` values is then authorized, counted
    across every root this authorization covers.

    The bound is **job-wide and durable, not per process**. The caller passes
    ``already_dispatched``, recomputed from the receipt tree and the ledger
    against the baseline pinned when the authorization was written, so a crashed
    or restarted recovery resumes with the remainder of its original allowance
    instead of being handed a fresh one. ``remaining`` therefore starts at
    ``max_new_requests - already_dispatched`` and a fully spent authorization
    cannot be constructed at all.

    The first new provider failure calls :meth:`disarm`, which withdraws the
    whole remaining allowance immediately, and the failure also leaves its own
    failed receipt and stop record behind. A later process that arms the same
    root therefore finds an unacknowledged durable failure and refuses again,
    so the stop survives process restarts without a blanket retry.
    """

    def __init__(
        self,
        *,
        acknowledged_failures,
        max_new_requests: int,
        already_dispatched: int = 0,
        expected_root: Path | None = None,
    ) -> None:
        if not isinstance(acknowledged_failures, frozenset):
            raise ValueError("TRANSPORT_RESUME_ACKNOWLEDGEMENT_REQUIRED")
        for identifier in sorted(acknowledged_failures):
            _require_uuid("acknowledged_failure", identifier)
        if type(max_new_requests) is not int or not 1 <= max_new_requests <= 200:
            raise ValueError("TRANSPORT_RESUME_BOUND_INVALID")
        if type(already_dispatched) is not int or already_dispatched < 0:
            raise ValueError("TRANSPORT_RESUME_HISTORY_INVALID")
        if already_dispatched >= max_new_requests:
            raise ValueError("TRANSPORT_RESUME_ALLOWANCE_ALREADY_SPENT")
        self.acknowledged_failures = acknowledged_failures
        self.max_new_requests = max_new_requests
        self.already_dispatched = already_dispatched
        self.remaining = max_new_requests - already_dispatched
        self.expected_root = None if expected_root is None else Path(expected_root)
        self.dispatched: set[str] = set()
        self._armed: dict[str, bool] = {}

    def _scan(self, receipts: Path) -> bool:
        """Is every durable failure already in this root explicitly acknowledged?

        An unreadable receipt, a receipt without a response and any settled
        non-succeeded response all count as unresolved, so a root is armed only
        when the operator named each of them. No file here is written or moved.
        """
        # ponytail: bounded local operation; index receipts if ensembles grow large.
        found: set[str] = set()
        try:
            children = sorted(receipts.iterdir())
        except OSError:
            return False
        for child in children:
            if child.is_dir():
                response = child / "response.json"
                if not response.is_file():
                    return False
                try:
                    usage = json.loads(response.read_text())["usage"]
                    status = usage["status"]
                except (OSError, ValueError, KeyError, TypeError):
                    return False
                if status != "succeeded":
                    found.add(child.name)
            elif child.name.startswith("transport-stop") and child.name.endswith(".json"):
                try:
                    found.add(json.loads(child.read_text())["request_id"])
                except (OSError, ValueError, KeyError, TypeError):
                    return False
        return found <= self.acknowledged_failures

    def armed(self, receipts: Path) -> bool:
        key = str(receipts)
        if key not in self._armed:
            self._armed[key] = self._scan(receipts)
        return self._armed[key]

    def allows(self, receipts: Path) -> bool:
        return self.remaining > 0 and self.armed(receipts)

    def consume(self, receipts: Path, request_id: str) -> None:
        _require_uuid("request_id", request_id)
        if request_id in self.dispatched:
            return
        if not self.allows(receipts):
            raise PreflightBlocked("TRANSPORT_RESUME_ALLOWANCE_EXHAUSTED")
        self.dispatched.add(request_id)
        self.remaining -= 1

    def disarm(self, receipts: Path) -> None:
        """Withdraw the whole allowance on the first new failure; never widen it."""
        self._armed[str(receipts)] = False
        self.remaining = 0


class UpstageTaggingTransport:
    synthetic = False
    MODEL_PROFILE = MODEL_PROFILE
    TRANSPORT_VERSION = "compact-evidence-ids-v1"

    def __init__(
        self,
        probe: UpstageProbe,
        receipts: Path,
        *,
        settings: TaggingSettings,
        tenant_id: str,
        authorize: Callable[[TaggingSettings, dict], Preflight],
        resume: TransportResume | None = None,
        display_catalog=None,
    ):
        _require_uuid("tenant_id", tenant_id)
        if (
            not isinstance(probe, UpstageProbe | OpenRouterProbe)
            or not isinstance(settings, TaggingSettings)
            or settings.binding.synthetic
            or settings.model_id != probe.model
            or (
                isinstance(probe, OpenRouterProbe)
                and settings.wire_policy_version != probe.wire_policy_version
            )
            or settings.model_profile
            not in (
                {
                    MODEL_PROFILE,
                    COVERAGE_PROFILE,
                    QUOTE_PROFILE,
                    QUOTE_V4_PROFILE,
                    QUOTE_V5_PROFILE,
                    CONSISTENCY_PROFILE,
                }
                if self.MODEL_PROFILE == MODEL_PROFILE
                else {self.MODEL_PROFILE}
            )
            or settings.region != "provider-managed-unverified"
        ):
            raise ValueError("UPSTAGE_TAGGING_BINDING_INVALID")
        if not callable(authorize):
            raise ValueError("UPSTAGE_TAGGING_AUTHORIZER_REQUIRED")
        if resume is not None and not isinstance(resume, TransportResume):
            raise ValueError("UPSTAGE_TAGGING_RESUME_INVALID")
        if settings.model_profile == COVERAGE_PROFILE:
            self.TRANSPORT_VERSION = "compact-coverage-v2"
        elif settings.model_profile == QUOTE_PROFILE:
            self.TRANSPORT_VERSION = "compact-source-quotes-v3"
        elif settings.model_profile == QUOTE_V4_PROFILE:
            self.TRANSPORT_VERSION = "compact-source-quotes-v4"
        elif settings.model_profile == QUOTE_V5_PROFILE:
            self.TRANSPORT_VERSION = "compact-source-quotes-v5"
        elif settings.model_profile == CONSISTENCY_PROFILE:
            self.TRANSPORT_VERSION = "compact-element-consistency-v6"
        self._display_catalog = display_catalog
        self._authorize = authorize
        self._probe, self._settings, self._tenant = probe, settings, tenant_id
        self._resume = resume
        self._receipts = Path(receipts)
        self._receipts.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._init_operation_state()

    def _init_operation_state(self):
        self._operation_mutex = Lock()
        self._operation_users = 0
        self._operation_file = None
        self._active_requests = set()

    def _stopped(self) -> bool:
        return (self._receipts / "transport-stop.json").exists() or any(
            self._receipts.glob("transport-stop.*.json")
        )

    def may_dispatch(self) -> bool:
        """Is one more *new* billable request inside the caller's explicit bound?

        Without a resume authorization this is always True, so ordinary
        operation, its stop behavior and its receipt replay are unchanged: the
        stop check inside :meth:`_invoke` remains the only gate. With one, a
        caller can ask before reserving budget, so an exhausted or withdrawn
        allowance costs no reservation and no settled ledger row.
        """
        return self._resume is None or self._resume.allows(self._receipts)

    def invoke(self, request: dict) -> RawTagResponse:
        # Offline workers can load on Windows; paid dispatch still requires this lock.
        import fcntl

        # One operation per receipt root; the shared USD ledger also fences all roots.
        with self._operation_mutex:
            if self._operation_users == 0:
                lock = (self._receipts / ".operation.lock").open("a")
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    lock.close()
                    return self._failed(SUPPRESSED_ERROR_CODE, 0)
                self._operation_file = lock
            self._operation_users += 1
        try:
            return self._invoke(request)
        finally:
            with self._operation_mutex:
                self._active_requests.discard(request["request_id"])
                self._operation_users -= 1
                if self._operation_users == 0:
                    self._operation_file.close()
                    self._operation_file = None

    def count_input_tokens(self, request: dict, *, counter: Callable[[str, str], int]) -> int:
        """Count exactly the sent messages, using a caller-pinned provider counter.

        The counter must include model chat framing; no character/byte estimate
        or tokenizer from another model is supplied here. No receipt or paid call.
        """
        system, user, _, _, _ = self._wire_request(request)
        self._probe.request_body(
            system,
            user,
            request_id=request["request_id"],
            max_tokens=request["max_tokens"],
            json_mode=True,
        )
        return counter(system, user)

    def _authorize_request(self, request: dict) -> Preflight:
        settings = self._settings
        authorization = self._authorize(settings, request)
        if (
            not isinstance(authorization, Preflight)
            or authorization.ready is not True
            or any(check.status == "fail" for check in authorization.checks)
            or not {
                "runtime_approval",
                "consent_approval",
                "model_binding",
                "document_scope",
                "document_rights",
                "data_consent",
                "tagging_settings",
                "selected_document_rights",
            }
            <= {check.name for check in authorization.checks if check.status == "pass"}
        ):
            raise PreflightBlocked("UPSTAGE_TAGGING_AUTHORIZATION_REQUIRED")
        for name in ("tenant_id", "claim_id", "request_id"):
            _require_uuid(name, request[name])
        for name in ("packet_sha256", "request_signature"):
            _require_sha256(name, request[name])
        if (
            request["tenant_id"] != self._tenant
            or request["binding"] != asdict(settings.binding)
            or request["model_id"] != settings.model_id
            or request["model_profile"] != settings.model_profile
            or request["region"] != settings.region
            or request["temperature"] != 0
            or type(request["replicate_id"]) is not int
            or request["replicate_id"] not in (1, 2, 3)
            or type(request["max_tokens"]) is not int
            or not 1 <= request["max_tokens"] <= settings.max_tokens
        ):
            raise ValueError("UPSTAGE_TAGGING_REQUEST_INVALID")
        return authorization

    def _wire_request(self, request: dict) -> tuple[str, str, dict[str, dict], Preflight, str]:
        settings = self._settings
        authorization = self._authorize_request(request)
        system, user, refs, schema = build_wire_request(
            request,
            settings,
            display_catalog=getattr(self, "_display_catalog", None),
            request_body=lambda *args, **kwargs: self._probe.request_body(*args, **kwargs),
        )
        return system, user, refs, authorization, schema

    def _restore_ref(self, selection, refs: dict[str, dict], *, policy=None) -> dict:
        return restore_ref(
            selection,
            refs,
            model_profile=self._settings.model_profile,
            display_catalog=getattr(self, "_display_catalog", None),
            policy=policy,
        )

    def restore_payload(self, payload, refs, *, policy=None):
        return restore_payload(
            payload,
            refs,
            model_profile=self._settings.model_profile,
            display_catalog=getattr(self, "_display_catalog", None),
            restore_ref=self._restore_ref,
            refine_year=self._refine_g1_year,
            policy=policy,
        )

    @staticmethod
    def _refine_g1_year(element: dict) -> None:
        refine_g1_year(element)

    def _invoke(self, request: dict) -> RawTagResponse:
        settings = self._settings
        system = request["system_prompt"]
        wire_system, wire_user, refs, authorization, wire_schema = self._wire_request(request)
        stop = self._receipts / "transport-stop.json"
        # ponytail: bounded local operation; index receipts if ensembles grow large.
        with self._operation_mutex:
            incomplete = any(
                child.is_dir()
                and child.name not in self._active_requests
                and not (child / "response.json").exists()
                for child in self._receipts.iterdir()
            )
            # A stopped root stays stopped unless an explicit acknowledged authorization
            # re-arms it for a bounded number of new requests; the stop itself is never
            # read as permission and never removed.
            permitted = (
                not self._stopped() if self._resume is None else self._resume.allows(self._receipts)
            )
            if incomplete or not permitted:
                return self._failed(SUPPRESSED_ERROR_CODE, 0)
            if self._resume is not None:
                self._resume.consume(self._receipts, request["request_id"])
            directory = self._receipts / request["request_id"]
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError:
                raise ValueError("TAGGING_RECEIPT_EXISTS") from None
            self._active_requests.add(request["request_id"])
        write = UpstageClaimExtractor._write
        write(
            directory / "request.json",
            canonical_json(
                dict(
                    request=request,
                    request_sha256=canonical_hash(request),
                    model_sha256=settings.model_sha256,
                    prompt_sha256=canonical_hash(system),
                    wire_system=wire_system,
                    wire_user_json=wire_user,
                    wire_prompt_sha256=canonical_hash(wire_system),
                    transport_version=self.TRANSPORT_VERSION,
                    evidence_refs=refs,
                    authorization=authorization.to_dict(),
                )
            ),
        )
        started = monotonic_ns()
        try:
            receipt = self._probe.complete(
                wire_system,
                wire_user,
                request_id=request["request_id"],
                max_tokens=request["max_tokens"],
                json_mode=True,
                **(
                    {"schema_json": wire_schema} if isinstance(self._probe, OpenRouterProbe) else {}
                ),
            )
        except Exception as error:
            code = str(error)
            from proofops.application.provider_resilience import ISOLATED_CODES

            # The probe normalizes unrecognized request failures only after its
            # typed guards. Under request-only resilience this is a failed vote,
            # not permission to stop the shared receipt root for other claims.
            if (
                getattr(self._probe, "provider_resilience", None)
                and code == "OPENAI_REQUEST_FAILED"
            ):
                code = "PROVIDER_PROCESSING_FAILED"
            isolated = bool(
                getattr(self._probe, "provider_resilience", None) and code in ISOLATED_CODES
            )
            if code in {"R108_FINALS_BUDGET_EXHAUSTED", "R108_FINALS_CUMULATIVE_BUDGET_EXHAUSTED"}:
                code = "BUDGET_EXHAUSTED"
            elif not isolated and code not in UPSTAGE_TRANSPORT_STOP_CODES | {
                "PROCESSING_UNCERTAIN"
            }:
                code = "UPSTREAM_UNAVAILABLE"
            # Only hosted broker transport uncertainty is isolated to this request.
            # Its failed receipt and pending money remain immutable; mkdir/ledger
            # guards still forbid repeating it. Other failures stop the root as before.
            if not isolated and code != "PROCESSING_UNCERTAIN":
                # Exclusive creation prevents overwriting an earlier failure receipt.
                if not stop.exists():
                    write(stop, canonical_json(dict(code=code, request_id=request["request_id"])))
                else:
                    # An acknowledged stop is immutable, so this new failure is
                    # recorded beside it: the next process to arm this root finds an
                    # unacknowledged durable failure and refuses again.
                    chained = self._receipts / f"transport-stop.{request['request_id']}.json"
                    if not chained.exists():
                        write(
                            chained,
                            canonical_json(dict(code=code, request_id=request["request_id"])),
                        )
                if self._resume is not None:
                    self._resume.disarm(self._receipts)
            response = self._failed(code, (monotonic_ns() - started) // 1_000_000)
        else:
            try:
                if receipt.get("schema_valid") is False:
                    raise ValueError("provider schema invalid")
                payload = json.loads(receipt["content"])
                response_policy = json.loads(request["user_json"])["untrusted_document_data"].get(
                    "tagging_response_policy"
                )
                preliminary_policy = json.loads(request["user_json"]).get(
                    "preliminary_response_policy"
                )
                if response_policy is not None or preliminary_policy is not None:
                    from jsonschema import Draft202012Validator

                    if not Draft202012Validator(json.loads(wire_schema)).is_valid(payload):
                        raise ValueError("K4_RAW_RESPONSE_SCHEMA_INVALID")
                if response_policy is not None:
                    from proofops.application.tagging.k4_contract import bind_response

                    payload = bind_response(payload, request, policy=response_policy)
                if preliminary_policy is not None:
                    from proofops.application.tagging.k4_contract import bind_response

                    payload = bind_response(payload, request, policy=preliminary_policy)
                    payload.pop("packet_sha256")
                    payload.pop("replicate_id")
                restore_policy = json.loads(request["user_json"])["untrusted_document_data"].get(
                    "citation_restore_policy"
                )
                payload = self.restore_payload(payload, refs, policy=restore_policy)
                expanded = canonical_json(payload)
            except (ValueError, KeyError, TypeError, AttributeError):
                expanded = None
                receipt = {**receipt, "validation_error": "TAGGING_EVIDENCE_ID_INVALID"}
            response = RawTagResponse(
                expanded,
                TokenUsage(
                    receipt["input_tokens"],
                    receipt["output_tokens"],
                    0,
                    0,
                    (monotonic_ns() - started) // 1_000_000,
                    "succeeded",
                    receipt["provider_request_id"],
                ),
                False,
                canonical_json(receipt),
            )
        if request.get("cf6_confirmation") is not None:
            from proofops.adapters.local.cf6_transport import authenticate

            try:
                response = authenticate(
                    request,
                    response,
                    self._probe,
                    settings=settings,
                    wire_system=wire_system,
                    wire_user=wire_user,
                    wire_schema=wire_schema,
                )
            except (ValueError, KeyError, TypeError, OSError):
                # Preserve successful usage/raw evidence; lack of authenticated
                # freshness blocks only CF6 publication, not the paid receipt.
                provider = json.loads(response.provider_response_json or "{}")
                provider.pop("cf6_transport_receipt", None)
                provider["cf6_transport_rejection"] = "CURRENT_ORIGIN_NOT_AUTHENTICATED"
                response = replace(response, provider_response_json=canonical_json(provider))
        response = self._response_metadata(response)
        write(directory / "response.json", canonical_json(asdict(response)))
        return response

    def _response_metadata(self, response):
        return response

    @staticmethod
    def _failed(code: str, latency: int) -> RawTagResponse:
        return RawTagResponse(
            None,
            TokenUsage(None, None, None, None, latency, "failed", None, code),
            False,
            canonical_json(dict(error_code=code)),
        )
