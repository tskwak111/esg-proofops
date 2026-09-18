"""Rule-pack validation and activation (TASK-025, FR-025).

Pure application logic: stdlib + proofops.domain only. No AWS SDK, no network,
no file access, no environment variables, no scripts/legacy imports. File I/O
lives in scripts/verify_rulepack.py; this module takes already-parsed dicts.

Contract: validate_rulepack / activate_rulepack ::
YAML + source metadata + gap registry -> validated pack / status.

Content validation, administrative activation, and domain/basis approval are
separate steps (evidence/contract_review_resolution.md finding 3):
- `validate_rulepack` checks structure, manifest-bound hash, gap registry,
  and fail-closed gap gates. It never grants approval.
- `activate_rulepack` additionally requires status=validated plus a recorded
  human approver, and only moves the (tenant, mode) default for NEW runs.
- `grant_demo_use` permits local validated-draft explicit-ladder demos with
  fixed limits and no invented approval; it never touches activation state.

Rules enforced (fail-closed, refs docs/31):
- version / effective_date / mode / ontology / source hash / files present.
- Declared sha256 must equal the semantic content hash, which binds manifest
  identity (version, ontology, source hash, mode, effective date, file set,
  gaps) plus every file payload with deterministic no-NaN encoding.
- Manifest file set must equal the provided content set; duplicate and unsafe
  (absolute, dot-dot, backslash) paths rejected; malformed payloads rejected.
- Every referenced file must declare the pack's version and source identity.
- unresolved_gap_ids must all exist in the gap registry (GAP-xxx).
- GAP-008: a basis with a clause number claimed "verified" without
  verified_by/verified_at evidence is rejected; unverified stays unverified.
- GAP-001: safe-harbor grade/reasonable-basis mappings must be null until an
  approved mapping exists.
- GAP-009: automatic legal applicability must stay disabled.
- Registry identity is (tenant_id, rule_pack_id): identical replay is
  idempotent, a changed record under an existing ID is rejected.
- Tenant isolation: lookups across tenants raise LookupError("rule pack not
  found") without leaking the other tenant's data.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any
from uuid import UUID

from proofops.domain.rulepacks import pack_content_hash

MODES = ("disclosure", "advertising")
STATUSES = ("draft", "validated", "active", "retired")
DEMO_STATUSES = ("draft", "validated")

DEMO_LIMITS = (
    "explicit-ladder demo only",
    "per-claim gates retained",
    "unverified basis stays unverified",
    "no legal-effect or immunity claim",
    "local synthetic use only; never customer activation",
)

_REQUIRED_PACK_KEYS = (
    "rule_pack_id",
    "tenant_id",
    "version",
    "effective_date",
    "mode",
    "status",
    "ontology_version",
    "source_document_sha256",
    "files",
    "sha256",
    "unresolved_gap_ids",
)


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _is_safe_path(path: str) -> bool:
    if not path or path.startswith("/") or "\\" in path or ":" in path:
        return False
    return all(segment not in ("", ".", "..") for segment in path.split("/"))


def compute_pack_sha256(
    pack: Mapping[str, Any],
    files_content: Mapping[str, Any],
) -> str:
    """Semantic content hash: manifest identity bound to every file payload."""
    return pack_content_hash(pack, files_content)


def _iter_bases(node: Any) -> Any:
    """Yield every `basis` mapping found in a nested file document."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key == "basis" and isinstance(value, Mapping):
                yield value
            else:
                yield from _iter_bases(value)
    elif isinstance(node, list | tuple):
        for item in node:
            yield from _iter_bases(item)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...]
    computed_sha256: str


