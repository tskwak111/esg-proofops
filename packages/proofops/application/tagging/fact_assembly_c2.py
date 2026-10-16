"""DEC-43 bounded direct-certification pilot. Pure assembly; publication disabled.

Three original extraction receipts stay separate from each deterministic result.
The reader recomputes everything from the trusted graph and frozen packet. No
statement union, GRI-page credit, unknown-to-absence, or external I/O exists here.
"""

import json
import re
from dataclasses import asdict, dataclass

from jsonschema import Draft202012Validator
from proofops.application.evidence.binding import accept_binding
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import ConfirmedFact, ConfirmedTags, RuleContext, evaluate
from proofops.domain.values import SourceRef, _require_sha256


def vote_schema():
    selection = dict(
        type="object",
        additionalProperties=False,
        properties=dict(
            source_index=dict(type="integer", minimum=0, maximum=1),
            quote=dict(type="string", minLength=1),
        ),
        required=["source_index", "quote"],
    )
    nullable = dict(anyOf=[selection, dict(type="null")])
    element = dict(
        type="object",
        additionalProperties=False,
        properties=dict(state=dict(enum=["present", "unknown", "conflict"]), evidence=nullable),
        required=["state", "evidence"],
    )
    return dict(
        type="object",
        additionalProperties=False,
        properties=dict(
            track=dict(enum=["management", "performance", "goal", None]),
            safe_harbor_category=dict(type=["string", "null"]),
            superlative_quote=dict(type=["string", "null"]),
            period_kind=dict(enum=["report_context", "explicit_current", None]),
            dimensions=dict(
                type="object",
                additionalProperties=False,
                properties={k: nullable for k in ("activity", "period", "boundary")},
                required=["activity", "period", "boundary"],
            ),
            elements=dict(
                type="object",
                additionalProperties=False,
                properties={f"M{i}": element for i in range(1, 5)},
                required=[f"M{i}" for i in range(1, 5)],
            ),
            triggers=dict(
                type="object",
                additionalProperties=False,
                properties={
                    k: dict(type=["boolean", "null"])
                    for k in ("governance_claim", "compensation_link_claim")
                },
                required=["governance_claim", "compensation_link_claim"],
            ),
        ),
        required=[
            "track",
            "safe_harbor_category",
            "superlative_quote",
            "period_kind",
            "dimensions",
            "elements",
            "triggers",
        ],
    )


PROFILE = "management-direct-certification-c2-v1"
SCHEMA = "FactAssemblyReceiptV1"
POLICY = dict(
    profile=PROFILE,
    enabled=False,
    approval="DEC-43 design only",
    authority="raw_guarded_and_independent_derived_3_of_3",
    scope="same_atomic_activity; direct_ISO14001_assertion_only",
    period="explicit_current_or_same_page_disclosure_context",
    boundary="per_replica_M2_evidence; declared_dimension_containment; no_shared_packet_fill",
    rollback="stop_new_profile; retain_reader_and_immutable_artifacts",
    vote_schema_sha256=canonical_hash(vote_schema()),
)
POLICY_HASH = canonical_hash(POLICY)
ELEMENTS = {
    "M1": "named_means_or_concrete_state",
    "M2": "org_boundary",
    "M3": "external_verification",
    "M4": "concrete_implementation_detail",
}
TRIGGERS = ("governance_claim", "compensation_link_claim")


@dataclass(frozen=True)
class FactAssemblyReceiptV1:
    payload_json: str
    receipt_sha256: str

    def to_dict(self):
        return json.loads(self.payload_json) | dict(receipt_sha256=self.receipt_sha256)


def _receipt(data):
    return FactAssemblyReceiptV1(
        json.dumps(data, ensure_ascii=False, sort_keys=True), canonical_hash(data)
    )


