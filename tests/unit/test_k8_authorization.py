from datetime import UTC, datetime

import pytest
from proofops.application.authorization import TenantNotFoundError
from proofops.application.preflight import check_local_upstage_binding
from proofops.domain.provenance import canonical_hash

from evaluation.k8_authorization import fresh_grants
from tests.acceptance.test_preflight import AUTH
from tests.integration.test_upstage_runtime import profiles


def test_fresh_local_task_grant_preserves_source_and_tenant_fences():
    runtime, consent = profiles()
    runtime.update(
        budget_limit_usd="3.00",
        provider="openai",
        model_id="gpt-6-luna",
        endpoint="https://api.openai.com/v1/chat/completions",
    )
    consent["provider"] = "openai"
    before = {"runtime": runtime, "consent": consent}
    now = datetime.now(UTC).isoformat()
    model_hash = canonical_hash(
        dict(model="gpt-6-luna", provider="openai", transport="OpenAIProbe")
    )
    kwargs = dict(auth=AUTH, checked_at=now, source_sha256="a" * 64, model_sha256=model_hash)
    assert not check_local_upstage_binding(binding=runtime, consent=consent, **kwargs).ready
    after = fresh_grants(before)
    kwargs["checked_at"] = datetime.now(UTC).isoformat()
    assert check_local_upstage_binding(
        binding=after["runtime"], consent=after["consent"], **kwargs
    ).ready
    assert after["consent"]["allowed_source_sha256"] == consent["allowed_source_sha256"]
    assert after["consent"]["allowed_document_rights"] == consent["allowed_document_rights"]
    assert after["runtime"]["runtime_binding_id"] != runtime["runtime_binding_id"]
    assert after["runtime"]["budget_limit_usd"] == "3.00"
    assert not check_local_upstage_binding(
        binding=after["runtime"],
        consent=after["consent"],
        **(kwargs | dict(source_sha256="b" * 64)),
    ).ready
    with pytest.raises(TenantNotFoundError):
        check_local_upstage_binding(
            binding=after["runtime"] | dict(tenant_id="00000000-0000-4000-8000-000000000099"),
            consent=after["consent"],
            **kwargs,
        )


def test_k8_does_not_renew_other_provider_or_production_grants():
    runtime, consent = profiles()
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        fresh_grants(dict(runtime=runtime, consent=consent))


def test_revoked_grant_is_not_reapproved():
    runtime, consent = profiles()
    runtime.update(provider="openai", status="revoked")
    consent["provider"] = "openai"
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        fresh_grants(dict(runtime=runtime, consent=consent))


def test_all_copied_model_role_grants_receive_fresh_ids_and_expiry():
    runtime, consent = profiles()
    runtime.update(provider="openai", budget_limit_usd="3.00")
    consent["provider"] = "openai"
    snapshot = dict(runtime=runtime, consent=consent)
    for prefix in ("preliminary", "tagging", "relation"):
        snapshot[prefix + "_runtime"] = runtime | dict(role=prefix)
    changes = fresh_grants(snapshot)
    for prefix in ("preliminary", "tagging", "relation"):
        field = prefix + "_runtime"
        assert changes[field]["expires_at"] == changes["runtime"]["expires_at"]
        assert changes[field]["runtime_binding_id"] != snapshot[field]["runtime_binding_id"]
        assert changes[field]["role"] == prefix
