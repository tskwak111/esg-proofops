"""C4 general direct-system certification; C2/C3 readers remain frozen.

Discovery nominates exact paragraph spans. Independently extracted facts are
verified and bound before the unchanged Python rules can decide or publish.
"""

import re
from dataclasses import asdict

from jsonschema import Draft202012Validator
from proofops.application.evidence.binding import accept_binding
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.tagging.fact_assembly_c2 import (
    ELEMENTS,
    SCHEMA,
    TRIGGERS,
    _receipt,
    vote_schema,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import ConfirmedFact, ConfirmedTags, RuleContext, evaluate
from proofops.domain.values import SourceRef, _require_sha256

PROFILE = "management-direct-certification-c4-v1"
SYSTEMS = {"14001": "환경경영시스템", "50001": "에너지경영시스템", "45001": "안전보건경영시스템"}
ISO = re.compile(r"ISO\s*(14001|50001|45001)", re.I)
POSSESSION = re.compile(
    r"인증(?:을?\s*(?:통해 제3자 검증을 받고|완료|취득|획득|유지|보유)|받|을 받)"
)
NEGATIVE = re.compile(r"부합|예정|미취득|미인증|철회|취소|진행\s*중|계획|추진|준비")
SCOPE = re.compile(
    r"국내|글로벌|전사|(?:전|모든|주요|\d+개)\s*(?:생산\s*)?사업장|[가-힣A-Za-z]+\s*(?:공장|오피스|캠퍼스)|데이터센터"
)
POLICY = dict(
    profile=PROFILE,
    enabled=True,
    approval="C4 task; DEC-25/DEC-43 and R8 guards",
    authority="raw_guarded_and_independent_derived_3_of_3",
    scope="same_paragraph_same_named_system_direct_certification_with_complete_explicit_scope",
    systems=SYSTEMS,
    period="explicit_current_or_same_page_disclosure_context",
    boundary="each_replica_complete_scope; no_facility_period_opinion_union",
    source="exact_native_glyph_and_rendered_span; no_parent_promotion",
    guard="negative_possession;activity_entity_product;partial_scope;validity;conflict;footnote",
    rollback="stop_new_C4; retain_C2_C3_C4_readers_and_immutable_revisions",
    vote_schema_sha256=canonical_hash(vote_schema()),
)
POLICY_HASH = canonical_hash(POLICY)


def _plain(text):
    return re.sub(r"\s+", " ", text).strip()


def safety_reasons(quote):
    reasons = []
    if not POSSESSION.search(quote):
        reasons.append("CERTIFICATION_POSSESSION_UNRESOLVED")
    if NEGATIVE.search(quote):
        reasons.append("CERTIFICATION_NONPOSSESSION_OR_PLAN")
    if not any(system in quote for system in SYSTEMS.values()):
        reasons.append("CERTIFICATION_SYSTEM_NOT_DIRECTLY_NAMED")
    if re.search(r"제품|교육|연수|정책\s*개정|방침\s*수립", quote):
        reasons.append("OTHER_ACTIVITY_ENTITY_PRODUCT_REQUIRES_REVIEW")
    if re.search(r"유효기간|만료|유효하|유효한", quote):
        reasons.append("CERTIFICATION_VALIDITY_NOT_ESTABLISHED")
    if re.search(r"\d+\)|[*†‡]", quote):
        reasons.append("SCOPE_FOOTNOTE_REQUIRES_REVIEW")
    if re.search(r"세계 최초|업계 최고|보상|이사회|담당조직|전담조직", quote):
        reasons.append("CONDITIONAL_OR_SUPERLATIVE_REVIEW")
    counts = re.search(r"(?:총\s*)?(\d+)개\s*(?:생산\s*)?사업장\s*중\s*(\d+)개", quote)
    if (
        counts
        and int(counts[2]) < int(counts[1])
        and re.search(
            r"(?:글로벌|전 세계|국내외).{0,12}(?:전|전체|모든)\s*(?:생산\s*)?사업장", quote
        )
    ):
        reasons.append("PARTIAL_SCOPE_EXPANDED")
    return sorted(set(reasons))


def discover(graph):
    """Nominations only; same original paragraph, never source approval or a grade."""
    found = []
    for block in graph.blocks:
        if block.kind != "paragraph" or block.winner is None:
            continue
        text = block.normalized_text
        spans = [
            (m.start(), m.end(), m.group().strip()) for m in re.finditer(r"[^.]+(?:\.|$)", text)
        ]
        for idx, (start, end, sentence) in enumerate(spans):
            if not POSSESSION.search(sentence) or NEGATIVE.search(sentence):
                continue
            # Two linked sentences may name a system first, then its certification.
            first = idx
            if not ISO.search(sentence) or not any(s in sentence for s in SYSTEMS.values()):
                if idx == 0:
                    continue
                # The certification sentence must explicitly repeat its system
                # or standard. Paragraph adjacency alone supplies no ownership.
                if not ISO.search(sentence) and not any(s in sentence for s in SYSTEMS.values()):
                    continue
                first = idx - 1
            begin, _, _ = spans[first]
            combined = text[begin:end].strip()
            iso = ISO.search(combined)
            if not iso or SYSTEMS[iso[1]] not in combined:
                continue
            system = SYSTEMS[iso[1]]
            if len({m[1] for m in ISO.finditer(combined)}) != 1:
                continue
            scope_sentence = sentence if SCOPE.search(sentence) else None
            if scope_sentence is None and idx + 1 < len(spans):
                _, next_end, next_sentence = spans[idx + 1]
                if (
                    SCOPE.search(next_sentence)
                    and POSSESSION.search(next_sentence)
                    and (ISO.search(next_sentence) or system in next_sentence)
                ):
                    end, scope_sentence = next_end, next_sentence
            if scope_sentence is None:
                continue
            quote = text[begin:end].strip()
            if safety_reasons(quote):
                continue
            begin = text.index(quote, begin)
            item = dict(
                source_id=block.source_id,
                physical_page=block.page_num,
                char_start=begin,
                char_end=begin + len(quote),
                quote=quote,
                certificate="ISO " + iso[1],
                system=system,
                certification_quote=combined,
                scope_quote=scope_sentence,
            )
            # A following scope sentence can itself contain a possession verb;
            # retain one atomic nomination per overlapping statement.
            if not any(
                f["source_id"] == item["source_id"]
                and f["char_start"] <= item["char_start"] < f["char_end"]
                for f in found
            ):
                found.append(item)
    return found


def assemble(votes, *, context, graph, packet, rulepack, tag_revision=1):
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
        raise ValueError("C4_ASSEMBLY_IDENTITY_MISMATCH")
    candidate = data.get("c4_candidate")
    if candidate not in discover(graph) or claim.quote != candidate["quote"]:
        raise ValueError("C4_FROZEN_CANDIDATE_MISMATCH")
    if any(
        type(v.get("replicate_id")) is not int
        or type(v.get("simulated")) is not bool
        or not isinstance(v.get("provider"), str)
        or not v["provider"]
        for v in votes
    ):
        raise ValueError("C4_PROVENANCE_TYPE_INVALID")
    ordered = sorted(votes, key=lambda v: v["replicate_id"])
    if len(ordered) != 3 or [v["replicate_id"] for v in ordered] != [1, 2, 3]:
        raise ValueError("C4_INDEPENDENT_REPLICAS_REQUIRED")
    for field in ("request_id", "request_sha256", "provider_request_id"):
        if len({v.get(field) for v in ordered}) != 3 or any(not v.get(field) for v in ordered):
            raise ValueError("C4_RESPONSE_REPLAY")
    if (
        len(
            {
                (v["model_sha256"], v["prompt_sha256"], v["provider"], v["simulated"])
                for v in ordered
            }
        )
        != 1
    ):
        raise ValueError("C4_MODEL_PROMPT_PROVIDER_MISMATCH")
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
                raise ValueError("C4_PROVIDER_SCOPE_MISMATCH")
            _require_sha256("response_sha256", v.get("response_sha256"))
        Draft202012Validator(vote_schema()).validate(v["raw"])
        if (
            v.get("identity") != identity
            or v.get("raw_sha256") != canonical_hash(v["raw"])
            or v.get("vote_sha256")
            != canonical_hash({k: x for k, x in v.items() if k != "vote_sha256"})
        ):
            raise ValueError("C4_RAW_RECEIPT_MISMATCH")
    refs = {str(i): SourceRef(**r) for i, r in enumerate(data["c4_sources"])}
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
                not re.search(
                    r"지속가능(?:성|경영)?\s*보고서|Sustainability\s*Report",
                    block.normalized_text,
                    re.I,
                )
                or re.search(r"참고|인용|전년|previous", block.normalized_text, re.I)
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
            state = (
                "present"
                if ref and binding == "accepted"
                else ("conflict" if value.get("state") == "conflict" else "unknown")
            )
            if state == "present":
                contained = any(
                    c.source_id == ref.source_id
                    and c.char_start <= ref.char_start < ref.char_end <= c.char_end
                    for c in claim_refs
                )
                expected = data["c4_candidate"]
                if not contained:
                    state = "unknown"
                    reasons.append("ELEMENT_OUTSIDE_ATOMIC_ACTIVITY:" + eid)
                elif eid == "M3" and (
                    safety_reasons(ref.quote)
                    or not any(
                        "ISO " + m[1] == expected["certificate"] for m in ISO.finditer(ref.quote)
                    )
                    or expected["system"] not in ref.quote
                    or _plain(expected["certification_quote"]) not in _plain(ref.quote)
                ):
                    state = "unknown"
                    reasons.append("DIRECT_CERTIFICATION_ACTIVITY_UNRESOLVED")
                elif eid == "M2" and _plain(expected["scope_quote"]) not in _plain(ref.quote):
                    state = "unknown"
                    reasons.append("BOUNDARY_SCOPE_INCOMPLETE")
                elif eid == "M1" and expected["system"] not in ref.quote:
                    state = "unknown"
                    reasons.append("NAMED_SYSTEM_UNRESOLVED")
                elif eid == "M4" and not POSSESSION.search(ref.quote):
                    state = "unknown"
                    reasons.append("CONCRETE_CERTIFICATION_IMPLEMENTATION_UNRESOLVED")
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
                else ConfirmedFact(primitive, state)
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
        if boundary_value:
            boundary_value = _plain(data["c4_candidate"]["scope_quote"])
        activity_value = (
            data["c4_candidate"]["system"]
            if dims["activity"] and data["c4_candidate"]["system"] in dims["activity"].quote
            else None
        )
        if activity_value is None:
            reasons.append("ACTIVITY_NOT_NAMED_SYSTEM")
        reasons.extend(safety_reasons(claim.quote))
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
            public_auto_confirmed=bool(
                eligible
                and not any(v["simulated"] for v in ordered)
                and not any(c.synthetic for c in graph.candidates)
                and rulepack.status == "active"
                and rulepack.approved_by
                and rulepack.approved_at
            ),
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
        raise ValueError("C4_ASSEMBLY_RECEIPT_MISMATCH")
    result = assemble(receipt["raw_receipts"], **inputs)
    if result.to_dict() != receipt:
        raise ValueError("C4_ASSEMBLY_REPLAY_MISMATCH")
    return result


def publication_policy_for(profile, *, pinned_hash=None):
    if profile != PROFILE or pinned_hash not in (None, POLICY_HASH):
        raise ValueError("C4_PUBLICATION_PROFILE_MISMATCH")
    return dict(POLICY)


def publication_values(receipt, *, rulepack, tag_revision):
    # This builder is policy-independent; C4 replay validates its authority first.
    from proofops.application.tagging.fact_assembly_c3 import publication_values as values

    return values(receipt, rulepack=rulepack, tag_revision=tag_revision)


def validate_publication(inputs):
    if inputs.fact_assembly_receipt is None:
        raise ValueError("C4_PUBLICATION_RECEIPT_REQUIRED")
    receipt = replay(
        inputs.fact_assembly_receipt.to_dict(),
        context=inputs.context,
        graph=inputs.original,
        packet=inputs.packet,
        rulepack=inputs.rulepack,
        tag_revision=inputs.tag_revision,
    ).to_dict()
    consensus, decision = publication_values(
        receipt, rulepack=inputs.rulepack, tag_revision=inputs.tag_revision
    )
    if (
        inputs.consensus != consensus
        or inputs.decision != decision
        or inputs.tag_runs
        or inputs.rule_context.local_synthetic
        or inputs.fact_assembly_profile != PROFILE
        or inputs.rule_context.packet_sha256 != inputs.packet.packet_sha256
        or inputs.run_id != inputs.packet.to_dict()["run_id"]
        or inputs.packet.to_dict()["retrieval_packet_sha256"]
        != inputs.original_packet.packet_sha256
        or asdict(evaluate(consensus.confirmed_tags, inputs.rule_context, inputs.rulepack))
        != asdict(decision)
    ):
        raise ValueError("C4_PUBLICATION_INPUT_MISMATCH")


def confirmation_display(receipt):
    if not receipt["public_auto_confirmed"]:
        raise ValueError("C4_PUBLICATION_NOT_ELIGIBLE")
    result = receipt["derived_results"][0]["result"]
    refs = result["elements"]["M3"]["source_refs"]
    system = next(s for s in SYSTEMS.values() if s in refs[0]["quote"])
    certificate = "ISO " + ISO.search(refs[0]["quote"])[1]
    scope = result["elements"]["M2"]["source_refs"][0]["quote"]
    period = result["dimensions"]["period"]
    kind = "보고서 문맥" if result["period_kind"] == "report_context" else "본문 명시 연도"
    return (
        "자동 확정 E3 · SUBSTANTIATED — 프로젝트 루브릭상 공시 내 입증요소 충족. "
        f"{system}의 {certificate} 직접 인증과 적용범위({scope})를 "
        f"p{refs[0]['page_num']}에서 확인. "
        f"{kind}: {period['quote']}; 인증 유효기간: 미기재."
    )
