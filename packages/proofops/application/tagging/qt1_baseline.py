"""AP-03: replay SC1, then bind an explicitly referenced GHG maintenance baseline.

Inventory votes only nominate source facts. Each final G2/G3 vote must select its
own literal value/year/unit bundle. No reduction, deadline or absence is inferred.
"""

import re
from dataclasses import asdict, replace
from unicodedata import normalize

from proofops.application.evidence.binding import _axis_cues
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.tagging.analysis_scope import InventoryIndex
from proofops.application.tagging.element_inventory import replay_inventory
from proofops.application.tagging.qt1_tuples import add_sources, contains, tuples_for
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.qt1_baseline import SOURCE_SCOPE
from proofops.domain.values import SourceRef

GUIDANCE = (
    "DEC-93 AP-03 overrides DEC-24's same-sentence restriction ONLY for supplied "
    "qt1_baseline_links: a GHG maintenance target explicitly referencing that baseline "
    "year may use its verified selected-scope value. Select value, unit and baseline "
    "year IDs for G2 and separately G3; normalize to the literal value. Keep the "
    "maintenance meaning. Never invent 0% reduction, a target year, progress or "
    "absence. Other units/subjects/metrics/boundaries/years, unresolved and contrary "
    "sources stay held. Non-GHG direct evidence rules and safe-harbor grade-null stay."
)
POLICY = dict(
    profile="qt1_v25_maintenance_baseline_ap03_v1",
    approval="DEC-93/AP-03",
    source_scope=SOURCE_SCOPE,
    elements=["G2", "G3"],
    guidance_sha256=canonical_hash(GUIDANCE),
    inventory="replayed-element-evidence-inventory-sc1-v1; three-unopposed-present-votes",
    identity="same-tenant-run-document-version-manifest-graph-selected-pages",
    link="explicit-baseline-year-in-maintenance-goal; exact-subject-metric-unit-site-scope",
    unknown="missing-roles-unreadable-conflict-ambiguous-values-remain-candidate-only",
    outside_selection="not_run; never-search-or-expand-scope",
)
_UNIT = re.compile(r"(?<![A-Za-z가-힣])(?:천|만)?\s*tCO[₂2](?:-?(?:eq|e))?", re.I)
_NUMBER = r"[+−-]?\d[\d,]*(?:\.\d+)?"
_QUANTITY = re.compile(rf"(?<![\d,.])({_NUMBER})\s*({_UNIT.pattern})(?![A-Za-z/])", re.I)
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_BASELINE = re.compile(r"((?:19|20)\d{2})년(?:(?!(?:19|20)\d{2})[^.!?;\n]){0,80}?수준")
_BOUNDARY = re.compile(r"전사|그룹|본사|국내|해외|전\s*사업장|생산공장|연결|별도")
POLICY.update(
    unit=_UNIT.pattern,
    baseline_reference=_BASELINE.pattern,
    boundary_qualifiers=_BOUNDARY.pattern,
    intensity="explicit-absolute-GHG-unit-only; no-implicit-scale-or-denominator-conversion",
)


def _key(text):
    return " ".join(normalize("NFC", text).casefold().split())


def _part(ref, start, end):
    return ref | dict(
        char_start=ref["char_start"] + start,
        char_end=ref["char_start"] + end,
        quote=ref["quote"][start:end],
    )


def _verified(ref, graph, tenant):
    return (
        verify_source_ref(SourceRef(**ref), graph, tenant_id=tenant).verification_state
        == "verified"
    )


