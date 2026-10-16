"""DEC-85 scope confirmation from a single replayed run inventory; no model calls."""

import json
import unicodedata
from dataclasses import asdict, replace

from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.tagging.consensus import form_consensus
from proofops.application.tagging.element_inventory import POLICY_HASH as INVENTORY_HASH
from proofops.application.tagging.element_inventory import replay_inventory
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.analysis_scope import POLICY_HASH as RULE_HASH
from proofops.domain.rules.analysis_scope import evaluate_scope
from proofops.domain.rules.engine import MAPPINGS, ConfirmedFact, ConfirmedTags, evaluate
from proofops.domain.values import SourceRef, llm_tags_from_dict

SCHEMA = "sc1-scope-confirmation-v1"
ATTRIBUTE_ROLES = dict(
    subject="entity", metric="metric", site="facility", period="reporting_period"
)


def agreement_policy(required=3):
    if type(required) is not int or required not in (1, 2, 3):
        raise ValueError("SC1_AGREEMENT_THRESHOLD_INVALID")
    return dict(
        profile="sc1-required-facts-agreement-v1",
        required_present_votes=required,
        total_replicas=3,
        remaining_votes="unknown_only",
        contrary_absent_or_conflict="blocks_confirmation",
        present="verified_bound_same_value; no_failed_replica_as_unknown",
    )


