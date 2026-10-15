"""Opt-in, source-bound contextual elements; never create semantic votes.

Adjacent prose is proposed only inside one canonical paragraph. Admission needs
an explicit shared activity and all asserted dimensions; proximity is not proof.
Cross-page sources keep the existing explicit-link/attribution review path.
"""

import re
from dataclasses import asdict, replace

from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.ingest.k5_context import BULLET, TERMINAL
from proofops.domain.provenance import canonical_hash

GUIDANCE = """
QT2: P2 compares the current observation with an earlier/base-year value in the
SAME verified table row. Select the comparison value AND its year header IDs;
normalized_value is the exact comparison value quote, not the reporting year or
a paraphrase. A stored comparison is a candidate, never an automatic present.
M2 is the organizations/facilities actually covered by the cited activity.
Regulator names (EPA/ECHA/환경부), consultation partners, and '전사 전략과 연계'
are not an operating boundary. Keep limited/main-site qualifiers and footnotes.
M4 includes concrete performed or recurring actions (internal audits, monthly
monitoring, installed equipment), even without a reduction amount or event date.
General will, environmental services/campaigns with no named action or result,
and plans alone are insufficient. Select the literal subject/action context.
For neighboring sentences use only citable catalog sources from the same
paragraph with the same activity, entity, facility and period; a different topic,
site or year cannot fill the gap. Other pages require explicit source references
and full attribution. Display-only metric paths and interpretation are not proof.
Do not infer missing actors/dates, present from metadata, or absent from unknown.
Conflict/unreadable stay held. Only Python computes grades; new votes require
three independent replicas over the same frozen packet.
""".strip()
POLICY = dict(
    profile="qt2-contextual-elements-v1",
    guidance_sha256=canonical_hash(GUIDANCE),
    elements=["P2", "M2", "M4"],
    prose="verified-same-paragraph-nearest-two-sentences; shared-explicit-activity",
    attribution="all-asserted-axes; no-period-facility-or-entity-substitution",
    table="same-attested-row-comparison-value-and-year; model-selection-required",
    cross_page="no-new-admission; existing-explicit-reference-guards",
    rejection="unknown; preserve-raw-votes-and-conflict",
)
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?:년)?(?!\d)")
_REGULATOR = re.compile(r"\b(?:EPA|ECHA)\b|환경부|지방환경관서|행정기관", re.I)
_BOUNDARY = re.compile(
    r"사업장|공장|데이터센터|법인|자회사|계열사|부문|사업부|사업본부|전사|그룹"
    r"|(?:임직원|직원|이사)\S*\s*대상"
)
_ACTOR = re.compile(r"위원회|이사회|전담조직|대표이사")
_ASPIRATIONAL_BOUNDARY = re.compile(r"(?:안전한|친환경|지속가능한)\s*사업장")
_GENERIC = re.compile(
    r"노력|의지|추진할|계획|예정|서비스와\s*캠페인|서비스\s*및\s*캠페인|환경적?\s*가치.{0,15}창출|^창출하고\s*있습니다[.]?$"
)
_CONCRETE = re.compile(
    r"(?:심사|점검|모니터링|설치|구축|적용|도입|실시|운영|갱신|가입|취득|보고|공유|책정)"
    r".{0,16}(?:했|하였|하고\s*있|합니다|합니|중|완료)|\d+\s*(?:명|회|건|개)|매년|월\s*단위"
)

POLICY.update(
    negative_patterns=dict(
        regulator=_REGULATOR.pattern,
        boundary=_BOUNDARY.pattern,
        actor=_ACTOR.pattern,
        aspirational_boundary=_ASPIRATIONAL_BOUNDARY.pattern,
        generic=_GENERIC.pattern,
        concrete=_CONCRETE.pattern,
    ),
    inventory="element-evidence-inventory-sc1-v1; replay-required; exact-four-axes; three-votes",
    local_m4="same-verified-atomic-span; asserted-roles-checked; no-date-inference",
)
POLICY_HASH = canonical_hash(POLICY)


