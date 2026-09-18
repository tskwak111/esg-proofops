"""Conservative majority candidates; only unanimous guarded tags can be confirmed."""

from collections import Counter
from dataclasses import dataclass, replace

from proofops.application.evidence.retrieval import EvidencePacket
from proofops.application.tagging.service import TagRun
from proofops.domain.errors import DomainValidationError
from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import MAPPINGS, ConfirmedFact, ConfirmedTags
from proofops.domain.values import LlmElement


@dataclass(frozen=True, slots=True)
class ConsensusResult:
    candidate_elements: tuple[LlmElement, ...]
    agreement: tuple[tuple[str, int], ...]
    review_status: str
    confirmed_tags: ConfirmedTags | None
    reasons: tuple[str, ...]
    replicate_hashes: tuple[str, ...]


def form_consensus(
    runs: tuple[TagRun, ...],
    *,
    packet: EvidencePacket,
    rulepack: RulePackSnapshot,
    tenant_id: str,
    tag_revision: int,
    rule_gaps: tuple[str, ...] = (),
) -> ConsensusResult:
    """A 2:1 majority is a review candidate, never an automatic confirmed revision.

    Raw/guarded receipts stay with the caller's immutable revision. Compound
    elements retain their complete tagged value and evidence on each constituent
    primitive; no year/unit/numeric value is inferred by splitting a string.
    Missing/unresolved elements and failed replicas cannot masquerade as absence.
    """
    data = packet.to_dict()
    selected_track = data.get("track")
    if (
        "retrieval_packet_sha256" not in data
        or selected_track not in MAPPINGS
        or data["allowed_elements"]
        != [
            e["id"]
            for e in rulepack.file_content("rubric/elements.yaml")["elements"]
            if e["id"] in MAPPINGS[selected_track]
        ]
        or set(data["allowed_elements"]) != set(MAPPINGS[selected_track])
    ):
        raise DomainValidationError("complete frozen track packet required")
    if len(runs) != 3 or {r.replicate_id for r in runs} != {1, 2, 3}:
        raise DomainValidationError("exactly one run per replicate required")
    ordered = tuple(sorted(runs, key=lambda r: r.replicate_id))
    if data["tenant_id"] != tenant_id or rulepack.tenant_id != tenant_id:
        raise DomainValidationError("tenant mismatch")
    for run in ordered:
        if (
            run.tenant_id,
            run.claim_id,
            run.run_id,
            run.packet_sha256,
            run.graph_sha256,
            run.rule_sha256,
        ) != (
            tenant_id,
            data["claim_id"],
            data["run_id"],
            packet.packet_sha256,
            data["graph_sha256"],
            rulepack.sha256,
        ):
            raise DomainValidationError("replicate packet/provenance mismatch")
        if run.guarded and (
            run.guarded.replicate_id,
            run.guarded.packet_sha256,
            run.guarded.claim_id,
        ) != (run.replicate_id, run.packet_sha256, run.claim_id):
            raise DomainValidationError("guarded vote identity mismatch")
    if (
        len({r.request.request_id for r in ordered}) != 3
        or len({r.request.request_signature for r in ordered}) != 3
    ):
        raise DomainValidationError("independent request identities required")
    if (
        len(
            {
                (r.model_sha256, r.prompt_sha256, r.request.extraction_epoch, r.product_variant)
                for r in ordered
            }
        )
        != 1
    ):
        raise DomainValidationError("replicate model/prompt/epoch mismatch")
    reasons = list(rule_gaps)
    provider_ids = [
        r.usage.provider_request_id for r in ordered if r.usage and r.usage.provider_request_id
    ]
    if len(provider_ids) != len(set(provider_ids)):
        reasons.append("PROVIDER_RESPONSE_REPLAY")
    if any(r.status != "succeeded" or r.errors or r.guarded is None for r in ordered):
        reasons.append("REPLICA_UNRESOLVED")
    headers = {
        (r.guarded.track, r.guarded.safe_harbor_category, r.guarded.superlative_quote)
        for r in ordered
        if r.guarded
    }
    if len(headers) != 1:
        reasons.append("TRACK_CATEGORY_SUPERLATIVE_DISAGREEMENT")
    candidates, agreement, facts = [], [], []
    track = next(iter(headers))[0] if len(headers) == 1 else None
    if any(header[:2] != (selected_track, data.get("safe_harbor_category")) for header in headers):
        reasons.append("PACKET_TRACK_MISMATCH")
    requested = data["allowed_elements"]
    for element_id in requested:
        votes = []
        for run in ordered:
            if run.guarded:
                for element in run.guarded.elements:
                    if element.element_id == element_id:
                        key = (
                            element.state,
                            element.normalized_value,
                            dict(run.binding_hashes).get(element_id),
                        )
                        votes.append((key, element))
        counts = Counter(key for key, _ in votes)
        common = counts.most_common(1)
        count = common[0][1] if common else 0
        agreement.append((element_id, count))
        if count < 2:
            reasons.append(f"NO_MAJORITY:{element_id}")
            continue
        key = common[0][0]
        winners = [element for vote, element in votes if vote == key]
        refs = tuple(dict.fromkeys(ref for element in winners for ref in element.evidence_refs))
        candidate = replace(winners[0], evidence_refs=refs)
        candidates.append(candidate)
        scopes = {dict(run.source_scopes).get(element_id) for run in ordered if run.guarded}
        scope = next(
            (scope for scope in ("global_bound", "same_table", "local_claim") if scope in scopes),
            "local_claim",
        )
        if count != 3 or candidate.state in ("unknown", "conflict"):
            reasons.append(f"REVIEW:{element_id}")
        if track is not None:
            names = MAPPINGS[track].get(element_id)
            if names is None:
                reasons.append(f"ELEMENT_TRACK_MISMATCH:{element_id}")
                continue
            if candidate.state == "present":
                for name in names:
                    facts.append(
                        ConfirmedFact(
                            name,
                            "present",
                            refs,
                            tenant_id,
                            True,
                            True,
                            source_scope=scope,
                            normalized_value=candidate.normalized_value,
                        )
                    )
            else:
                # No synthetic absence/applicability attestation is minted here.
                facts.extend(ConfirmedFact(name, candidate.state) for name in names)
    hashes = tuple(run.semantic_hash for run in ordered)
    confirmed = None
    if not reasons and track is not None:
        first = ordered[0]
        header = next(iter(headers))
        confirmed = ConfirmedTags(
            tenant_id,
            data["document_version_id"],
            data["claim_id"],
            track,
            tuple(facts),
            tag_revision,
            packet.packet_sha256,
            first.model_sha256,
            first.prompt_sha256,
            hashes,
            rulepack.ontology_version,
            header[1],
            header[2],
            first.product_variant,
        )
    return ConsensusResult(
        tuple(candidates),
        tuple(agreement),
        "auto_confirmed" if confirmed else "needs_review",
        confirmed,
        tuple(sorted(set(reasons))),
        hashes,
    )