def validate_rulepack(
    pack: Mapping[str, Any],
    files_content: Mapping[str, Any],
    gap_ids: Collection[str],
) -> ValidationResult:
    """Validate a rule-pack dict against files content and the gap registry."""
    errors: list[str] = []
    known_gaps = set(gap_ids)

    for key in _REQUIRED_PACK_KEYS:
        if key not in pack:
            errors.append(f"missing required field: {key}")

    if "rule_pack_id" in pack and not _is_uuid(pack["rule_pack_id"]):
        errors.append("rule_pack_id must be a UUID string")
    if "tenant_id" in pack and not _is_uuid(pack["tenant_id"]):
        errors.append("tenant_id must be a UUID string")
    if "version" in pack and not (isinstance(pack["version"], str) and pack["version"]):
        errors.append("version must be a non-empty string")
    if "effective_date" in pack and _parse_date(pack["effective_date"]) is None:
        errors.append("effective_date must be a YYYY-MM-DD date string")
    if "mode" in pack and pack["mode"] not in MODES:
        errors.append(f"mode must be one of {sorted(MODES)}")
    if "status" in pack and pack["status"] not in STATUSES:
        errors.append(f"status must be one of {sorted(STATUSES)}")
    if "ontology_version" in pack and not (
        isinstance(pack["ontology_version"], str) and pack["ontology_version"]
    ):
        errors.append("ontology_version must be a non-empty string")
    if "source_document_sha256" in pack and not _is_sha256(pack["source_document_sha256"]):
        errors.append("source_document_sha256 must be a 64-char lowercase hex sha256")

    files = pack.get("files")
    listed: list[str] = []
    if files is not None:
        if not isinstance(files, list) or not files or any(not isinstance(f, str) for f in files):
            errors.append("files must be a non-empty list of path strings")
        else:
            listed = list(files)
            seen: set[str] = set()
            for path in listed:
                if not _is_safe_path(path):
                    errors.append(f"unsafe file path rejected: {path}")
                if path in seen:
                    errors.append(f"duplicate file entry rejected: {path}")
                seen.add(path)
            extra = sorted(set(files_content.keys()) - set(listed))
            if extra:
                errors.append(f"files beyond manifest rejected: {extra}")
            for path in listed:
                doc = files_content.get(path)
                if doc is None:
                    errors.append(f"missing referenced file: {path}")
                    continue
                if not isinstance(doc, Mapping):
                    errors.append(f"file is not a mapping: {path}")
                    continue
                if not doc.get("version") or not doc.get("effective_date"):
                    errors.append(f"file missing version/effective_date: {path}")
                elif _parse_date(doc.get("effective_date")) is None:
                    errors.append(f"file has bad effective_date: {path}")
                if (
                    "version" in doc
                    and "version" in pack
                    and doc.get("version") != pack.get("version")
                ):
                    errors.append(
                        f"file version mismatch: {path} declares {doc.get('version')!r}, "
                        f"pack declares {pack.get('version')!r}"
                    )
                if (
                    "source_document_sha256" in doc
                    and "source_document_sha256" in pack
                    and doc.get("source_document_sha256") != pack.get("source_document_sha256")
                ):
                    errors.append(f"file source identity mismatch: {path}")

    try:
        computed = compute_pack_sha256(pack, files_content)
    except (TypeError, ValueError) as exc:
        errors.append(f"malformed rule payload, hash uncomputable: {exc}")
        computed = "uncomputable"
    else:
        declared = pack.get("sha256")
        if not _is_sha256(declared):
            errors.append("sha256 must be a 64-char lowercase hex sha256")
        elif declared != computed:
            errors.append(
                "sha256 mismatch: declared does not match semantic content hash "
                "(refusing to validate a tampered pack)"
            )

    unresolved = pack.get("unresolved_gap_ids")
    if unresolved is not None:
        if not isinstance(unresolved, list) or any(not isinstance(g, str) for g in unresolved):
            errors.append("unresolved_gap_ids must be a list of gap id strings")
        else:
            for gap in unresolved:
                if gap not in known_gaps:
                    errors.append(f"unknown gap id: {gap}")

    # GAP-008: verified clause claims need verified_by/verified_at evidence.
    for path in files_content:
        doc = files_content[path]
        if not isinstance(doc, Mapping):
            continue
        if doc.get("verification_status") == "verified" and not (
            doc.get("verified_by") and doc.get("verified_at")
        ):
            errors.append(
                f"file claims verification without evidence: {path} "
                "(GAP-008: clause approval requires reviewer/URL/date record)"
            )
        for basis in _iter_bases(doc):
            clause = basis.get("clause")
            status = basis.get("verification_status")
            if (
                clause is not None
                and status == "verified"
                and not (basis.get("verified_by") and basis.get("verified_at"))
            ):
                errors.append(
                    f"basis verification rejected in {path}: clause={clause} claims "
                    "verification_status=verified without reviewer/URL/date evidence "
                    "(GAP-008: clause numbers must not be invented or marked verified)"
                )

    # GAP-001: no grade mapping without an approved mapping.
    safe_harbor = files_content.get("regulatory/safe_harbor.yaml")
    if isinstance(safe_harbor, Mapping):
        if safe_harbor.get("grade_mapping") is not None:
            errors.append("grade_mapping requires an approved mapping (GAP-001: mapping is null)")
        if safe_harbor.get("reasonable_basis_boolean_mapping") is not None:
            errors.append("reasonable_basis_boolean_mapping requires an approved mapping (GAP-001)")

    # GAP-009: no automatic legal applicability.
    timeline = files_content.get("regulatory/timeline.yaml")
    if isinstance(timeline, Mapping) and timeline.get("automatic_legal_applicability_enabled"):
        errors.append("automatic legal applicability is disabled (GAP-009)")

    return ValidationResult(ok=not errors, errors=tuple(errors), computed_sha256=computed)