def _consensus(runs, packet, pack, revision, required=3, grade_agreement_policy=None):
    # Reuse the existing independent request/model/packet/tenant contract first.
    result = form_consensus(
        runs,
        packet=packet,
        rulepack=pack,
        tenant_id=packet.to_dict()["tenant_id"],
        tag_revision=revision,
        profile="grade-relevant-unanimity-v3",
    )
    if not _healthy(runs) or result.reasons == ("PARTIAL_FACTS_UNSAFE",):
        return result
    r18 = None
    if grade_agreement_policy is not None:
        from proofops.application.tagging.grade_required_agreement_policy import (
            GradeRequiredAgreementPolicy,
            assess_grade_required_facts,
        )

        policy = GradeRequiredAgreementPolicy(required)
        if grade_agreement_policy != policy.to_dict():
            raise ValueError("SC1_R18_POLICY_MISMATCH")
        guarded_replicas = []
        for run in runs:
            provider = json.loads(run.provider_response_json or "{}")
            origin = provider.get("saved_response_origin", {})
            guarded_replicas.append(
                dict(
                    replicate_id=run.replicate_id,
                    request_id=run.request.request_id,
                    provider_request_id=run.usage.provider_request_id,
                    context_sha256=canonical_hash(
                        dict(
                            packet=run.packet_sha256,
                            tenant=run.tenant_id,
                            run=run.run_id,
                            claim=run.claim_id,
                            graph=run.graph_sha256,
                            rule=run.rule_sha256,
                            model=run.model_sha256,
                            prompt=run.prompt_sha256,
                        )
                    ),
                    current_response_bound=not (
                        provider.get("response_reuse")
                        or origin.get("replay")
                        or origin.get("fresh_model_call") is False
                    ),
                    elements={
                        e.element_id: dict(
                            state=e.state,
                            binding="accepted"
                            if dict(run.binding_hashes).get(e.element_id)
                            else "unresolved",
                            binding_sha256=dict(run.binding_hashes).get(e.element_id),
                            source_refs=[asdict(r) for r in e.evidence_refs],
                            normalized_value=e.normalized_value,
                        )
                        for e in run.guarded.elements
                    },
                )
            )
        r18 = assess_grade_required_facts(
            guarded_replicas,
            required_element_ids=packet.to_dict()["allowed_elements"],
            claim_source_verified=True,
            policy=policy,
        )
    data = packet.to_dict()
    elements, facts = [], []
    for eid, names in MAPPINGS[data["track"]].items():
        votes = [next((e for e in r.guarded.elements if e.element_id == eid), None) for r in runs]
        positives = [(e, r) for e, r in zip(votes, runs, strict=True) if e and e.state == "present"]
        keys = {
            (e.normalized_value, dict(r.binding_hashes).get(eid), dict(r.source_scopes).get(eid))
            for e, r in positives
        }
        contrary = any(e and e.state in ("absent", "conflict") for e in votes)
        if contrary or len(keys) > 1:
            state = "conflict"
        elif (
            (
                r18 is None
                or (
                    r18["elements"][eid]["admitted"]
                    and all(r.startswith("GRADE_FACT_UNRESOLVED:") for r in r18["reasons"])
                )
            )
            and len(positives) >= required
            and len(keys) == 1
            and all(e and e.state in ("present", "unknown") for e in votes)
            and all(
                e.evidence_refs
                and dict(r.binding_hashes).get(eid)
                and all(ref.verification_state == "verified" for ref in e.evidence_refs)
                for e, r in positives
            )
        ):
            state = "present"
        else:
            state = "unknown"
        refs = (
            tuple(dict.fromkeys(ref for e, _ in positives for ref in e.evidence_refs))
            if state == "present"
            else ()
        )
        original = next((e for e in votes if e), None)
        if original:
            elements.append(
                replace(
                    original,
                    state=state,
                    evidence_refs=refs,
                    normalized_value=positives[0][0].normalized_value if refs else None,
                )
            )
        for name in names:
            facts.append(
                ConfirmedFact(
                    name,
                    state,
                    refs,
                    data["tenant_id"] if refs else None,
                    bool(refs),
                    bool(refs),
                    source_scope=dict(positives[0][1].source_scopes).get(eid, "local_claim")
                    if refs
                    else "local_claim",
                    normalized_value=positives[0][0].normalized_value if refs else None,
                )
            )
    # Reuse auxiliary trigger facts; they never inherit a lowered vote threshold.
    known = {f.name for f in facts}
    if result.confirmed_tags:
        facts.extend(f for f in result.confirmed_tags.facts if f.name not in known)
    ordered = sorted(runs, key=lambda r: r.replicate_id)
    first = ordered[0]
    tags = ConfirmedTags(
        data["tenant_id"],
        data["document_version_id"],
        data["claim_id"],
        data["track"],
        tuple(facts),
        revision,
        packet.packet_sha256,
        first.model_sha256,
        first.prompt_sha256,
        tuple(r.semantic_hash for r in ordered),
        pack.ontology_version,
        data.get("safe_harbor_category"),
        first.guarded.superlative_quote,
        first.product_variant,
    )
    return replace(result, candidate_elements=tuple(elements), confirmed_tags=tags)


def _healthy(runs):
    return (
        len(runs) == 3
        and all(
            r.guarded is not None
            and r.usage is not None
            and r.usage.status == "succeeded"
            and (r.synthetic or r.usage.provider_request_id)
            and not any(
                not e.startswith("UNRESOLVED:") and e != "DETERMINISTIC_CHECK_REQUIRED:P6"
                for e in r.errors
            )
            for r in runs
        )
        and len({r.usage.provider_request_id for r in runs}) == 3
    )


def confirmation_policy(required=3):
    return dict(
        profile="sc1_inventory_scope_v1",
        inventory_policy_sha256=INVENTORY_HASH,
        rule_policy_sha256=RULE_HASH,
        agreement=agreement_policy(required),
    )


def _normalize(value):
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def claim_key(context, graph):
    values = []
    for role in ATTRIBUTE_ROLES.values():
        ref = context.dimensions.get(role)
        if (
            ref is None
            or verify_source_ref(ref, graph, tenant_id=graph.tenant_id).verification_state
            != "verified"
        ):
            return None
        # Attributes must belong to the atomic claim, or its explicit source refs.
        if not any(
            r.source_id == ref.source_id
            and r.char_start <= ref.char_start < ref.char_end <= r.char_end
            for r in context.claim.source_refs
        ):
            return None
        values.append(_normalize(ref.quote))
    return tuple(values)