def assemble(
    votes, *, context, graph, packet, rulepack, tag_revision=1, source_scoped_quotes=False
):
    claim = context.claim
    data = packet.to_dict()
    identity = dict(
        tenant_id=claim.tenant_id,
        document_version_id=claim.document_version_id,
        original_sha256=graph.source_sha256,
        parse_manifest_id=graph.parse_manifest_id,
        graph_sha256=canonical_hash(asdict(graph)),
        claim_id=claim.claim_id,
        claim_sha256=canonical_hash(asdict(claim)),
        claim_revision=claim.revision,
        packet_sha256=packet.packet_sha256,
        rulepack_sha256=rulepack.sha256,
    )
    if (
        graph.tenant_id != claim.tenant_id
        or rulepack.tenant_id != claim.tenant_id
        or (claim.document_version_id, claim.parse_manifest_id, claim.source_sha256)
        != (graph.document_version_id, graph.parse_manifest_id, graph.source_sha256)
        or data.get("claim_id") != claim.claim_id
        or data.get("tenant_id") != claim.tenant_id
        or data.get("graph_sha256") != identity["graph_sha256"]
    ):
        raise ValueError("C2_ASSEMBLY_IDENTITY_MISMATCH")
    if any(
        type(v.get("replicate_id")) is not int
        or type(v.get("simulated")) is not bool
        or not isinstance(v.get("provider"), str)
        or not v["provider"]
        for v in votes
    ):
        raise ValueError("C2_PROVENANCE_TYPE_INVALID")
    ordered = sorted(votes, key=lambda v: v["replicate_id"])
    if len(ordered) != 3 or [v["replicate_id"] for v in ordered] != [1, 2, 3]:
        raise ValueError("C2_INDEPENDENT_REPLICAS_REQUIRED")
    for field in ("request_id", "request_sha256", "provider_request_id"):
        if len({v.get(field) for v in ordered}) != 3 or any(not v.get(field) for v in ordered):
            raise ValueError("C2_RESPONSE_REPLAY")
    if (
        len(
            {
                (v["model_sha256"], v["prompt_sha256"], v["provider"], v["simulated"])
                for v in ordered
            }
        )
        != 1
    ):
        raise ValueError("C2_MODEL_PROMPT_PROVIDER_MISMATCH")
    for v in ordered:
        for field in (
            "model_sha256",
            "prompt_sha256",
            "request_sha256",
            "raw_sha256",
            "vote_sha256",
        ):
            _require_sha256(field, v.get(field))
        if not v["simulated"]:
            cache = v.get("cache_identity")
            if (
                not isinstance(cache, dict)
                or type(cache.get("replica")) is not int
                or (
                    cache.get("tenant_id"),
                    cache.get("source_sha256"),
                    cache.get("replica"),
                    cache.get("role"),
                )
                != (claim.tenant_id, graph.source_sha256, v["replicate_id"], "elements")
            ):
                raise ValueError("C2_PROVIDER_SCOPE_MISMATCH")
            _require_sha256("response_sha256", v.get("response_sha256"))
        Draft202012Validator(vote_schema()).validate(v["raw"])
        if (
            v.get("identity") != identity
            or v.get("raw_sha256") != canonical_hash(v["raw"])
            or v.get("vote_sha256")
            != canonical_hash({k: x for k, x in v.items() if k != "vote_sha256"})
        ):
            raise ValueError("C2_RAW_RECEIPT_MISMATCH")
    refs = {str(i): SourceRef(**r) for i, r in enumerate(data["c2_sources"])}
    claim_refs = tuple(
        verify_source_ref(r, graph, tenant_id=claim.tenant_id) for r in claim.source_refs
    )
    claim_verified = bool(claim_refs) and all(
        r.verification_state == "verified" for r in claim_refs
    )
    results, facts_by_replica = [], []

    def ref_for(selection):
        if not isinstance(selection, dict) or set(selection) != {"source_index", "quote"}:
            return None
        source = refs.get(str(selection["source_index"]))
        if source is None or not isinstance(selection["quote"], str) or not selection["quote"]:
            return None
        quote = selection["quote"]
        if source.quote.count(quote) != 1:
            return None
        block = next(b for b in graph.blocks if b.source_id == source.source_id)
        # Use the graph's existing normalized-to-native offset mapping.
        if source_scoped_quotes:
            # CF2: an earlier occurrence outside the supplied source must not
            # hide its unique in-span occurrence. Never widen the admitted span.
            matches = []
            start = block.normalized_text.find(quote)
            while start >= 0:
                ref = block.source_ref(
                    normalized_char_start=start, normalized_char_end=start + len(quote)
                )
                if source.char_start <= ref.char_start < ref.char_end <= source.char_end:
                    matches.append(ref)
                start = block.normalized_text.find(quote, start + 1)
            if len(matches) != 1:
                return None
            checked = verify_source_ref(matches[0], graph, tenant_id=claim.tenant_id)
            return checked if checked.verification_state == "verified" else None
        start = block.normalized_text.find(quote)
        if start < 0:
            return None
        ref = block.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))
        if not source.char_start <= ref.char_start < ref.char_end <= source.char_end:
            return None
        checked = verify_source_ref(ref, graph, tenant_id=claim.tenant_id)
        return checked if checked.verification_state == "verified" else None

    for vote in ordered:
        raw, reasons, elements, facts = vote["raw"], [], {}, []
        if (raw.get("track"), raw.get("safe_harbor_category"), raw.get("superlative_quote")) != (
            "management",
            None,
            None,
        ):
            reasons.append("TRACK_CATEGORY_SUPERLATIVE_UNRESOLVED")
        dims = {
            name: ref_for(raw.get("dimensions", {}).get(name))
            for name in ("activity", "period", "boundary")
        }
        if any(r is None for r in dims.values()):
            reasons.append("ACTIVITY_PERIOD_BOUNDARY_UNRESOLVED")
        if dims["activity"] and not all(
            any(
                c.source_id == r.source_id
                and c.char_start <= r.char_start < r.char_end <= c.char_end
                for c in claim_refs
            )
            for r in (dims["activity"], dims["boundary"])
            if r
        ):
            reasons.append("DIMENSION_OUTSIDE_ATOMIC_ACTIVITY")
        period_kind = raw.get("period_kind")
        period = dims["period"]
        if period and (
            period_kind not in ("explicit_current", "report_context")
            or not re.fullmatch(r"(?:19|20)\d{2}(?: 년|년)?", period.quote)
        ):
            reasons.append("PERIOD_UNRESOLVED")
        if period and period_kind == "report_context":
            block = next(b for b in graph.blocks if b.source_id == period.source_id)
            if (
                "보고서" not in block.normalized_text
                or period.page_num not in {r.page_num for r in claim_refs}
                or re.search(r"20\d{2}", claim.quote)
            ):
                reasons.append("DISCLOSURE_PERIOD_NOT_APPLICABLE")
        elif period and not any(
            c.source_id == period.source_id
            and c.char_start <= period.char_start < period.char_end <= c.char_end
            for c in claim_refs
        ):
            reasons.append("PERIOD_OUTSIDE_ATOMIC_ACTIVITY")
        for eid, primitive in ELEMENTS.items():
            value = raw.get("elements", {}).get(eid, {})
            ref = ref_for(value.get("evidence")) if value.get("state") == "present" else None
            binding = (
                accept_binding(
                    context,
                    ref,
                    {},
                    original=graph,
                    tenant_id=claim.tenant_id,
                    rulepack=rulepack,
                    element_id=eid,
                )
                if ref is not None and claim_verified
                else "undetermined"
            )
            state = "present" if ref and binding == "accepted" else "unknown"
            if eid == "M3" and state == "present":
                # Direct cert clause must name this system, rather than a provider,
                # a policy on the same page, a GRI locator or a report-wide opinion.
                if not (
                    re.search(r"ISO\s*14001", ref.quote, re.I)
                    and "인증" in ref.quote
                    and "환경경영시스템" in claim.quote
                    and dims["activity"]
                    and "환경경영시스템" in dims["activity"].quote
                    and any(
                        c.source_id == ref.source_id
                        and c.char_start <= ref.char_start < ref.char_end <= c.char_end
                        for c in claim_refs
                    )
                ):
                    state = "unknown"
                    reasons.append("DIRECT_CERTIFICATION_ACTIVITY_UNRESOLVED")
            if state != "present":
                reasons.append("UNRESOLVED:" + eid)
            elements[eid] = dict(
                primitive=primitive,
                state=state,
                authority="raw_guarded",
                source_refs=[asdict(ref)] if state == "present" else [],
                binding=binding if state == "present" else "undetermined",
            )
            facts.append(
                ConfirmedFact(primitive, "present", (ref,), claim.tenant_id, True, True)
                if state == "present"
                else ConfirmedFact(primitive, "unknown")
            )
        triggers = raw.get("triggers", {})
        for name in TRIGGERS:
            value = triggers.get(name)
            if value is not False or not claim_verified:
                reasons.append("CONDITIONAL_TRIGGER_REVIEW:" + name)
                facts.append(ConfirmedFact(name, "unknown"))
            else:
                # Fully verified atomic coverage establishes only that this claim
                # does not assert this condition; no evidence element becomes absent.
                facts.append(
                    ConfirmedFact(
                        name,
                        "absent",
                        claim_refs,
                        claim.tenant_id,
                        True,
                        True,
                        search_coverage_verified=True,
                    )
                )
        normalized = dict(
            track=raw.get("track"),
            period_kind=period_kind,
            dimensions={k: asdict(r) if r else None for k, r in dims.items()},
            elements=elements,
            triggers=triggers,
            reasons=sorted(set(reasons)),
        )
        # Quote extents may differ while the verified literal dimensions agree.
        # Keep each complete result hash separately from its agreement tuple.
        m2_ref = ref_for(raw.get("elements", {}).get("M2", {}).get("evidence"))
        boundary_value = None
        if m2_ref and dims["boundary"] and elements["M2"]["state"] == "present":
            hint = dims["boundary"]
            if (
                hint.source_id == m2_ref.source_id
                and m2_ref.char_start <= hint.char_start < hint.char_end <= m2_ref.char_end
            ):
                boundary_value = m2_ref.quote
            else:
                reasons.append("BOUNDARY_DIMENSION_EVIDENCE_DISAGREEMENT")
        else:
            reasons.append("BOUNDARY_SOURCE_UNRESOLVED")
        if boundary_value and "국내 전 생산 사업장" in boundary_value:
            counts = re.search(r"총\s*(\d+)개 생산 사업장 중\s*(\d+)개 사업장", boundary_value)
            if counts and "글로벌 사업장" in boundary_value:
                boundary_value = [
                    "국내 전 생산 사업장",
                    "글로벌 생산 사업장",
                    counts.group(2),
                    counts.group(1),
                ]
            else:
                reasons.append("BOUNDARY_COUNTS_UNRESOLVED")
        activity_value = (
            "환경경영시스템"
            if dims["activity"] and "환경경영시스템" in dims["activity"].quote
            else None
        )
        agreement_value = dict(
            track=raw.get("track"),
            period_kind=period_kind,
            activity=activity_value,
            boundary=boundary_value,
            period=period.quote if period else None,
            activity_source_id=dims["activity"].source_id if dims["activity"] else None,
            boundary_source_id=m2_ref.source_id if m2_ref else None,
            states={e: v["state"] for e, v in elements.items()},
            triggers=triggers,
        )
        normalized["reasons"] = sorted(set(reasons))
        results.append(
            dict(
                replicate_id=vote["replicate_id"],
                matcher_policy_sha256=POLICY_HASH,
                input_sha256=vote["vote_sha256"],
                result=normalized,
                output_sha256=canonical_hash(normalized),
                agreement_value=agreement_value,
                agreement_sha256=canonical_hash(agreement_value),
            )
        )
        facts_by_replica.append(tuple(facts))
    reasons = sorted({r for result in results for r in result["result"]["reasons"]})
    if data.get("status") != "candidate":
        reasons.append("PACKET_SOURCE_BLOCKED")
    equivalent = len({r["agreement_sha256"] for r in results}) == 1
    if not equivalent:
        reasons.append("DERIVED_RESULTS_DISAGREE")
    if not claim_verified:
        reasons.append("CLAIM_SOURCE_UNVERIFIED")
    decision = None
    if equivalent and not reasons:
        tags = ConfirmedTags(
            claim.tenant_id,
            claim.document_version_id,
            claim.claim_id,
            "management",
            facts_by_replica[0],
            tag_revision,
            packet.packet_sha256,
            ordered[0]["model_sha256"],
            ordered[0]["prompt_sha256"],
            tuple(v["vote_sha256"] for v in ordered),
            rulepack.ontology_version,
        )
        decision = evaluate(
            tags,
            RuleContext(
                claim.tenant_id,
                claim.document_version_id,
                claim.claim_id,
                packet.packet_sha256,
                local_synthetic=any(v["simulated"] for v in ordered),
            ),
            rulepack,
        )
    eligible = bool(
        decision
        and decision.decision_status == "decided"
        and decision.review_status == "auto_confirmed"
        and not decision.gap_ids
    )
    return _receipt(
        dict(
            schema=SCHEMA,
            policy=POLICY,
            policy_sha256=POLICY_HASH,
            identity=identity,
            statement_id=canonical_hash([asdict(r) for r in claim_refs]),
            statement_boundary=[asdict(r) for r in claim_refs],
            raw_receipts=ordered,
            derived_results=results,
            resolved_3_of_3=equivalent and not reasons,
            engine_decision=asdict(decision) if decision else None,
            candidate_auto_confirmed=eligible,
            public_auto_confirmed=False,
            simulated=any(v["simulated"] for v in ordered),
            provider=ordered[0]["provider"],
            exclusions=[],
            unresolved=reasons,
        )
    )


def replay(receipt, **inputs):
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != SCHEMA
        or receipt.get("policy_sha256") != POLICY_HASH
        or receipt.get("receipt_sha256")
        != canonical_hash({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    ):
        raise ValueError("C2_ASSEMBLY_RECEIPT_MISMATCH")
    result = assemble(receipt["raw_receipts"], **inputs)
    if canonical_hash(result.to_dict()) != canonical_hash(receipt):
        raise ValueError("C2_ASSEMBLY_REPLAY_MISMATCH")
    return result


def publication_policy_for(profile, *, pinned_hash=None):
    if profile != PROFILE or pinned_hash not in (None, POLICY_HASH):
        raise ValueError("C2_PUBLICATION_PROFILE_MISMATCH")
    raise ValueError("C2_PUBLICATION_DISABLED_COORDINATOR_ACTIVATION_REQUIRED")
