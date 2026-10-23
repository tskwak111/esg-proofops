"""Current-head validation and pure immutable tag/decision construction."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from inspect import Parameter
from typing import Any, cast

from proofops.application.authorization import AuthContext
from proofops.application.tagging.consensus import (
    PARTIAL_FACTS_PROFILES,
)
from proofops.application.tagging.fact_assembly_c2 import FactAssemblyReceiptV1
from proofops.application.tagging.fact_assembly_c3 import PROFILE as C3_PROFILE
from proofops.application.tagging.fact_assembly_c3_v2 import PROFILE as C3_V2_PROFILE
from proofops.application.tagging.fact_assembly_c4 import PROFILE as C4_PROFILE
from proofops.application.tagging.service import TagRun
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import (
    MAPPINGS,
    ConfirmedFact,
    ConfirmedTags,
    Decision,
    evaluate,
)
from proofops.domain.values import LlmElement

from .contracts import ContextSourceVerifier, ReviewRejected, SourceVerifier
from .corrections import _review_applicability, _review_category, _review_safe_harbor
from .elements import validate_context_review, validate_elements
from .inputs import ReviewInputs


@dataclass(frozen=True)
class PreparedRevision:
    """Validated facts and receipts, with the immutable source snapshot still pinned."""

    input_snapshot_sha256: str
    facts: tuple[ConfirmedFact, ...]
    elements: list[dict[str, Any]]
    corrected_category: str | None
    receipts: dict[str, Any]


def prepare_revision(
    inputs: ReviewInputs,
    actor: AuthContext,
    body: dict[str, Any],
    elements: Sequence[LlmElement],
    initial: dict[str, Any],
    *,
    applicability_review: dict[str, Any] | None = None,
    safe_harbor_review: dict[str, Any] | None = None,
    category_review: dict[str, Any] | None = None,
    context_review: dict[str, Any] | None = None,
    reopen: bool = False,
    verify_context_sources: ContextSourceVerifier | None = None,
    verifier_parameters: Mapping[str, Parameter],
    pinned_run_snapshot: dict[str, Any] | None,
    verify_source_ref: SourceVerifier,
) -> PreparedRevision:
    """Revalidate the current head and its correction ancestry inside the transaction."""
    inputs.validate()
    # ``initial`` is the current tag head: the consensus tag (carries the
    # full ``inputs`` snapshot) on the first resolve, or a prior reviewed
    # tag (carries only ``input_snapshot_sha256``) on an explicit
    # re-review. Both must pin the same immutable loader snapshot, so a
    # re-review can never silently rebind to different inputs.
    initial_snapshot_sha256 = (
        canonical_hash(initial["inputs"])
        if "inputs" in initial
        else initial.get("input_snapshot_sha256")
    )
    if canonical_hash(inputs.snapshot()) != initial_snapshot_sha256:
        raise ReviewRejected("REVIEW_INPUT_MISMATCH", 409)
    # On an explicit re-review the fact base is the ORIGINAL consensus,
    # but any prior reviewed applicability/safe-harbor attestation on the
    # current head must be carried forward and re-validated (never
    # silently reverted). Re-supplied reviews override the carried ones;
    # when the caller omits them we replay the prior receipt's exact
    # request through the same guard chain so an unchanged re-review
    # reproduces the same honest decision (e.g. M5/M6 exclusion).
    carried_applicability = None
    carried_safe_harbor = None
    carried_category = None
    # Preserve the ORIGINAL attestation ancestry across chained carries:
    # if the prior receipt already recorded a ``carried_from`` we keep it,
    # otherwise the immediate prior tag's provenance is the origin. This
    # stops a human->human re-review from erasing an AI-delegated ancestor.
    prior_provenance = {
        k: initial[k]
        for k in ("origin", "reviewer_sub", "review_origin", "delegated_reviewer")
        if k in initial
    }
    applicability_ancestry = prior_provenance
    safe_harbor_ancestry = prior_provenance
    category_ancestry = prior_provenance
    if reopen:
        prior_applicability = initial.get("applicability_review")
        if isinstance(prior_applicability, dict):
            carried_applicability = prior_applicability.get("request")
            if isinstance(prior_applicability.get("carried_from"), dict):
                applicability_ancestry = prior_applicability["carried_from"]
        prior_safe_harbor = initial.get("safe_harbor_review")
        if isinstance(prior_safe_harbor, dict):
            carried_safe_harbor = prior_safe_harbor.get("request")
            if isinstance(prior_safe_harbor.get("carried_from"), dict):
                safe_harbor_ancestry = prior_safe_harbor["carried_from"]
        prior_category = initial.get("category_review")
        if isinstance(prior_category, dict):
            carried_category = prior_category.get("request")
            if isinstance(prior_category.get("carried_from"), dict):
                category_ancestry = prior_category["carried_from"]
    effective_applicability = (
        applicability_review if applicability_review is not None else carried_applicability
    )
    effective_safe_harbor = (
        safe_harbor_review if safe_harbor_review is not None else carried_safe_harbor
    )
    effective_category = category_review if category_review is not None else carried_category
    # Provenance of a carried (not re-supplied) attestation stays the
    # original reviewer's, never relabelled as the current actor. A human
    # HTTP re-review therefore cannot present an inherited AI-delegated
    # applicability/safe-harbor receipt as freshly human-attested.
    applicability_carried = applicability_review is None and carried_applicability is not None
    safe_harbor_carried = safe_harbor_review is None and carried_safe_harbor is not None
    category_carried = category_review is None and carried_category is not None
    base = inputs.consensus.confirmed_tags
    facts = {f.name: f for f in base.facts} if base else {}
    previous_names = {
        n for names in MAPPINGS[inputs.packet.to_dict()["track"]].values() for n in names
    }
    definitions = {
        e["id"]: e for e in inputs.rulepack.file_content("rubric/elements.yaml")["elements"]
    }
    trigger_names = {e["trigger"] for e in definitions.values() if e.get("trigger")}
    # A changed track requires fresh applicability, never inherited trigger tags.
    if body["track"] != inputs.packet.to_dict()["track"]:
        previous_names |= trigger_names | {"willingness_only"}
    # A category correction and a category checklist attestation cannot
    # coexist in one revision: the checklist documents the very category
    # being removed. Fail closed for a freshly supplied AND for a carried
    # safe-harbor review instead of dropping either one silently.
    corrected_category, category_receipt = (None, None)
    if effective_category is not None:
        if effective_safe_harbor is not None:
            raise ReviewRejected("CATEGORY_REVIEW_CONFLICTS_SAFE_HARBOR", 409)
        corrected_category, category_receipt, superseded_items = _review_category(
            inputs, body["track"], effective_category, verify_source_ref=verify_source_ref
        )
        # Exclude only the removed category's checklist names from the NEW
        # fact basis. The prior revision keeps them verbatim and immutable.
        previous_names |= set(superseded_items)
    reviewed_facts: list[ConfirmedFact] = []
    applicability_receipt: dict[str, Any] | None = None
    if effective_applicability is not None:
        reviewed_facts, applicability_receipt = _review_applicability(
            inputs, body["track"], effective_applicability, verify_source_ref=verify_source_ref
        )
        previous_names |= {f.name for f in reviewed_facts}
    safe_harbor_facts: list[ConfirmedFact] = []
    safe_harbor_receipt: dict[str, Any] | None = None
    if effective_safe_harbor is not None:
        safe_harbor_facts, safe_harbor_receipt = _review_safe_harbor(
            inputs, effective_safe_harbor, verify_source_ref=verify_source_ref
        )
        previous_names |= {f.name for f in safe_harbor_facts}
    new_facts = [f for n, f in facts.items() if n not in previous_names] + reviewed_facts
    new_facts += safe_harbor_facts
    context_receipt, original_refs = validate_context_review(
        inputs,
        body,
        initial,
        context_review=context_review,
        reopen=reopen,
        prior_provenance=prior_provenance,
        verify_context_sources=verify_context_sources,
        pinned_run_snapshot=pinned_run_snapshot,
    )
    element_facts, checked_elements, report_level_receipts = validate_elements(
        inputs,
        actor,
        body,
        elements,
        initial,
        facts=facts,
        definitions=definitions,
        context_receipt=context_receipt,
        original_refs=original_refs,
        verify_context_sources=verify_context_sources,
        verifier_parameters=verifier_parameters,
        pinned_run_snapshot=pinned_run_snapshot,
        verify_source_ref=verify_source_ref,
    )
    new_facts.extend(element_facts)
    receipts: dict[str, Any] = {}
    if applicability_receipt is not None:
        if applicability_carried and applicability_ancestry:
            applicability_receipt = {
                **applicability_receipt,
                "carried_from": applicability_ancestry,
            }
        receipts["applicability_review"] = applicability_receipt
    if safe_harbor_receipt is not None:
        if safe_harbor_carried and safe_harbor_ancestry:
            safe_harbor_receipt = {
                **safe_harbor_receipt,
                "carried_from": safe_harbor_ancestry,
            }
        receipts["safe_harbor_review"] = safe_harbor_receipt
    if category_receipt is not None:
        if category_carried and category_ancestry:
            category_receipt = {**category_receipt, "carried_from": category_ancestry}
        receipts["category_review"] = category_receipt
    if context_receipt is not None:
        receipts["claim_context_review"] = context_receipt
    if report_level_receipts:
        receipts["report_level_review"] = report_level_receipts
    return PreparedRevision(
        initial_snapshot_sha256, tuple(new_facts), checked_elements, corrected_category, receipts
    )


def build_revision(
    inputs: ReviewInputs,
    actor: AuthContext,
    body: dict[str, Any],
    review: dict[str, Any],
    decision_revision: int,
    prepared: PreparedRevision,
    *,
    origin: str,
    review_status: str,
    reviewer_sub: str | None,
    extra_tag: dict[str, Any] | None,
    evaluate: Callable[..., Decision] = evaluate,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pure tag/decision builder; semantic grading remains exclusively in the rule engine."""
    headers = {
        (r.guarded.safe_harbor_category, r.guarded.superlative_quote)
        for r in inputs.tag_runs
        if r.guarded
    }
    if inputs.fact_assembly_profile in (C3_PROFILE, C3_V2_PROFILE, C4_PROFILE):
        # Input replay already required the profile-specific publication receipt.
        receipt = cast(FactAssemblyReceiptV1, inputs.fact_assembly_receipt)
        headers = {
            (r["raw"]["safe_harbor_category"], r["raw"]["superlative_quote"])
            for r in cast("Callable[[], dict[str, Any]]", receipt.to_dict)()["raw_receipts"]
        }
    if len(headers) != 1:
        raise ReviewRejected("CATEGORY_REVIEW_REQUIRED", 409)
    category, superlative = next(iter(headers))
    if "category_review" in prepared.receipts:
        # Only the confirmed classification changes; the observed headers
        # above stay pinned in the receipt and in ``inputs``.
        category = prepared.corrected_category
    if inputs.fact_assembly_profile in (C3_PROFILE, C3_V2_PROFILE, C4_PROFILE):
        first: ConfirmedTags | TagRun = cast(ConfirmedTags, inputs.consensus.confirmed_tags)
    else:
        first = inputs.tag_runs[0]
    confirmed = ConfirmedTags(
        actor.tenant_id,
        inputs.original.document_version_id,
        review["claim_id"],
        body["track"],
        prepared.facts,
        body["base_tag_revision"] + 1,
        inputs.packet.packet_sha256,
        first.model_sha256,
        first.prompt_sha256,
        inputs.consensus.replicate_hashes,
        inputs.rulepack.ontology_version,
        category,
        superlative,
        first.product_variant,
    )
    decision = evaluate(
        confirmed,
        replace(inputs.rule_context, decision_revision=decision_revision),
        inputs.rulepack,
    )
    if inputs.fact_assembly_receipt is not None and inputs.fact_assembly_profile not in (
        C3_PROFILE,
        C3_V2_PROFILE,
        C4_PROFILE,
    ):
        # A reviewer cannot activate an unpublished experimental profile.
        # CAS has already been checked by the store; no revision is written.
        raise ReviewRejected("C2_PUBLICATION_DISABLED", 409)
    # Preserve the engine semantic hash exactly; review status is provenance metadata.
    api = decision.to_api_dict() | {"review_status": review_status}
    tag = dict(
        tag_revision=confirmed.tag_revision,
        confirmed_tags=asdict(confirmed),
        elements=prepared.elements,
        origin=origin,
        reviewer_sub=reviewer_sub if reviewer_sub is not None else actor.user_sub,
        review_reason=body["reason"],
        input_snapshot_sha256=prepared.input_snapshot_sha256,
    )
    if inputs.fact_assembly_profile in PARTIAL_FACTS_PROFILES:
        tag["fact_assembly"] = inputs.snapshot()["fact_assembly"]
    tag.update(prepared.receipts)
    if extra_tag:
        tag.update(extra_tag)
    decision_record = dict(decision_revision=decision_revision, decision=asdict(decision), api=api)
    if "fact_assembly" in tag:
        decision_record["fact_assembly"] = tag["fact_assembly"]
    return tag, decision_record