def _candidate_key(vote):
    attrs = vote["attributes"]
    if any(attrs.get(k) is None for k in ATTRIBUTE_ROLES):
        return None
    return tuple(_normalize(attrs[k]["quote"]) for k in ATTRIBUTE_ROLES)


class InventoryIndex:
    """Replayed once per run; deterministic exact attributes only (QT2 contract)."""

    def __init__(self, inventory, graph):
        self.inventory = replay_inventory(inventory, graph)
        self.graph = graph
        from proofops.application.tagging.cf1_inventory import absence_policy

        self.absence_agreement = absence_policy(self.inventory["selection"])
        self.by_element = {}
        for candidate in inventory["candidates"]:
            self.by_element.setdefault(candidate["element_id"], []).append(candidate)
        self.uncovered = {
            cue["element_id"] for c in inventory["chunks"] for cue in c["uncovered_cues"]
        }

    def state(self, element_id, key, required):
        original = self._unanimous_state(element_id, key, required)
        if self.absence_agreement is None or key is None:
            return original
        eligible = {1, 2, 3}
        contrary = []
        negative = False
        ids = set(original[2])
        for chunk in self.inventory["chunks"]:
            eligible.intersection_update(chunk["cf1_inspected_replicas"])
            for record in chunk["cf1_contrary_records"]:
                if record["element_id"] == element_id and _candidate_key(record) in (None, key):
                    contrary.append(record)
                    ids.add(record["candidate_id"])
        for candidate in self.by_element.get(element_id, []):
            votes = candidate["votes"]
            if all(_candidate_key(v) not in (None, key) for v in votes.values()):
                continue
            ids.add(candidate["candidate_id"])
            negative |= any(v["state"] == "not_applicable" for v in votes.values())
            for replica in tuple(eligible):
                vote = votes.get(str(replica))
                if vote is None or _candidate_key(vote) is None:
                    eligible.discard(replica)
                elif _candidate_key(vote) == key and vote["state"] != "not_applicable":
                    eligible.discard(replica)
        # Verified contrary evidence cannot be outvoted, including a verified
        # record from an otherwise invalid reply. Unanimous positives are kept.
        if original[0] == "conflict" or any(r["state"] == "conflict" for r in contrary):
            return "conflict", (), sorted(ids)
        if contrary and (
            negative or len(eligible) >= self.absence_agreement["required_absence_votes"]
        ):
            return "conflict", (), sorted(ids)
        if original[0] == "present":
            return original
        if len(eligible) >= self.absence_agreement["required_absence_votes"]:
            return "absent_in_scope", (), sorted(ids)
        return "unknown", (), sorted(ids)

    def _unanimous_state(self, element_id, key, required):
        if key is None:
            return "unknown", (), []
        positives, states, ids = [], [], []
        for candidate in self.by_element.get(element_id, []):
            votes = candidate["votes"]
            keys = {_candidate_key(v) for v in votes.values()}
            # Fully attributed other subjects/metrics/sites/periods cannot be borrowed.
            if None not in keys and key not in keys:
                continue
            ids.append(candidate["candidate_id"])
            if keys != {key}:
                states.append("unknown")
                continue
            values = [votes.get(str(i), {}).get("state", "unknown") for i in (1, 2, 3)]
            if "conflict" in values or ("present" in values and "not_applicable" in values):
                states.append("conflict")
            elif all(v == "not_applicable" for v in values):
                states.append("not_applicable")
            elif values.count("present") >= required and all(
                v in ("present", "unknown") for v in values
            ):
                states.append("present")
                positives.append(candidate["evidence_ref"])
            else:
                states.append("unknown")
        if "conflict" in states:
            return "conflict", (), ids
        if element_id in self.uncovered:
            return "unknown", (), ids
        # An unreadable/unresolved candidate can contradict an otherwise positive one.
        if "unknown" in states:
            return "unknown", (), ids
        if "present" in states:
            return "present", tuple(positives), ids
        return "absent_in_scope", (), ids