def validate_policy(policy):
    if policy != POLICY:
        raise ValueError("QT2_CONTEXT_POLICY_MISMATCH")


def guard(element):
    """Negative semantic checks only, scoped to model-selected evidence."""
    if element.state != "present" or element.element_id not in ("M2", "M4"):
        return element
    text = " ".join(" ".join(r.quote.split()) for r in element.evidence_refs)
    reason = None
    if element.element_id == "M2" and (
        ((_REGULATOR.search(text) or _ACTOR.search(text)) and not _BOUNDARY.search(text))
        or (
            _ASPIRATIONAL_BOUNDARY.search(text)
            and re.search(r"전략과제|비전|지향", text)
            and not _BOUNDARY.search(_ASPIRATIONAL_BOUNDARY.sub("", text))
        )
        or (
            re.search(r"전사\s*전략", text)
            and not _BOUNDARY.search(re.sub(r"전사\s*전략", "", text))
        )
    ):
        reason = "QT2_M2_REGULATOR_OR_STRATEGY_NOT_BOUNDARY"
    if (
        element.element_id == "M4"
        and (_GENERIC.search(text) or ("감독" in text and "의사결정" in text))
        and not _CONCRETE.search(text)
    ):
        reason = "QT2_M4_GENERAL_INTENT_NOT_IMPLEMENTATION"
    return (
        replace(
            element, state="unknown", normalized_value=None, credited_from=None, reason_code=reason
        )
        if reason
        else element
    )


def _contains(outer, inner):
    return outer.source_id == inner.source_id and (
        outer.char_start <= inner.char_start < inner.char_end <= outer.char_end
    )


def context_refs(claim, graph, *, tenant_id):
    """Propose only individually verified sentences, without promoting a block."""
    if (
        claim.tenant_id != tenant_id
        or tenant_id != graph.tenant_id
        or (claim.source_quality != "verified" or len(claim.source_refs) != 1)
    ):
        return ()
    focal = claim.source_refs[0]
    if verify_source_ref(focal, graph, tenant_id=tenant_id).verification_state != "verified":
        return ()
    block = next((b for b in graph.blocks if b.source_id == focal.source_id), None)
    if block is None or block.kind != "paragraph" or block.winner is None:
        return ()
    # Never bridge bullets, blank-line paragraphs, or a different canonical block.
    limits = [0, *[m.start() for m in re.finditer(BULLET, block.raw_text)], len(block.raw_text)]
    lower = max(p for p in limits if p <= focal.char_start)
    upper = min(p for p in limits if p >= focal.char_end)
    cuts = [
        lower,
        *[lower + m.end() for m in re.finditer(TERMINAL, block.raw_text[lower:upper])],
        upper,
    ]
    segments = [(a, b) for a, b in zip(cuts, cuts[1:]) if a < b]
    selected = [
        i for i, (a, b) in enumerate(segments) if a < focal.char_end and focal.char_start < b
    ]
    if not selected:
        return ()
    refs = []
    for a, b in segments[max(0, min(selected) - 2) : max(selected) + 3]:
        while a < b and block.raw_text[a].isspace():
            a += 1
        while b > a and block.raw_text[b - 1].isspace():
            b -= 1
        if a == b or b - a > 2000:
            continue
        ref = replace(
            focal,
            char_start=a,
            char_end=b,
            quote=block.raw_text[a:b],
            verification_state="candidate",
        )
        checked = verify_source_ref(ref, graph, tenant_id=tenant_id)
        if checked.verification_state == "verified":
            refs.append(checked)
    return tuple(refs)


def augment_packet(data, claim, graph, *, tenant_id):
    data["qt2_contextual_elements_policy"] = POLICY
    elements = [e for e in ("M2", "M4") if e in data["allowed_elements"]]
    if not elements:
        return data
    for ref in context_refs(claim, graph, tenant_id=tenant_id):
        candidate = next(
            (c for c in data["evidence_candidates"] if c["source_id"] == ref.source_id), None
        )
        if candidate is None:
            candidate = dict(
                source_id=ref.source_id,
                source_scope="local_claim",
                allowed_elements=elements[:],
                source_refs=[],
            )
            data["evidence_candidates"].append(candidate)
        candidate["allowed_elements"] = list(
            dict.fromkeys([*candidate["allowed_elements"], *elements])
        )
        if asdict(ref) not in candidate["source_refs"]:
            candidate["source_refs"].append(asdict(ref))
    return data


