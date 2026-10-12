"""Fresh, source-scoped local grants under the user's explicit fix-K8 instruction."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from proofops.domain.provenance import canonical_hash


def fresh_grants(snapshot, *, approved_by="authorized-local-operator:fix-K8.md"):
    now = datetime.now(UTC)
    changes = {}
    fields = [("runtime", "runtime_binding_id"), ("consent", "consent_profile_id")]
    fields += [
        (prefix + "_runtime", "runtime_binding_id")
        for prefix in ("preliminary", "tagging", "relation")
        if prefix + "_runtime" in snapshot
    ]
    for field, id_field in fields:
        previous = snapshot[field]
        if (
            previous.get("status") != "approved"
            or previous.get("purpose") != "local_test"
            or previous.get("provider") != "openai"
            or previous.get("tenant_id") != snapshot["consent"].get("tenant_id")
        ):
            raise ValueError("K8_LOCAL_APPROVAL_SCOPE_MISMATCH")
        grant = previous | {
            id_field: str(uuid4()),
            "approved_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=8)).isoformat(),
            "approved_by": approved_by,
        }
        changes[field] = grant
        changes[field + "_artifact_hash"] = canonical_hash(grant)
    return changes
