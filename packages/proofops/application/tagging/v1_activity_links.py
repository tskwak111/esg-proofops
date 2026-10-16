"""R19/DEC-93 explicit activity links over the once-replayed SC1 inventory.

No search or model calls and no new votes. Every link retains SC1's three raw
receipts, the actual boundary text, and the claim/evidence role spans. This is a
new opt-in reader; historical QT2, SC1 and rulepack content remain unchanged.
"""

import re
from dataclasses import asdict, replace
from uuid import UUID, uuid5

from proofops.application.evidence.binding import _axis_cues
from proofops.application.evidence.report_level import scope_rejection_reason
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.tagging.analysis_scope import InventoryIndex
from proofops.application.tagging.qt2_context import context_refs, guard
from proofops.application.tagging.qt2_inventory import _contains, _key
from proofops.application.tagging.semantic_admission import guard_element
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import pack_content_hash, snapshot_from_validated
from proofops.domain.values import LlmElement, SourceRef

_AXES = dict(subject="entity", metric="metric", site="facility", period="reporting_period")
_STRUCTURAL = {"section_parent", "table_parent", "same_statement"}
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_FUTURE = re.compile(r"예정|전망|계획입니다|목표로|할 계획|할 것입니다")
_TARGET_PERIOD = re.compile(r"(?:년\s*까지|목표\s*연도|기준\s*연도|대비)")
_SITE = re.compile(r"사업장|공장|데이터\s*센터|법인|사옥|본사|사업부|임직원|직원|전사")
_GENERIC_SITE = {"사업장", "사업장별", "공장", "조직", "회사", "기업"}

POLICY = dict(
    profile="v1_activity_links_r19_ap06_v1",
    approval="DEC-93:AP-06; R19-T01/T07; ACTIVITY_SCOPE_V2",
    elements=["M1", "M2", "M4"],
    inventory="element-evidence-inventory-sc1-v1; replay_once; independent_3of3",
    binding="verified_explicit_subject_and_named_activity; exact_asserted_axes",
    structure="direct_typed_graph_edge_only; no_page_proximity_or_company_year_join",
    m2="actual_qualified_target; missing_claim_target_stays_null; no_report_wide_scope",
    period="M1/M4_explicit_same_operating_period; M2_both_undated_only_no_year_borrow",
    scopes={"M1": "global_bound", "M2": "global_bound", "M4": "global_bound"},
    exclusions="M3_and_numeric_unchanged; no_inferred_achievement; no_absence_from_links",
    unresolved=(
        "unknown_attribution_is_not_other_activity; uncovered_linked_cues_block_confirmation"
    ),
    negative_patterns=dict(
        future=_FUTURE.pattern,
        target_period=_TARGET_PERIOD.pattern,
        site=_SITE.pattern,
        year=_YEAR.pattern,
        generic_sites=sorted(_GENERIC_SITE),
    ),
)
POLICY_HASH = canonical_hash(POLICY)


def validate_policy(policy):
    if policy != POLICY:
        raise ValueError("V1_ACTIVITY_POLICY_MISMATCH")


def policy_from_profile(profile):
    policy = profile.get("v1_activity_links")
    if policy is not None:
        validate_policy(policy)
        if profile.get("v1_activity_links_sha256") != POLICY_HASH:
            raise ValueError("V1_ACTIVITY_POLICY_PIN_MISMATCH")
    return policy


def effective_rulepack(rulepack):
    """Versioned AP-06 scope contract; retain base pack and derived hash in receipt."""
    from proofops.application.rulepacks import validate_rulepack

    files = {path: rulepack.file_content(path) for path in rulepack.files}
    for definition in files["rubric/elements.yaml"]["elements"]:
        if definition["id"] in ("M1", "M4"):
            definition["source_scopes"] = list(
                dict.fromkeys([*definition["source_scopes"], "global_bound"])
            )
            definition["binding_policy"] = POLICY["profile"]
    manifest = asdict(rulepack) | dict(version=rulepack.version + "+v1-ap06")
    manifest["rule_pack_id"] = str(
        uuid5(UUID(rulepack.rule_pack_id), POLICY_HASH + rulepack.sha256)
    )
    for content in files.values():
        content["version"] = manifest["version"]
    manifest["files"] = list(rulepack.files)
    manifest["unresolved_gap_ids"] = list(rulepack.unresolved_gap_ids)
    manifest["sha256"] = pack_content_hash(manifest, files)
    checked = validate_rulepack(manifest, files, rulepack.unresolved_gap_ids)
    if not checked.ok:
        raise ValueError("V1_ACTIVITY_RULEPACK_INVALID")
    return snapshot_from_validated(manifest, files)