def analyze_scope(
    *,
    runs,
    packet,
    context,
    graph,
    rulepack,
    rule_context,
    inventory,
    prior_projection=None,
    tag_revision=1,
    required_present_votes=3,
    grade_agreement_policy=None,
    v1_activity_policy=None,
):
    policy = confirmation_policy(required_present_votes)
    if v1_activity_policy is not None:
        from proofops.application.tagging.v1_activity_links import validate_policy

        validate_policy(v1_activity_policy)
        if required_present_votes != 3:
            raise ValueError("V1_ACTIVITY_REQUIRES_THREE_REPLICAS")
        policy = policy | dict(v1_activity_links=v1_activity_policy)
    index = inventory if isinstance(inventory, InventoryIndex) else InventoryIndex(inventory, graph)
    if index.absence_agreement is not None:
        policy = policy | dict(cf1_absence_agreement=index.absence_agreement)
    data, selected = packet.to_dict(), index.inventory["selection"]
    if (
        selected["run_id"],
        selected["tenant_id"],
        selected["document_version_id"],
        selected["graph_sha256"],
        context.claim.claim_id,
    ) != (
        data["run_id"],
        data["tenant_id"],
        data["document_version_id"],
        data["graph_sha256"],
        data["claim_id"],
    ):
        raise ValueError("SC1_RUN_PACKET_MISMATCH")
    if canonical_hash(asdict(graph)) != selected["graph_sha256"]:
        raise ValueError("SC1_GRAPH_MISMATCH")
    scope = selected | dict(
        inspected_pages=[
            p["physical_page"] for p in index.inventory["pages"] if p["status"] == "inspected"
        ],
        uninspected_pages=[
            p["physical_page"] for p in index.inventory["pages"] if p["status"] != "inspected"
        ],
        inspected_block_count=sum(
            p["block_count"] for p in index.inventory["pages"] if p["status"] == "inspected"
        ),
        inventory_sha256=index.inventory["inventory_sha256"],
        rule_policy_sha256=RULE_HASH,
        confirmation_policy_sha256=canonical_hash(policy),
        agreement_policy=policy["agreement"],
    )
    consensus = _consensus(
        runs, packet, rulepack, tag_revision, required_present_votes, grade_agreement_policy
    )
    tags = consensus.confirmed_tags
    v1_links = None
    base_rulepack = rulepack
    if v1_activity_policy is not None:
        from proofops.application.tagging.v1_activity_links import (
            effective_rulepack,
            link_inventory,
        )

        v1_links = link_inventory(
            context,
            index,
            graph,
            run_id=data["run_id"],
            tenant_id=data["tenant_id"],
            rulepack=rulepack,
            policy=v1_activity_policy,
        )
    reasons, searches, decision = [], [], None
    if not scope["selected_pages"] or scope["uninspected_pages"]:
        reasons.append("SC1_UNINSPECTED_PAGES")
    if not _healthy(runs) or tags is None:
        reasons.append("SC1_BASE_REPLICAS_UNRESOLVED")
    if context.claim.source_quality != "verified" or any(
        verify_source_ref(r, graph, tenant_id=graph.tenant_id).verification_state != "verified"
        for r in context.claim.source_refs
    ):
        reasons.append("SC1_CLAIM_SOURCE_UNVERIFIED")
    if prior_projection and prior_projection.get("grade_basis") in {
        "estimate_hold",
        "retag_required",
        "scope3_calculation_hold",
    }:
        reasons.append("SC1_EXISTING_SAFETY_HOLD")
    if tags and (tags.safe_harbor_category or tags.superlative_quote or tags.product_variant):
        reasons.append("SC1_EXCEPTION_REVIEW_REQUIRED")
    raw_contrary = False
    for run in runs:
        try:
            raw = llm_tags_from_dict(json.loads(run.raw_response_json))
            raw_contrary |= any(e.state in ("absent", "conflict") for e in raw.elements)
        except (ValueError, TypeError):
            raw_contrary = True
    if raw_contrary or (tags and any(f.state == "conflict" for f in tags.facts)):
        reasons.append("SC1_CONFLICT")
    key = claim_key(context, graph)
    if key is None:
        reasons.append("SC1_CLAIM_ATTRIBUTES_UNRESOLVED")
    elif any(
        index.state(eid, key, required_present_votes)[0] == "conflict"
        for eid in MAPPINGS[data["track"]]
    ):
        reasons.append("SC1_INVENTORY_CONFLICT")
    if tags and any(
        ref.page_num not in scope["selected_pages"]
        or verify_source_ref(ref, graph, tenant_id=graph.tenant_id).verification_state != "verified"
        for fact in tags.facts
        if fact.state == "present"
        for ref in fact.evidence_refs
    ):
        reasons.append("SC1_POSITIVE_SOURCE_OUTSIDE_SCOPE_OR_UNVERIFIED")
    if index.inventory["synthetic"] and not rule_context.local_synthetic:
        reasons.append("SC1_SYNTHETIC_INVENTORY_NOT_PUBLIC")
    if any(r.synthetic for r in runs) and not rule_context.local_synthetic:
        reasons.append("SC1_SYNTHETIC_TAGS_NOT_PUBLIC")
    if v1_links is not None and v1_links["unresolved_elements"]:
        reasons.append("V1_ACTIVITY_INVENTORY_UNRESOLVED")
    if v1_links is not None and any(
        link["element"]["element_id"] in index.uncovered for link in v1_links["links"]
    ):
        reasons.append("V1_ACTIVITY_UNCOVERED_CUES")
    # New positives are facts from the retained inventory, not fabricated claim
    # replicas. Keep raw claim votes immutable and every existing safety hold.
    # Unresolved absence keys do not invalidate a fully attributed positive link.
    positive_holds = [r for r in reasons if r != "SC1_CLAIM_ATTRIBUTES_UNRESOLVED"]
    if v1_links is not None and tags and tags.track == "management" and not positive_holds:
        linked = {f.name: f for f in tags.facts}
        for link in v1_links["links"]:
            eid = link["element"]["element_id"]
            names = MAPPINGS[tags.track][eid]
            if any(linked[name].state != "unknown" for name in names):
                continue
            # A competing unresolved/contrary inventory candidate is still a hold.
            if key is not None and index.state(eid, key, 3)[0] == "conflict":
                continue
            refs = tuple(SourceRef(**r) for r in link["element"]["evidence_refs"])
            for name in names:
                linked[name] = ConfirmedFact(
                    name,
                    "present",
                    refs,
                    graph.tenant_id,
                    True,
                    True,
                    source_scope=link["source_scope"],
                )
        tags = replace(tags, facts=tuple(linked.values()))
        rulepack = effective_rulepack(rulepack)
    base = evaluate(tags, rule_context, rulepack) if tags else None
    facts = {f.name: f for f in tags.facts} if tags else {}
    if base and base.grade_floor and base.grade_floor > "E0" and not reasons:
        for eid in base.grade_open_elements:
            names = MAPPINGS[tags.track][eid]
            if any(facts[n].state != "unknown" for n in names):
                continue
            state, refs, ids = index.state(eid, key, required_present_votes)
            reason = None
            if state == "absent_in_scope" and any(
                e.element_id == eid and e.state == "present"
                for run in runs
                if run.guarded
                for e in run.guarded.elements
            ):
                state, reason = "unknown", "SC1_PARTIAL_POSITIVE_BLOCKS_ABSENCE"
            if state == "present":
                # Use the existing binding boundary. QT2 can reuse the inventory;
                # SC1 does not change its general retrieval/linking implementation.
                from proofops.application.evidence.binding import accept_binding

                accepted = []
                scopes = set()
                for ref_dict in refs:
                    ref = SourceRef(**ref_dict)
                    candidate = next(
                        c for c in index.by_element[eid] if c["evidence_ref"] == ref_dict
                    )
                    vote = next(v for v in candidate["votes"].values() if v["state"] == "present")
                    roles = {
                        ATTRIBUTE_ROLES[k]: SourceRef(**v)
                        for k, v in vote["attributes"].items()
                        if v
                    }
                    # Assurance coverage and deterministic consistency cannot be
                    # manufactured by a semantic inventory record.
                    if (
                        eid in ("P4", "P6")
                        or accept_binding(
                            context,
                            ref,
                            roles,
                            original=graph,
                            tenant_id=graph.tenant_id,
                            rulepack=rulepack,
                            element_id=eid,
                        )
                        != "accepted"
                    ):
                        continue
                    accepted.append(ref)
                    local = any(
                        r.source_id == ref.source_id
                        and r.char_start <= ref.char_start
                        and ref.char_end <= r.char_end
                        for r in context.claim.source_refs
                    )
                    scopes.add(
                        "local_claim"
                        if local
                        else "same_table"
                        if any(
                            b.source_id == ref.source_id and b.kind == "table_cell"
                            for b in graph.blocks
                        )
                        else "global_bound"
                    )
                if len(accepted) != len(refs) or len(scopes) != 1:
                    state, reason = "unknown", "SC1_POSITIVE_BINDING_REQUIRED"
                else:
                    for name in names:
                        facts[name] = ConfirmedFact(
                            name,
                            "present",
                            tuple(accepted),
                            graph.tenant_id,
                            True,
                            True,
                            source_scope=next(iter(scopes)),
                        )
            if state != "present":
                for name in names:
                    facts[name] = replace(facts[name], state=state)
            searches.append(
                dict(
                    element_id=eid,
                    previous_state="unknown",
                    state=state,
                    candidate_ids=ids,
                    reason=reason,
                    inventory_sha256=scope["inventory_sha256"],
                )
            )
    elif not reasons:
        reasons.append("SC1_VERIFIED_LOWER_BOUND_REQUIRED")
    fully_linked = (
        v1_links is not None
        and base
        and base.decision_status == "decided"
        and not positive_holds
        and v1_links["links"]
        and not any(link["element"]["element_id"] in index.uncovered for link in v1_links["links"])
    )
    if fully_linked:
        reasons = [r for r in reasons if r != "SC1_CLAIM_ATTRIBUTES_UNRESOLVED"]
    body = dict(
        schema=SCHEMA,
        policy=policy,
        policy_sha256=canonical_hash(policy),
        scope=scope,
        claim_id=context.claim.claim_id,
        packet_sha256=packet.packet_sha256,
        base_replicate_hashes=[r.semantic_hash for r in sorted(runs, key=lambda r: r.replicate_id)],
        tag_revision=tag_revision,
        searches=searches,
        reasons=reasons,
        prior_projection_sha256=canonical_hash(prior_projection),
    )
    if grade_agreement_policy is not None:
        body["grade_required_agreement_policy"] = grade_agreement_policy
        body["grade_required_agreement_policy_sha256"] = canonical_hash(grade_agreement_policy)
    if v1_links is not None:
        body.update(
            v1_activity_links=v1_links,
            v1_base_rulepack_sha256=base_rulepack.sha256,
            v1_effective_rulepack=asdict(rulepack),
            v1_projection=base.to_api_dict() if base else None,
        )
    receipt_hash = canonical_hash(body)
    absent = [f.name for f in facts.values() if f.state == "absent_in_scope"]
    if absent and not reasons and not any(f.state == "conflict" for f in facts.values()):
        scoped = replace(tags, facts=tuple(facts.values()))
        decision = evaluate_scope(
            scoped,
            rule_context,
            rulepack,
            scope=scope,
            absent_facts=absent,
            receipt_sha256=receipt_hash,
        )
        if decision.decision_status != "decided":
            decision = None
    elif fully_linked:
        from proofops.application.tagging.v1_activity_links import confirmed_decision

        decision = confirmed_decision(base, scope, receipt_hash)
    return body | dict(
        receipt_sha256=receipt_hash,
        sc1_confirmation=decision.to_api_dict() if decision else None,
        sc1_elements=[
            dict(
                element_id=eid,
                state=(
                    "conflict"
                    if any(facts[n].state == "conflict" for n in names)
                    else "absent_in_scope"
                    if any(facts[n].state == "absent_in_scope" for n in names)
                    else "present"
                    if all(facts[n].state == "present" for n in names)
                    else "unknown"
                ),
                inventory_sha256=scope["inventory_sha256"],
            )
            for eid, names in MAPPINGS[data["track"]].items()
        ]
        if facts
        else [],
    )


