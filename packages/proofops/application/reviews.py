"""Human tag revisions; source guards and pure rules are the only grading path.

An additive, explicitly-delegated AI review route exists for a trusted local
operator (``ReviewService.resolve_ai_delegated_review``). It reuses the exact
same source/binding/If-Match/engine guards as the human route and records an
honest ``ai_delegated`` origin -- it never writes ``human`` provenance for
machine-driven work. The HTTP body can never self-assert provenance: both
routes accept only the fixed 4-key correction body, and the AI origin is
supplied by backend constructor arguments, never by caller JSON.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from inspect import signature
from typing import Any, Protocol

from proofops.application.authorization import AuthContext
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.review_parts.contracts import (
    AI_DELEGATED_ORIGIN as AI_DELEGATED_ORIGIN,
)
from proofops.application.review_parts.contracts import (
    AI_DELEGATED_REVIEW_ORIGIN as AI_DELEGATED_REVIEW_ORIGIN,
)
from proofops.application.review_parts.contracts import (
    AI_DELEGATED_REVIEW_STATUS as AI_DELEGATED_REVIEW_STATUS,
)
from proofops.application.review_parts.contracts import (
    AI_DELEGATED_REVIEWER_PREFIX as AI_DELEGATED_REVIEWER_PREFIX,
)
from proofops.application.review_parts.contracts import (
    CATEGORY_POLICY_V1 as CATEGORY_POLICY_V1,
)
from proofops.application.review_parts.contracts import (
    HUMAN_ORIGIN as HUMAN_ORIGIN,
)
from proofops.application.review_parts.contracts import (
    HUMAN_REVIEW_STATUS as HUMAN_REVIEW_STATUS,
)
from proofops.application.review_parts.contracts import ContextSourceVerifier, RevisionBuilder
from proofops.application.review_parts.contracts import (
    ReviewRejected as ReviewRejected,
)
from proofops.application.review_parts.corrections import (
    _packet_ref_index as _packet_ref_index,
)
from proofops.application.review_parts.corrections import (
    _review_applicability as _review_applicability,
)
from proofops.application.review_parts.corrections import (
    _review_category as _review_category,
)
from proofops.application.review_parts.corrections import (
    _review_safe_harbor as _review_safe_harbor,
)
from proofops.application.review_parts.corrections import (
    parse_resolution as parse_resolution,
)
from proofops.application.review_parts.inputs import ReviewInputs as ReviewInputs
from proofops.application.review_parts.inputs import build_open_review
from proofops.application.review_parts.revisions import build_revision, prepare_revision
from proofops.application.tagging.consensus import (
    form_consensus as form_consensus,
)
from proofops.domain.audit import AuditConflict
from proofops.domain.errors import DomainValidationError
from proofops.domain.rules.engine import evaluate as evaluate
from proofops.domain.values import (
    _require_uuid,
)


class ReviewStore(Protocol):
    def publish(self, inputs: ReviewInputs, review: dict[str, Any]) -> dict[str, Any]: ...
    def publish_transaction(
        self, db: sqlite3.Connection, inputs: ReviewInputs, review: dict[str, Any]
    ) -> dict[str, Any]: ...
    def get(self, tenant_id: str, review_id: str) -> dict[str, Any]: ...
    def resolve(
        self,
        actor: AuthContext,
        review_id: str,
        body: dict[str, Any],
        expected: int,
        key: str,
        build: RevisionBuilder,
        *,
        reopen: bool = False,
    ) -> dict[str, Any]: ...


class ReviewService:
    def __init__(
        self,
        store: ReviewStore,
        *,
        load_inputs: Callable[[str, str, str], ReviewInputs],
        verify_context_sources: ContextSourceVerifier | None = None,
        load_run_snapshot: Callable[[str, str], dict[str, Any]] | None = None,
    ) -> None:
        self.store, self.load_inputs = store, load_inputs
        self.verify_context_sources = verify_context_sources
        self.load_run_snapshot = load_run_snapshot

    def _review(self, inputs: ReviewInputs, review_id: str | None = None) -> dict[str, Any]:
        return build_open_review(inputs, review_id)

    def publish(self, inputs: ReviewInputs, review_id: str | None = None) -> dict[str, Any]:
        return self.store.publish(inputs, self._review(inputs, review_id))

    def publish_transaction(
        self, connection: sqlite3.Connection, inputs: ReviewInputs, review_id: str | None = None
    ) -> dict[str, Any]:
        return self.store.publish_transaction(connection, inputs, self._review(inputs, review_id))

    def resolve_review(
        self,
        actor: AuthContext,
        review_id: str,
        body: dict[str, Any],
        if_match: str | None,
        idempotency_key: str | None,
        *,
        category_review: dict[str, Any] | None = None,
        reopen: bool = False,
    ) -> dict[str, Any]:
        """Default human route: provenance is always human, never caller-chosen.

        ``reopen=True`` is the explicit human re-review action for a review that
        was already resolved: it produces the next immutable tag/decision/review
        revisions on the CURRENT head and never mutates or reverts the prior
        ones. The default (``reopen=False``) still refuses a resolved review.

        ``category_review`` is a trusted backend-only keyword (the HTTP router
        never supplies it), so the HTTP request contract is unchanged. A human
        re-review still CARRIES and re-validates a prior correction receipt
        without supplying anything.
        """
        return self._resolve_with_provenance(
            actor,
            review_id,
            body,
            if_match,
            idempotency_key,
            origin=HUMAN_ORIGIN,
            review_status=HUMAN_REVIEW_STATUS,
            reviewer_sub=None,
            extra_tag=None,
            category_review=category_review,
            reopen=reopen,
        )

    def resolve_ai_delegated_review(
        self,
        actor: AuthContext,
        review_id: str,
        body: dict[str, Any],
        if_match: str | None,
        idempotency_key: str | None,
        *,
        delegated_reviewer: str,
        delegation_authority: str,
        applicability_review: dict[str, Any] | None = None,
        safe_harbor_review: dict[str, Any] | None = None,
        category_review: dict[str, Any] | None = None,
        context_review: dict[str, Any] | None = None,
        reopen: bool = False,
    ) -> dict[str, Any]:
        """Trusted backend-only operation for explicit user-delegated AI review.

        Not reachable from HTTP: ``delegated_reviewer`` and
        ``delegation_authority`` are constructor arguments supplied by local
        operator code (the CLI), never parsed from the correction body, so a
        remote caller cannot self-assert trusted provenance. All factual
        guards (source/binding/If-Match/engine) also apply here. Optional
        applicability and safe-harbor reviews are separately pinned and cannot
        authorize ordinary element absence or a caller-supplied grade.

        ``reopen=True`` is the explicit re-review action for an already-resolved
        review; it stays honestly ``ai_delegated`` and produces the next
        immutable revisions on the current head, never a ``human`` label and
        never a silent mutation of a prior revision.
        """
        if not isinstance(delegated_reviewer, str) or not delegated_reviewer.strip():
            raise ReviewRejected("VALIDATION_ERROR")
        if not isinstance(delegation_authority, str) or not delegation_authority.strip():
            raise ReviewRejected("VALIDATION_ERROR")
        reviewer = delegated_reviewer.strip()
        if len(reviewer) > 320 or "\n" in reviewer:
            raise ReviewRejected("VALIDATION_ERROR")
        return self._resolve_with_provenance(
            actor,
            review_id,
            body,
            if_match,
            idempotency_key,
            origin=AI_DELEGATED_ORIGIN,
            review_status=AI_DELEGATED_REVIEW_STATUS,
            reviewer_sub=f"{AI_DELEGATED_REVIEWER_PREFIX}{reviewer}",
            extra_tag={
                "review_origin": AI_DELEGATED_REVIEW_ORIGIN,
                "delegation_authority": delegation_authority.strip(),
                "delegated_reviewer": reviewer,
            },
            applicability_review=applicability_review,
            safe_harbor_review=safe_harbor_review,
            category_review=category_review,
            context_review=context_review,
            reopen=reopen,
        )

    def _resolve_with_provenance(
        self,
        actor: AuthContext,
        review_id: str,
        body: dict[str, Any],
        if_match: str | None,
        idempotency_key: str | None,
        *,
        origin: str,
        review_status: str,
        reviewer_sub: str | None,
        extra_tag: dict[str, Any] | None,
        applicability_review: dict[str, Any] | None = None,
        safe_harbor_review: dict[str, Any] | None = None,
        category_review: dict[str, Any] | None = None,
        context_review: dict[str, Any] | None = None,
        reopen: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(actor, AuthContext) or not actor.has_capability("reviewer"):
            raise ReviewRejected("FORBIDDEN", 403)
        _require_uuid("review_id", review_id)
        if not isinstance(if_match, str) or not re.fullmatch(r'"[1-9][0-9]*"', if_match):
            raise ReviewRejected("IF_MATCH_REQUIRED", 400)
        if not isinstance(idempotency_key, str) or not 16 <= len(idempotency_key) <= 128:
            raise ReviewRejected("IDEMPOTENCY_KEY_INVALID", 400)
        elements = parse_resolution(body)

        # Existing local read adapters open transactions too. Load the immutable
        # inputs before the writer lock; the transaction still compares pins and
        # both heads before publishing anything.
        target = self.store.get(actor.tenant_id, review_id)
        try:
            inputs = self.load_inputs(actor.tenant_id, target["run_id"], target["claim_id"])
        except KeyError:
            raise ReviewRejected("REVIEW_INPUT_UNAVAILABLE", 409) from None
        verifier_parameters = (
            signature(self.verify_context_sources).parameters
            if self.verify_context_sources is not None
            else {}
        )
        pinned_run_snapshot = (
            self.load_run_snapshot(actor.tenant_id, target["run_id"])
            if self.load_run_snapshot is not None and "pinned_run_snapshot" in verifier_parameters
            else None
        )
        if not inputs.rule_context.local_synthetic and not (
            inputs.rulepack.status == "active"
            and inputs.rulepack.approved_by
            and inputs.rulepack.approved_at
        ):
            raise ReviewRejected("RULEPACK_APPROVAL_REQUIRED", 409)

        def build(
            review: dict[str, Any], initial: dict[str, Any], decision_revision: int
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            prepared = prepare_revision(
                inputs,
                actor,
                body,
                elements,
                initial,
                applicability_review=applicability_review,
                safe_harbor_review=safe_harbor_review,
                category_review=category_review,
                context_review=context_review,
                reopen=reopen,
                verify_context_sources=self.verify_context_sources,
                verifier_parameters=verifier_parameters,
                pinned_run_snapshot=pinned_run_snapshot,
                verify_source_ref=verify_source_ref,
            )
            return build_revision(
                inputs,
                actor,
                body,
                review,
                decision_revision,
                prepared,
                origin=origin,
                review_status=review_status,
                reviewer_sub=reviewer_sub,
                extra_tag=extra_tag,
                evaluate=evaluate,
            )

        try:
            trusted_options = {}
            if applicability_review is not None:
                trusted_options["applicability_review"] = applicability_review
            if safe_harbor_review is not None:
                trusted_options["safe_harbor_review"] = safe_harbor_review
            if category_review is not None:
                trusted_options["category_review"] = category_review
            if context_review is not None:
                trusted_options["context_review"] = context_review
            # Every supplied trusted option joins the retry identity on EVERY
            # callable surface, not only when an AI provenance label is present:
            # a same-key retry with a changed receipt must conflict, never replay.
            # With no trusted option the identity stays the exact legacy shape so
            # stored receipts still replay byte-for-byte.
            retry_identity = dict(extra_tag or {}, **trusted_options) if trusted_options else {}
            return self.store.resolve(
                actor,
                review_id,
                body | {"_trusted_ai_review": retry_identity} if retry_identity else body,
                int(if_match[1:-1]),
                idempotency_key,
                build,
                reopen=reopen,
            )
        except KeyError:
            raise ReviewRejected("REVIEW_INPUT_UNAVAILABLE", 409) from None
        except AuditConflict:
            raise ReviewRejected("REVIEW_CONFLICT", 409) from None
        except DomainValidationError:
            raise ReviewRejected("VALIDATION_ERROR") from None