def confirmed_decision(base, scope, receipt_hash):
    """Wrap a fully decided positive ladder; no absent fact or new ladder rule."""
    from proofops.domain.rules.analysis_scope import ScopeDecision

    result = ScopeDecision(
        **asdict(base),
        confirmation_scope=scope | dict(search_receipt_sha256=receipt_hash),
        confirmation_policy_sha256=scope["confirmation_policy_sha256"],
    )
    return replace(
        result,
        semantic_hash=canonical_hash(
            dict(
                policy_sha256=POLICY_HASH,
                decision=asdict(result),
                receipt_sha256=receipt_hash,
            )
        ),
    )


def _checked(ref, graph, tenant):
    return verify_source_ref(ref, graph, tenant_id=tenant).verification_state == "verified"


def _attributed(ref, evidence, graph):
    if _contains(evidence, ref):
        return True
    # SC1 accepts structural attributes; only a semantic parent/header edge is
    # sufficient here. Same page, nearby blocks and repeated words are not links.
    return any(
        edge.source_id == evidence.source_id
        and edge.target_id == ref.source_id
        and edge.relation in _STRUCTURAL
        for edge in graph.edges
    )


def _candidate(candidate, context, graph, *, tenant_id, rulepack):
    eid = candidate["element_id"]
    if eid not in POLICY["elements"]:
        return None
    focal = context.claim.source_refs[0]
    evidence = SourceRef(**candidate["evidence_ref"])
    votes = candidate["votes"]
    if set(votes) != {"1", "2", "3"} or any(
        v["state"] != "present" or v["evidence_ref"] != candidate["evidence_ref"]
        for v in votes.values()
    ):
        return None
    if len({canonical_hash(v["attributes"]) for v in votes.values()}) != 1:
        return None
    attrs = next(iter(votes.values()))["attributes"]
    roles = {k: SourceRef(**v) if v else None for k, v in attrs.items()}

    def attributed(name, value):
        if _attributed(value, evidence, graph):
            return True
        # Existing same-paragraph explicit actor continuation. Activity, target
        # and time still need their own refs; this never imports a page's actor.
        return (
            name == "subject"
            and _contains(focal, value)
            and focal.source_id == evidence.source_id
            and any(
                _contains(r, evidence)
                for r in context_refs(context.claim, graph, tenant_id=tenant_id)
            )
        )

    if not _checked(evidence, graph, tenant_id) or any(
        value and (not _checked(value, graph, tenant_id) or not attributed(name, value))
        for name, value in roles.items()
    ):
        return None
    if scope_rejection_reason(eid, (evidence,), rulepack=rulepack, original=graph):
        return None
    # Context qualifiers are never silently discarded, including unresolved axes.
    for axis, value in context.dimensions.items():
        if axis not in _AXES.values():
            # A null optional GHG axis is retained as null, never filled merely
            # to make a non-GHG management activity pass a four-axis matcher.
            if (
                value is not None
                or axis not in ("scope", "boundary")
                or _axis_cues(focal.quote + evidence.quote, axis)
            ):
                return None
    for attr in ("subject", "metric"):
        expected, actual = context.dimensions.get(_AXES[attr]), roles[attr]
        if expected is None or actual is None or not _contains(focal, expected):
            return None
        if not _checked(expected, graph, tenant_id) or _key(expected.quote) != _key(actual.quote):
            return None
    activity = roles["metric"]
    if activity is None:
        return None
    # A company/year join, generic topic or ordinary noun cannot name a process.
    if len(_key(activity.quote)) < 3 or _key(activity.quote) in {
        "환경",
        "환경경영",
        "관리",
        "에너지",
        "온실가스",
        "사업",
        "기후변화",
        "감축",
    }:
        return None
    target, claimed_target = roles["site"], context.dimensions.get("facility")
    if target is None or not _SITE.search(target.quote) or _key(target.quote) in _GENERIC_SITE:
        return None
    if claimed_target is not None:
        if (
            not _contains(focal, claimed_target)
            or not _checked(claimed_target, graph, tenant_id)
            or _key(claimed_target.quote) != _key(target.quote)
        ):
            return None
    elif eid != "M2":
        return None
    period, claimed_period = roles["period"], context.dimensions.get("reporting_period")
    if period is None or claimed_period is None:
        if (
            eid != "M2"
            or period is not None
            or claimed_period is not None
            or _YEAR.search(focal.quote + evidence.quote)
        ):
            return None
    elif (
        not _contains(focal, claimed_period)
        or not _checked(claimed_period, graph, tenant_id)
        or _key(period.quote) != _key(claimed_period.quote)
    ):
        return None
    # Avoid roles that were selected from target/base years, and disjoint event years.
    if _TARGET_PERIOD.search(focal.quote + evidence.quote):
        return None
    if period and (_YEAR.findall(focal.quote) != _YEAR.findall(evidence.quote)):
        return None
    if eid == "M4" and _FUTURE.search(evidence.quote):
        return None
    element = LlmElement(eid, "present", (evidence,), None, evidence.source_id, None)
    admitted = guard(guard_element(element, claim_quote=context.claim.quote))
    if admitted.state != "present":
        return None
    return dict(
        candidate_id=candidate["candidate_id"],
        element=asdict(admitted),
        source_scope="global_bound",
        replica_ids=[1, 2, 3],
        link_status="accepted",
        claim_roles={k: asdict(v) if v else None for k, v in context.dimensions.items()},
        evidence_roles=attrs,
        qualified_target=asdict(target),
        period_role="operating_period" if period else "not_stated_no_period_credit",
        structural_edges=[
            asdict(e)
            for e in graph.edges
            if e.source_id == evidence.source_id
            and any(v and v.source_id == e.target_id for v in roles.values())
            and e.relation in _STRUCTURAL
        ],
    )