def replay_scope(receipt, **inputs):
    expected = analyze_scope(
        **inputs,
        tag_revision=receipt["tag_revision"],
        required_present_votes=receipt["policy"]["agreement"]["required_present_votes"],
        grade_agreement_policy=receipt.get("grade_required_agreement_policy"),
        v1_activity_policy=receipt["policy"].get("v1_activity_links"),
    )
    if canonical_hash(expected) != canonical_hash(receipt):
        raise ValueError("SC1_REPLAY_MISMATCH")
    return expected


def read_runs(values):
    """Decode retained TagRuns without relabeling responses or request identities."""
    from proofops.adapters.cache.aws import CacheNamespace, CacheRequest
    from proofops.application.budget import TokenUsage
    from proofops.application.tagging.service import TagRun

    return tuple(
        TagRun(
            **(
                r
                | dict(
                    request=CacheRequest(
                        **(
                            r["request"]
                            | dict(namespace=CacheNamespace(**r["request"]["namespace"]))
                        )
                    ),
                    usage=TokenUsage(**r["usage"]) if r["usage"] else None,
                    guarded=llm_tags_from_dict(r["guarded"]) if r["guarded"] else None,
                    errors=tuple(r["errors"]),
                    source_scopes=tuple(map(tuple, r["source_scopes"])),
                    binding_hashes=tuple(map(tuple, r["binding_hashes"])),
                )
            )
        )
        for r in values
    )