def _target(context, graph):
    claim = context.claim
    if claim.source_quality != "verified" or len(claim.source_refs) != 1:
        return None
    focal = asdict(claim.source_refs[0])
    if claim.quote != focal["quote"]:
        return None
    if not _verified(focal, graph, claim.tenant_id) or not re.search(r"유지|관리", claim.quote):
        return None
    matches = [m for m in _BASELINE.finditer(claim.quote) if len(_YEAR.findall(m[0])) == 1]
    units = list(_UNIT.finditer(claim.quote))
    if len(matches) != 1 or len(units) != 1:
        return None
    if re.match(r"\s*/", claim.quote[units[0].end() :]):
        return None
    required = ("entity", "metric", "facility", "scope")
    if any(context.dimensions.get(k) is None for k in required):
        return None
    for name, ref in context.dimensions.items():
        if name == "reporting_period":
            continue  # target/observation year is never substituted for the baseline year
        if (
            ref is None
            or not contains(focal, asdict(ref))
            or not _verified(asdict(ref), graph, claim.tenant_id)
        ):
            return None
    if not re.search(r"배출량|emissions", context.dimensions["metric"].quote, re.I):
        return None
    return dict(
        year=matches[0][1],
        unit=units[0][0],
        baseline_reference=_part(focal, matches[0].start(1), matches[0].end(1)),
    )


def _source_tuples(candidate, graph):
    ref = candidate["evidence_ref"]
    block = next(b for b in graph.blocks if b.source_id == ref["source_id"])
    if block.kind == "table":
        return [
            t
            for t in tuples_for(block, graph)
            if t["admitted"] and t["period_role"] == "observation" and contains(ref, t["value"])
        ]
    if block.kind != "paragraph" or re.search(r"목표|전망|예상|추정", ref["quote"]):
        return []
    quantities, years = list(_QUANTITY.finditer(ref["quote"])), list(_YEAR.finditer(ref["quote"]))
    if len(quantities) != 1 or len(years) != 1:
        return []
    q, year = quantities[0], years[0]
    return [
        dict(
            value=_part(ref, q.start(1), q.end(1)),
            unit=_part(ref, q.start(2), q.end(2)),
            period=_part(ref, year.start(), year.end()),
            year=year[0],
        )
    ]


def _matches(candidate, context, target, graph):
    evidence = candidate["evidence_ref"]
    votes = candidate["votes"]
    if set(votes) != {"1", "2", "3"} or any(v["state"] != "present" for v in votes.values()):
        return False
    for vote in votes.values():
        if vote["evidence_ref"] != evidence:
            return False
        for attr, axis in (("subject", "entity"), ("metric", "metric"), ("site", "facility")):
            ref = vote["attributes"][attr]
            if (
                ref is None
                or not _verified(ref, graph, context.claim.tenant_id)
                or not contains(evidence, ref)
                or _key(ref["quote"]) != _key(context.dimensions[axis].quote)
            ):
                return False
        period = vote["attributes"]["period"]
        if period is None or _YEAR.findall(period["quote"]) != [target["year"]]:
            return False
    # SC1's four-axis schema must not erase a Scope/product/organization qualifier.
    for axis in ("scope", "boundary"):
        if _axis_cues(evidence["quote"], axis) != _axis_cues(context.claim.quote, axis):
            return False
    if set(_BOUNDARY.findall(evidence["quote"])) != set(_BOUNDARY.findall(context.claim.quote)):
        return False
    for name, ref in context.dimensions.items():
        if name not in ("entity", "metric", "facility", "scope", "reporting_period") and (
            ref is None or ref.quote not in evidence["quote"]
        ):
            return False
    return True