@dataclass(frozen=True, slots=True)
class RulePackRecord:
    rule_pack_id: str
    tenant_id: str
    version: str
    effective_date: str
    mode: str
    status: str
    ontology_version: str
    source_document_sha256: str
    files: tuple[str, ...]
    sha256: str
    unresolved_gap_ids: tuple[str, ...]
    approved_by: str | None = None
    approved_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", tuple(self.files))
        object.__setattr__(self, "unresolved_gap_ids", tuple(self.unresolved_gap_ids))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RulePackRecord:
        return cls(
            rule_pack_id=str(data["rule_pack_id"]),
            tenant_id=str(data["tenant_id"]),
            version=str(data["version"]),
            effective_date=str(data["effective_date"]),
            mode=str(data["mode"]),
            status=str(data["status"]),
            ontology_version=str(data["ontology_version"]),
            source_document_sha256=str(data["source_document_sha256"]),
            files=tuple(data["files"]),
            sha256=str(data["sha256"]),
            unresolved_gap_ids=tuple(data.get("unresolved_gap_ids", [])),
            approved_by=data.get("approved_by"),
            approved_at=data.get("approved_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_pack_id": self.rule_pack_id,
            "tenant_id": self.tenant_id,
            "version": self.version,
            "effective_date": self.effective_date,
            "mode": self.mode,
            "status": self.status,
            "ontology_version": self.ontology_version,
            "source_document_sha256": self.source_document_sha256,
            "files": list(self.files),
            "sha256": self.sha256,
            "unresolved_gap_ids": list(self.unresolved_gap_ids),
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    """Minimal frozen run pointer: the rule snapshot a run started with."""

    run_id: str
    tenant_id: str
    rule_pack_id: str
    rule_pack_sha256: str
    status: str


@dataclass(frozen=True, slots=True)
class ActivationRecord:
    before_pack_id: str | None
    after_pack_id: str
    tenant_id: str
    mode: str
    actor: str
    reason: str


@dataclass(frozen=True, slots=True)
class DemoGrant:
    """Local validated-draft explicit-ladder demo permission.

    Carries no approval: `approved_by` stays None, fixed limits apply, and the
    grant never changes registry activation state.
    """

    rule_pack_id: str
    tenant_id: str
    sha256: str
    actor: str
    purpose: str
    limits: tuple[str, ...] = DEMO_LIMITS
    local_only: bool = True
    approved_by: str | None = None


@dataclass(frozen=True, slots=True)
class RulePackRegistry:
    """Immutable registry: packs, runs, and the per-(tenant, mode) default pointer.

    Pack identity is (tenant_id, rule_pack_id): identical replay returns the
    same registry, a changed record under an existing ID is rejected.
    """

    packs: tuple[RulePackRecord, ...] = ()
    runs: tuple[RunSnapshot, ...] = ()
    active: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "packs", tuple(self.packs))
        object.__setattr__(self, "runs", tuple(self.runs))
        object.__setattr__(self, "active", tuple(tuple(entry) for entry in self.active))

    @classmethod
    def empty(cls) -> RulePackRegistry:
        return cls()

    def with_pack(self, pack: RulePackRecord) -> RulePackRegistry:
        for existing in self.packs:
            if (existing.tenant_id, existing.rule_pack_id) == (
                pack.tenant_id,
                pack.rule_pack_id,
            ):
                if existing == pack:
                    return self
                raise ValueError(
                    f"conflicting rule pack id {pack.rule_pack_id} for tenant: "
                    "immutable IDs cannot be overwritten"
                )
        return RulePackRegistry(packs=self.packs + (pack,), runs=self.runs, active=self.active)

    def with_run(self, run: RunSnapshot) -> RulePackRegistry:
        return RulePackRegistry(packs=self.packs, runs=self.runs + (run,), active=self.active)

    def get_pack(self, tenant_id: str, rule_pack_id: str) -> RulePackRecord:
        for pack in self.packs:
            if pack.rule_pack_id == rule_pack_id and pack.tenant_id == tenant_id:
                return pack
        # Uniform not-found: never reveal whether the id exists in another tenant.
        raise LookupError("rule pack not found")

    def packs_for_tenant(self, tenant_id: str) -> list[RulePackRecord]:
        return [p for p in self.packs if p.tenant_id == tenant_id]

    def runs_for_tenant(self, tenant_id: str) -> list[RunSnapshot]:
        return [r for r in self.runs if r.tenant_id == tenant_id]

    def active_pack_id(self, tenant_id: str, mode: str) -> str | None:
        for tenant, pack_mode, pack_id in self.active:
            if tenant == tenant_id and pack_mode == mode:
                return pack_id
        return None

    def _with_active(self, tenant_id: str, mode: str, pack_id: str) -> RulePackRegistry:
        active = tuple(a for a in self.active if not (a[0] == tenant_id and a[1] == mode))
        return RulePackRegistry(
            packs=self.packs, runs=self.runs, active=active + ((tenant_id, mode, pack_id),)
        )


def grant_demo_use(
    pack: Mapping[str, Any],
    files_content: Mapping[str, Any],
    gap_ids: Collection[str],
    *,
    actor: str,
    purpose: str,
) -> DemoGrant:
    """Grant local validated-draft explicit-ladder demo use (no approval invented).

    The pack must validate structurally and be in draft/validated status. The
    grant records fixed limits and never changes activation state; customer
    activation still requires `activate_rulepack` with a recorded approver.
    """
    if not actor or not purpose:
        raise ValueError("demo grant requires actor and purpose")
    if pack.get("status") not in DEMO_STATUSES:
        raise ValueError("demo use is limited to draft/validated packs")
    result = validate_rulepack(pack, files_content, gap_ids)
    if not result.ok:
        raise ValueError("rule pack failed validation: " + "; ".join(result.errors))
    return DemoGrant(
        rule_pack_id=str(pack["rule_pack_id"]),
        tenant_id=str(pack["tenant_id"]),
        sha256=str(pack["sha256"]),
        actor=actor,
        purpose=purpose,
        approved_by=pack.get("approved_by"),
    )


def activate_rulepack(
    registry: RulePackRegistry,
    rule_pack_id: str,
    tenant_id: str,
    *,
    actor: str,
    reason: str,
    files_content: Mapping[str, Any],
    gap_ids: Collection[str],
) -> tuple[RulePackRegistry, ActivationRecord]:
    """Activate a validated pack as the default for NEW runs of (tenant, mode).

    Existing runs keep their frozen rule_pack_id/rule_pack_sha256 snapshot.
    The previously active pack is retired (preserved), never overwritten.
    Re-activating the already-active pack is idempotent.
    """
    if not actor or not reason:
        raise ValueError("activation requires actor and reason")
    pack = registry.get_pack(tenant_id, rule_pack_id)
    if pack.status == "retired":
        raise ValueError("retired packs cannot be activated")
    if pack.status != "validated" and not (
        pack.status == "active" and registry.active_pack_id(tenant_id, pack.mode) == rule_pack_id
    ):
        raise ValueError("only status=validated packs can be activated (validate first)")
    if not pack.approved_by or not pack.approved_at:
        raise ValueError("activation requires approved_by and approved_at")

    result = validate_rulepack(pack.to_dict(), files_content, gap_ids)
    if not result.ok:
        raise ValueError("rule pack failed validation: " + "; ".join(result.errors))

    current_id = registry.active_pack_id(tenant_id, pack.mode)
    if current_id == rule_pack_id:
        return registry, ActivationRecord(
            before_pack_id=current_id,
            after_pack_id=rule_pack_id,
            tenant_id=tenant_id,
            mode=pack.mode,
            actor=actor,
            reason=reason,
        )

    packs: list[RulePackRecord] = []
    for existing in registry.packs:
        if (
            existing.tenant_id == tenant_id
            and existing.mode == pack.mode
            and existing.rule_pack_id == current_id
            and existing.status == "active"
        ):
            packs.append(replace(existing, status="retired"))
        elif existing.rule_pack_id == rule_pack_id and existing.tenant_id == tenant_id:
            packs.append(replace(existing, status="active"))
        else:
            packs.append(existing)
    # Runs are carried over untouched: the same tuple object is preserved.
    updated = RulePackRegistry(packs=tuple(packs), runs=registry.runs, active=registry.active)
    updated = updated._with_active(tenant_id, pack.mode, rule_pack_id)
    record = ActivationRecord(
        before_pack_id=current_id,
        after_pack_id=rule_pack_id,
        tenant_id=tenant_id,
        mode=pack.mode,
        actor=actor,
        reason=reason,
    )
    return updated, record