def analyze_record(
    record,
    claim,
    graph,
    rulepack,
    inventory,
    *,
    required_present_votes,
    local_synthetic,
    grade_agreement_policy=None,
    v1_activity_policy=None,
):
    from proofops.application.evidence.binding import ClaimContext
    from proofops.application.evidence.retrieval import freeze_packet
    from proofops.domain.rules.engine import RuleContext
    from proofops.domain.values import SourceRef

    data = {k: v for k, v in record["frozen_packet"].items() if k != "packet_sha256"}
    packet = freeze_packet(data)
    context = ClaimContext(
        claim, {k: SourceRef(**v) if v else None for k, v in record["sc1_dimensions"].items()}
    )
    rule_context = RuleContext(
        claim.tenant_id,
        claim.document_version_id,
        claim.claim_id,
        packet.packet_sha256,
        local_synthetic=local_synthetic,
    )
    return analyze_scope(
        runs=read_runs(record["tag_runs"]),
        packet=packet,
        context=context,
        graph=graph,
        rulepack=rulepack,
        rule_context=rule_context,
        inventory=inventory,
        prior_projection=record["provisional_grade"],
        required_present_votes=required_present_votes,
        grade_agreement_policy=grade_agreement_policy,
        v1_activity_policy=v1_activity_policy,
    )
