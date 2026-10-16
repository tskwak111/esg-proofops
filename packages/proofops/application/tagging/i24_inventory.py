"""V24 inventory dispatch limits. Existing grants and dollar ceilings still apply."""

from proofops.application.tagging.element_inventory import POLICY as INVENTORY_POLICY
from proofops.application.tagging.element_inventory import (
    POLICY_HASH,
    PROMPT,
    STATES,
    inventory_request,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json

SPAN = dict(
    type="object",
    additionalProperties=False,
    required=["source_id", "char_start", "char_end"],
    properties=dict(
        source_id=dict(type="string"),
        char_start=dict(type="integer"),
        char_end=dict(type="integer"),
    ),
)
SCHEMA = dict(
    type="object",
    additionalProperties=False,
    required=["complete", "records", "packet_sha256", "replicate_id"],
    properties=dict(
        complete=dict(type="boolean"),
        packet_sha256=dict(type="string"),
        replicate_id=dict(type="integer"),
        records=dict(
            type="array",
            items=dict(
                type="object",
                additionalProperties=False,
                required=["element_id", "state", "evidence", "attributes"],
                properties=dict(
                    element_id=dict(type="string", enum=sorted(INVENTORY_POLICY["terms"])),
                    state=dict(type="string", enum=sorted(STATES)),
                    evidence=SPAN,
                    attributes=dict(
                        type="object",
                        additionalProperties=False,
                        required=["subject", "metric", "site", "period"],
                        properties={
                            k: dict(anyOf=[SPAN, dict(type="null")])
                            for k in ("subject", "metric", "site", "period")
                        },
                    ),
                ),
            ),
        ),
    ),
)


WIRE_PROMPT = (
    PROMPT
    + "\nJSON schema: "
    + canonical_json(SCHEMA)
    + "\nElement cue hints (retain contrary evidence): "
    + canonical_json(INVENTORY_POLICY["terms"])
)

POLICY = dict(
    profile="sc1_hosted_inventory_i24_v1",
    inventory_policy_sha256=POLICY_HASH,
    prompt_sha256=canonical_hash(PROMPT),
    wire_prompt_sha256=canonical_hash(WIRE_PROMPT),
    wire="exact_span_offsets_and_text; full_provenance_in_receipts",
    max_calls=300,
    max_output_tokens=1024,
    max_reserved_usd="2.00",
    provider="existing_tagging_transport_grant_and_shared_broker",
    retries="existing_provider_bound; no_inventory_retry",
    failure="uninspected; never_absence",
    freshness="current_response; reject_response_reuse_or_replay",
    graph="final_full_selected_scope_after_source_verification",
)


def transport_request(request, settings):
    """Wrap the SC1 packet without changing its independent request identity."""
    from dataclasses import asdict

    from proofops.application.fxh_policy import POLICY as FXH_POLICY

    execution = request["untrusted_document_data"]["selection"].get("fxh_inventory_execution")
    if execution is not None and execution != FXH_POLICY:
        raise ValueError("FXH_INVENTORY_POLICY_MISMATCH")

    if request != inventory_request(
        request["untrusted_document_data"], request["replicate_id"], settings.model_sha256
    ):
        raise ValueError("SC1_REQUEST_MISMATCH")
    body = dict(
        tenant_id=request["tenant_id"],
        claim_id=request["run_id"],  # document-scoped authorization key, never a claim tag
        packet_sha256=request["packet_sha256"],
        replicate_id=request["replicate_id"],
        request_id=request["request_id"],
        binding=asdict(settings.binding),
        model_id=settings.model_id,
        model_profile=settings.model_profile,
        region=settings.region,
        system_prompt=request["system_prompt"],
        user_json=canonical_json(request),
        temperature=0,
        max_tokens=min(
            settings.max_tokens,
            (execution["inventory_output_tokens"] if execution else POLICY["max_output_tokens"]),
        ),
        sc1_transport_policy_sha256=canonical_hash(POLICY),
    )
    return body | dict(request_signature=canonical_hash(body))