def baseline_links(context, inventory, graph, *, run_id, tenant_id):
    if isinstance(inventory, InventoryIndex):
        if inventory.graph is not graph:
            raise ValueError("QT1_BASELINE_GRAPH_MISMATCH")
        inv = inventory.inventory
    else:
        inv = replay_inventory(inventory, graph)
    selection, claim = inv["selection"], context.claim
    if (
        selection["run_id"] != run_id
        or selection["tenant_id"] != tenant_id
        or (claim.tenant_id, graph.tenant_id) != (tenant_id, tenant_id)
        or (claim.document_version_id, claim.parse_manifest_id, claim.source_sha256)
        != (graph.document_version_id, graph.parse_manifest_id, graph.source_sha256)
    ):
        raise ValueError("QT1_BASELINE_IDENTITY_MISMATCH")
    body = dict(
        policy=POLICY,
        run_id=run_id,
        claim_id=claim.claim_id,
        inventory_sha256=inv["inventory_sha256"],
        selection=selection,
        outside_selection="not_run",
        links=[],
        candidates=[],
    )
    target = _target(context, graph)
    if target is not None and all(
        r.page_num in selection["selected_pages"] for r in claim.source_refs
    ):
        for candidate in inv["candidates"]:
            if candidate["element_id"] != "G3":
                continue
            evidence = candidate["evidence_ref"]
            if evidence["page_num"] not in selection["selected_pages"]:
                continue
            # Query the frozen inventory; unrelated metrics/years cannot block or
            # satisfy this baseline. Ambiguous matching candidates still veto it.
            if not all(
                context.dimensions[k].quote in evidence["quote"]
                for k in ("entity", "metric", "facility")
            ):
                continue
            if target["year"] not in evidence["quote"] and not any(
                v["attributes"].get("period")
                and target["year"] in v["attributes"]["period"]["quote"]
                for v in candidate["votes"].values()
            ):
                continue
            if contains(asdict(claim.source_refs[0]), evidence):
                continue  # the target itself is not its historical observation
            if not _matches(candidate, context, target, graph):
                body["candidates"].append(
                    dict(candidate_id=candidate["candidate_id"], status="unresolved")
                )
                continue
            for item in _source_tuples(candidate, graph):
                if item["year"] != target["year"] or _key(item["unit"]["quote"]) != _key(
                    target["unit"]
                ):
                    continue
                if not all(
                    _verified(item[k], graph, tenant_id) for k in ("value", "unit", "period")
                ):
                    continue
                body["links"].append(
                    dict(
                        candidate_id=candidate["candidate_id"],
                        value=item["value"],
                        unit=item["unit"],
                        period=item["period"],
                        baseline_reference=target["baseline_reference"],
                        elements=["G2", "G3"],
                        meaning="maintenance_at_baseline",
                        replica_ids=[1, 2, 3],
                    )
                )
        values = {_key(link["value"]["quote"]) for link in body["links"]}
        # Do not vote away a competing value, or a matching unresolved candidate.
        if len(values) > 1 or body["candidates"]:
            body["candidates"] += [
                dict(candidate_id=link["candidate_id"], status="conflict_or_unresolved")
                for link in body["links"]
            ]
            body["links"] = []
    return body | dict(receipt_sha256=canonical_hash(body))


def augment_packet(data, receipt):
    data["qt1_baseline_receipt"] = receipt
    for link in receipt["links"]:
        add_sources(
            data, [link[k] for k in ("value", "unit", "period")], ["G2", "G3"], scope=SOURCE_SCOPE
        )
    return data


def validate_packet(data, context, inventory, graph, *, tenant_id):
    expected = baseline_links(context, inventory, graph, run_id=data["run_id"], tenant_id=tenant_id)
    if canonical_hash(data.get("qt1_baseline_receipt")) != canonical_hash(expected):
        raise ValueError("QT1_BASELINE_REPLAY_MISMATCH")
    return expected["links"]


def prepare_element(element, links):
    if element.state != "present" or element.element_id not in ("G2", "G3"):
        return element, False
    refs = [asdict(r) for r in element.evidence_refs]
    for link in links:
        required = [link[k] for k in ("value", "unit", "period")]
        if (
            element.normalized_value == link["value"]["quote"]
            and all(any(contains(r, p) for r in refs) for p in required)
            and all(any(contains(p, r) for p in required) for r in refs)
        ):
            return replace(element, evidence_refs=tuple(SourceRef(**r) for r in required)), True
    return element, False