def accepts_context(context, ref, graph, *, tenant_id, element_id, relation_tags=None):
    """Literal local identity or explicit activity continuity, never a vote.

    For a local M4 action null dimensions remain null, as for intrinsic M1.
    Neighboring sentences require a non-null shared metric/activity. Every
    asserted role must still verify locally; dates/sites cannot be borrowed.
    """
    claim = context.claim
    if element_id not in ("M2", "M4") or claim.source_quality != "verified":
        return False
    if len(claim.source_refs) != 1 or (claim.tenant_id, graph.tenant_id) != (tenant_id, tenant_id):
        return False
    focal = claim.source_refs[0]
    if any(
        verify_source_ref(r, graph, tenant_id=tenant_id).verification_state != "verified"
        for r in (focal, ref)
    ):
        return False
    local = _contains(focal, ref)
    if local and element_id != "M4":
        return False  # M2's existing stricter local scope admission remains.
    if not local and not any(
        _contains(r, ref) for r in context_refs(claim, graph, tenant_id=tenant_id)
    ):
        return False
    if not local:
        entity = context.dimensions.get("entity")
        if entity is None:
            return False
        activity = context.dimensions.get("metric")
        if activity is None or len(activity.quote.strip()) < 3 or activity.quote not in ref.quote:
            return False
        # Explicit repeated actor, or the activity itself as the continuing subject.
        prefix = re.sub(r"^(?:또한|그리고)[, ]*", "", ref.quote.strip())
        if entity.quote not in prefix and not prefix.startswith(activity.quote):
            # A repeated site followed by the activity is also explicit continuity.
            facility = context.dimensions.get("facility")
            if facility is None or not prefix.startswith(facility.quote + " " + activity.quote):
                return False
        # A stated event year cannot silently become another period or disappear.
        years = set(_YEAR.findall(claim.quote))
        if years != set(_YEAR.findall(ref.quote)):
            return False
    for name, expected in context.dimensions.items():
        actual = (relation_tags or {}).get(name)
        for value in (expected, actual):
            if value is not None and (
                verify_source_ref(value, graph, tenant_id=tenant_id).verification_state
                != "verified"
                or (not _contains(focal, value) and not _contains(ref, value))
            ):
                return False
        if actual is not None and (expected is None or actual.quote != expected.quote):
            return False
        if expected is None:
            if not local and name in ("facility", "scope", "product", "material", "boundary"):
                return False
            continue
        if not _contains(focal, expected):
            return False
        if not local and name not in ("entity", "metric") and expected.quote not in ref.quote:
            return False
    # New asserted axes cannot evade the checks by omitting them from the claim.
    if any(v is not None and k not in context.dimensions for k, v in (relation_tags or {}).items()):
        return False
    return True


def prepare_table(element, claim, graph, *, tenant_id):
    """Accept a selected comparison year OR value, with both exact refs present."""
    from proofops.application.tagging.pb2_table_evidence import observation_sources

    if element.element_id != "P2" or element.state != "present" or not element.evidence_refs:
        return element, False
    sources = observation_sources(
        claim, graph, tenant_id=tenant_id, recover_row_unit=True, observed_headers=True
    )
    if sources is None:
        return element, False
    for comp in sources["comparisons"]:
        pair = (comp["value"]["ref"], comp["year"])
        if element.normalized_value not in (pair[0].quote, pair[1].quote):
            continue
        if all(any(_contains(r, p) for r in element.evidence_refs) for p in pair) and all(
            verify_source_ref(r, graph, tenant_id=tenant_id).verification_state == "verified"
            and any(_contains(p, r) for p in (*pair, sources["row"]))
            for r in element.evidence_refs
        ):
            return element, True
    return element, False