def link_inventory(context, inventory, graph, *, run_id, tenant_id, rulepack, policy):
    validate_policy(policy)
    index = inventory if isinstance(inventory, InventoryIndex) else InventoryIndex(inventory, graph)
    if index.graph is not graph:
        raise ValueError("V1_INVENTORY_GRAPH_MISMATCH")
    selection, claim = index.inventory["selection"], context.claim
    if (
        (selection["run_id"], selection["tenant_id"]) != (run_id, tenant_id)
        or (graph.tenant_id, claim.tenant_id, rulepack.tenant_id) != (tenant_id,) * 3
        or (claim.document_version_id, claim.parse_manifest_id, claim.source_sha256)
        != (graph.document_version_id, graph.parse_manifest_id, graph.source_sha256)
    ):
        raise ValueError("V1_INVENTORY_IDENTITY_MISMATCH")
    links, unresolved = [], set()
    if (
        claim.source_quality == "verified"
        and len(claim.source_refs) == 1
        and _checked(claim.source_refs[0], graph, tenant_id)
        and claim.source_refs[0].page_num in selection["selected_pages"]
    ):
        for candidate in index.inventory["candidates"]:
            if candidate["physical_page"] not in selection["selected_pages"]:
                continue
            accepted = _candidate(candidate, context, graph, tenant_id=tenant_id, rulepack=rulepack)
            if accepted:
                links.append(accepted)
            eid = candidate["element_id"]
            if eid not in POLICY["elements"]:
                continue
            # Unknown attribution cannot prove a contrary receipt belongs to
            # another activity. Exclude it only on explicit mismatching roles.
            relevant = any(
                all(
                    context.dimensions.get(_AXES[attr]) is None
                    or vote["attributes"].get(attr) is None
                    or _key(context.dimensions[_AXES[attr]].quote)
                    == _key(vote["attributes"][attr]["quote"])
                    for attr in ("subject", "metric")
                )
                for vote in candidate["votes"].values()
            )
            states = [candidate["votes"].get(str(i), {}).get("state", "unknown") for i in (1, 2, 3)]
            attributes = [vote["attributes"] for vote in candidate["votes"].values()]
            required_roles = ["subject", "metric", "site"]
            if eid != "M2" or context.dimensions.get("reporting_period") is not None:
                required_roles.append("period")
            if relevant and (
                "conflict" in states
                or "unknown" in states
                or "unreadable" in states
                or ("present" in states and "not_applicable" in states)
                or len({canonical_hash(attrs) for attrs in attributes}) > 1
                or any(attrs.get(role) is None for attrs in attributes for role in required_roles)
            ):
                unresolved.add(eid)
    links = [link for link in links if link["element"]["element_id"] not in unresolved]
    body = dict(
        schema="v1-activity-links-r19-v1",
        run_id=run_id,
        claim_id=claim.claim_id,
        inventory_sha256=index.inventory["inventory_sha256"],
        selection=selection,
        policy_sha256=POLICY_HASH,
        links=links,
        grade_credit=False,
        unresolved_elements=sorted(unresolved),
    )
    return body | dict(links_sha256=canonical_hash(body))
