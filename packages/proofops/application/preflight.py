"""TASK-029: evaluate trusted, tenant-scoped approval snapshots without I/O.

Inputs are server-resolved ApprovedProfile artifacts, never request-body
assertions of approval. Account permission/routing/schema/image evidence must
be captured by the approved deployment process; this function does not claim
to discover AWS capabilities. Each dispatch evaluates its frozen run snapshots.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from proofops.application.authorization import AuthContext, TenantNotFoundError
from proofops.application.supply_chain import SupplyChainResult
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    reason: str


@dataclass(frozen=True)
class Preflight:
    ready: bool
    checks: tuple[Check, ...]
    binding_sha256: str | None
    checked_at: str

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "checks": [asdict(check) for check in self.checks]}


class PreflightBlocked(ValueError):
    """A sanitized failure at the external-transmission boundary."""


class ModelInvocationPort(Protocol):
    def invoke(
        self,
        *,
        body: bytes,
        auth: AuthContext,
        binding: Mapping[str, Any],
        consent: Mapping[str, Any],
        allowed_regions: Sequence[str],
        document_rights: str,
        checked_at: str,
    ) -> dict[str, Any]: ...


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _uuid(value: Any) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value.lower()
    except ValueError:
        return False


def _model_target(value: Any, region: Any, account: Any, *, profile_only: bool = False) -> bool:
    if not _text(value) or not _text(region) or not _text(account):
        return False
    if not value.startswith("arn:"):
        return not profile_only and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,2047}", value))
    # P0 supports foundation models and explicit inference profiles only.
    # Other Bedrock resource kinds fail closed until their routing is reviewed.
    match = re.fullmatch(
        r"arn:aws:bedrock:([a-z0-9-]+):([0-9]{12}|):"
        r"(foundation-model|inference-profile|application-inference-profile)/"
        r"([A-Za-z0-9][A-Za-z0-9._:-]*)",
        value,
    )
    if match is None or match[1] != region:
        return False
    if match[3] == "foundation-model":
        return not profile_only and match[2] == ""
    return match[2] == account


def _timestamp(value: Any) -> datetime | None:
    if not _text(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _regions(value: Any) -> set[str]:
    if not isinstance(value, list | tuple) or not value:
        return set()
    if any(
        not isinstance(r, str) or not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", r) for r in value
    ):
        return set()
    return set(value)


def check_runtime_binding(
    *,
    binding: Mapping[str, Any],
    consent: Mapping[str, Any],
    auth: AuthContext,
    allowed_regions: Sequence[str],
    checked_at: str,
    include_live_model_probe: bool = False,
) -> Preflight:
    """Check an approved model role against consent and server region policy.

    `ready` means supplied approval evidence passes, not a new live AWS test.
    A requested new live probe remains not_run/blocked in this offline checker.
    Alternative bindings must start a new ensemble run and pass this gate;
    nested fallback configuration is rejected rather than silently followed.
    """
    for profile in (binding, consent):
        if not auth.tenant_id or profile.get("tenant_id") != auth.tenant_id:
            raise TenantNotFoundError("profile not found")
    now = _timestamp(checked_at)
    if now is None:
        raise ValueError("checked_at must be a timezone-aware timestamp")
    if type(include_live_model_probe) is not bool:
        raise ValueError("include_live_model_probe must be a bool")
    # Detach mutable config before inspecting nested values and hashing it.
    runtime = json.loads(canonical_json(dict(binding)))
    profile = json.loads(canonical_json(dict(consent)))
    checks: list[Check] = []

    def add(name: str, passed: bool, reason: str) -> None:
        checks.append(
            Check(name, "pass" if passed else "fail", "verified snapshot" if passed else reason)
        )

    for name, data, id_field in (
        ("runtime_approval", runtime, "runtime_binding_id"),
        ("consent_approval", profile, "consent_profile_id"),
    ):
        approved_at = _timestamp(data.get("approved_at"))
        add(
            name,
            data.get("status") == "approved"
            and _uuid(data.get(id_field))
            and all(_text(data.get(key)) for key in ("version", "approved_by"))
            and approved_at is not None
            and approved_at <= now,
            "approved version, reviewer and timestamp required",
        )
    verified_at = _timestamp(runtime.get("checked_at"))
    add(
        "account_permission",
        _text(runtime.get("account_id"))
        and bool(re.fullmatch(r"[0-9]{12}", runtime["account_id"]))
        and runtime.get("permissions_verified") is True
        and verified_at is not None
        and verified_at <= now,
        "account access verification missing or invalid",
    )
    model_id = runtime.get("model_id")
    inference_profile = runtime.get("inference_profile_arn")
    region = runtime.get("endpoint_region")
    add(
        "model_binding",
        _model_target(model_id, region, runtime.get("account_id"))
        and runtime.get("role") in ("extractor", "tagger", "vision", "writer")
        and (
            inference_profile is None
            or _model_target(
                inference_profile, region, runtime.get("account_id"), profile_only=True
            )
        ),
        "model ID, role or inference profile is missing/invalid",
    )
    destinations = _regions(runtime.get("allowed_processing_regions"))
    deployment_regions = _regions(list(allowed_regions))
    consent_regions = _regions(profile.get("allowed_processing_regions"))
    add(
        "processing_regions",
        bool(destinations and deployment_regions and consent_regions)
        and runtime.get("processing_regions_verified") is True
        and _text(region)
        and region in destinations
        and destinations <= deployment_regions & consent_regions,
        "REGION_DENIED: all endpoint and processing destinations must be verified and allowed",
    )
    add(
        "fallback",
        runtime.get("fallback_bindings", []) == [],
        "fallback requires a separate approved binding and new ensemble run",
    )
    add(
        "structured_output",
        _text(runtime.get("structured_output_strategy"))
        and runtime.get("structured_output_verified") is True,
        "structured output capability verification missing",
    )
    image_required = runtime.get("role") == "vision"
    add(
        "image_input",
        type(runtime.get("accepts_images")) is bool
        and (
            not image_required
            or runtime.get("accepts_images") is True
            and runtime.get("image_input_verified") is True
        ),
        "image input capability verification missing",
    )
    context, output = runtime.get("max_context_tokens"), runtime.get("max_output_tokens")
    add(
        "token_limits",
        type(context) is int and type(output) is int and 0 < output <= context,
        "positive model token limits required; output exceeds context",
    )
    rights = profile.get("allowed_document_rights")
    add(
        "document_rights",
        isinstance(rights, list)
        and bool(rights)
        and all(_text(right) and right != "*" for right in rights),
        "approved document rights required",
    )
    add(
        "data_consent",
        profile.get("provider_terms_approved") is True
        and profile.get("allow_cross_tenant_cache", False) is False
        and profile.get("allow_agentcore_memory", False) is False,
        "provider terms approval required; cross-tenant cache and Memory remain disabled",
    )
    checks.append(
        Check(
            "live_model_probe",
            "not_run",
            (
                "live probe requested but no approved live execution is wired"
                if include_live_model_probe
                else "offline snapshot verification; no model call performed"
            ),
        )
    )
    return Preflight(
        ready=all(c.status != "fail" for c in checks) and not include_live_model_probe,
        checks=tuple(checks),
        binding_sha256=hashlib.sha256(canonical_json(runtime).encode("ascii")).hexdigest(),
        checked_at=checked_at,
    )


def combine_build_checks(result: Preflight, build: SupplyChainResult | None) -> Preflight:
    """Compose TASK-042 build evidence; never run build tooling in an API image.

    Composition supplies a build-time verifier result for its immutable image.
    Missing attestation is not_run and cannot imply deployment readiness.
    Error details may contain internal paths, so expose a stable summary only.
    """
    check = Check(
        "supply_chain",
        "not_run" if build is None else "pass" if build.passed else "fail",
        "build/license verification unavailable"
        if build is None
        else "build/license checks passed"
        if build.passed
        else "build/license checks blocked; inspect deployment evidence",
    )
    return Preflight(
        result.ready and build is not None and build.passed,
        result.checks + (check,),
        result.binding_sha256,
        result.checked_at,
    )


def check_local_upstage_binding(
    *,
    binding: Mapping[str, Any],
    consent: Mapping[str, Any],
    auth: AuthContext,
    checked_at: str,
    source_sha256: str | None = None,
    include_live_model_probe: bool = False,
    model_sha256: str | None = None,
) -> Preflight:
    """Explicit local test consent, never production routing/rights attestation.

    Only the local composition may call this path. No AWS account is invented;
    provider-managed processing geography remains unverified.

    Only solar-pro3/solar-pro4 model IDs are authorized. When ``model_sha256``
    is supplied it must exactly equal
    ``canonical_hash({model: model_id, provider: upstage, transport: UpstageProbe})``.
    Omission preserves the legacy model3-only call shape; run creation and the
    per-call worker must still supply the frozen profile hash so an invalid or
    missing profile can never become an omitted bypass.
    """
    if any(p.get("tenant_id") != auth.tenant_id for p in (binding, consent)):
        raise TenantNotFoundError("profile not found")
    now = _timestamp(checked_at)
    if now is None or type(include_live_model_probe) is not bool:
        raise ValueError("invalid preflight input")
    if model_sha256 is not None and (
        type(model_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", model_sha256)
    ):
        raise ValueError("invalid model_sha256")
    checks = []

    def add(name, passed):
        checks.append(
            Check(
                name,
                "pass" if passed else "fail",
                "local test authorization" if passed else "local test authorization invalid",
            )
        )

    for name, profile, id_field in (
        ("runtime_approval", binding, "runtime_binding_id"),
        ("consent_approval", consent, "consent_profile_id"),
    ):
        approved = _timestamp(profile.get("approved_at"))
        expires = _timestamp(profile.get("expires_at"))
        add(
            name,
            profile.get("status") == "approved"
            and _uuid(profile.get(id_field))
            and all(_text(profile.get(k)) for k in ("version", "approved_by"))
            and approved is not None
            and expires is not None
            and approved <= now < expires
            and profile.get("purpose") == "local_test"
            and profile.get("provider") == "upstage",
        )
    model_id = binding.get("model_id")
    model_hash_ok = model_id == "solar-pro3"
    if model_sha256 is not None:
        expected = (
            canonical_hash({"model": model_id, "provider": "upstage", "transport": "UpstageProbe"})
            if model_id in ("solar-pro3", "solar-pro4")
            else None
        )
        model_hash_ok = expected is not None and model_sha256 == expected
    add(
        "model_binding",
        binding.get("role") == "extractor"
        and binding.get("model_id") in ("solar-pro3", "solar-pro4")
        and model_hash_ok
        and binding.get("endpoint") == "https://api.upstage.ai/v1/chat/completions"
        and binding.get("budget_limit_usd") in ("10.00", "20.00")
        and binding.get("fallback_bindings", []) == [],
    )
    hashes = consent.get("allowed_source_sha256")
    add(
        "document_scope",
        isinstance(hashes, list | tuple)
        and bool(hashes)
        and all(isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes)
        and (source_sha256 is None or source_sha256 in hashes),
    )
    rights = consent.get("allowed_document_rights")
    add(
        "document_rights",
        isinstance(rights, list | tuple)
        and bool(rights)
        and all(_text(r) and r != "*" for r in rights),
    )
    add(
        "data_consent",
        consent.get("allow_cross_tenant_cache") is False
        and consent.get("allow_agentcore_memory") is False,
    )
    checks.extend(
        (
            Check(
                "processing_regions",
                "not_run",
                "provider-managed; local test only, deployment blocked",
            ),
            Check("live_model_probe", "not_run", "no model call during preflight"),
        )
    )
    return Preflight(
        all(c.status != "fail" for c in checks) and not include_live_model_probe,
        tuple(checks),
        hashlib.sha256(canonical_json(dict(binding)).encode("ascii")).hexdigest(),
        checked_at,
    )
