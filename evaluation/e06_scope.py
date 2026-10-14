"""Opt-in discovery scope and guarded S18/S14 proposals; never evidence admission.

W4/AS1 bytes and defaults remain replayable. All proposed roles are unverified.
Caps are for declared subset review, never full-report claim quotas.
"""

from __future__ import annotations

import re
from copy import deepcopy

from proofops.domain.provenance import canonical_hash

from evaluation.report_scope import (
    ENV_GROUPS,
    RANKING_POLICY_SHA256,
    RANKING_VERSION,
    SUPPORT_POLICY_SHA256,
    SUPPORT_VERSION,
    _normal,
    build_plan,
)
from evaluation.scope_claim_signals import claim_signals, claim_support_signals

VERSION = "E06-scope-v1"
SUMMARY_HEADING = (
    r"progress|summary|주요\s*성과|목표.*성과|성과.*목표|환경.*목표|"
    r"environment.*(?:target|performance)"
)
POLICY = {
    "version": VERSION,
    "base_policy_sha256": RANKING_POLICY_SHA256,
    "claim_cap": 10,
    "ceo_cap": 1,
    "summary": "readable_other; >=2 environmental groups; target+metric+implementation; score>=30",
    "summary_heading_pattern": SUMMARY_HEADING,
    "spare_slots": (
        "actionable_summary_then_nonnumeric_governance_heading_then_missing_topic;" "score_tiebreak"
    ),
    "preserve": "existing_non_ceo_claims; retain_one_CEO; no_topic_grade_or_full_mode_quota",
    "ocr": (
        "native_scope_failed_only; discovery_only; original_unknowns_retained;"
        "bounded_front_back_middle"
    ),
    "bundles": "contiguous_assurance_heading_pages; never_partial_covered",
    "compact": "S18 claim10/evidence_only=max(8,18-claims)/union18; S14 claim8/evidence6/union14",
    "restore": "required_source_page_or_bundle_loss_restores_union30; rejected_candidate_retained",
    "adoption": "requires_source_binding_and_paired_parse_or_wall_measurement; default_not_adopted",
}
POLICY_SHA256 = canonical_hash(POLICY)
W5_SCOPE_VERSION = "E06-W5-scope-v1"
W5_SCOPE_POLICY = POLICY | dict(version=W5_SCOPE_VERSION, base_policy_sha256=SUPPORT_POLICY_SHA256)
W5_SCOPE_POLICY_SHA256 = canonical_hash(W5_SCOPE_POLICY)


def _seal(plan):
    plan["plan_sha256"] = canonical_hash({k: v for k, v in plan.items() if k != "plan_sha256"})
    return plan


def _update_selection(plan, claims, evidence):
    claims, evidence = sorted(set(claims)), sorted(set(evidence))
    plan.update(
        selected_claim_pages=claims,
        selected_evidence_pages=evidence,
        evidence_only_pages=sorted(set(evidence) - set(claims)),
        excluded_claim_candidate_pages=sorted(set(plan["claim_candidate_pages"]) - set(claims)),
        excluded_evidence_candidate_pages=sorted(
            set(plan["evidence_candidate_pages"]) - set(evidence)
        ),
    )
    for row in plan["pages"]:
        row["claim_selected"] = row["page"] in claims
        row["evidence_selected"] = row["page"] in evidence
        row["reasons"] = [r for r in row["reasons"] if r != "excluded_by_declared_cap"]
        if row["page"] in plan["evidence_candidate_pages"] and row["page"] not in evidence:
            row["reasons"].append("excluded_by_declared_cap;unsearched_by_precision_parser")


def _topic(text):
    hits = {
        g: len(re.findall(pattern, _normal(text)))
        for g, pattern in ENV_GROUPS.items()
        if g != "environment"
    }
    best = max(hits, key=hits.get)
    return best if hits[best] else "environment"


def build_scope(
    study, texts, *, headings=None, primary=None, discovery=None, ranking_policy=RANKING_VERSION
):
    """Recover actionable summaries and spare-slot diversity without hardcoded pages."""
    if ranking_policy not in (RANKING_VERSION, SUPPORT_VERSION):
        raise ValueError("unsupported E06 ranking policy")
    plan = deepcopy(
        build_plan(
            study,
            texts,
            page_headings=headings,
            page_primary_headings=primary,
            ranking_policy=ranking_policy,
        )
    )
    baseline_sha = plan["plan_sha256"]
    rows = {r["page"]: r for r in plan["pages"]}
    for p, row in rows.items():
        text = texts.get(p, "")
        scorer = claim_support_signals if ranking_policy == SUPPORT_VERSION else claim_signals
        score, signals = scorer(text, (headings or {}).get(p, []))
        row.update(
            dominant_environment_topic=_topic(text), claim_signal_score=score, claim_signals=signals
        )
        if (
            row["category"] == "other"
            and p not in plan["conflict_pages"]
            and p not in plan["unreadable_pages"]
            and len(row["environmental_groups"]) >= 2
            and score >= 30
            and any(
                re.search(SUMMARY_HEADING, title, re.I) for title in (headings or {}).get(p, [])
            )
            and all(signals[k] for k in ("target_year", "metric", "implementation"))
        ):
            row.update(
                category="e_narrative", classification_method="actionable_environment_summary"
            )
            row["reasons"].append("environment_summary_overrides_section_routing_only")
            plan["environmental_candidate_pages"].append(p)
    candidates = sorted(set(plan["environmental_candidate_pages"]))
    plan["environmental_candidate_pages"] = candidates
    plan["claim_candidate_pages"] = sorted(set(candidates + plan["ceo_candidate_pages"]))
    plan["evidence_candidate_pages"] = sorted(set(plan["evidence_candidate_pages"] + candidates))
    ceos = sorted(set(plan["selected_claim_pages"]) & set(plan["ceo_candidate_pages"]))[:1]
    selected = set(plan["selected_claim_pages"]) - set(plan["ceo_candidate_pages"])
    selected.update(ceos)
    represented = {_topic(texts.get(p, "")) for p in selected if p not in ceos}
    # Existing non-CEO claims never displaced by speculative hints. Spare slots only.
    remaining = [p for p in candidates if p not in selected]

    def management(p):
        return (
            rows[p]["claim_signals"]["metric"] == 0
            and rows[p]["claim_signals"]["named_means"] > 0
            and any(
                re.search(r"거버넌스|governance", title, re.I)
                for title in (headings or {}).get(p, [])
            )
        )

    remaining = [
        p
        for p in remaining
        if rows[p]["classification_method"] == "actionable_environment_summary"
        or management(p)
        or rows[p]["dominant_environment_topic"] not in represented
    ]
    ranked = sorted(
        remaining,
        key=lambda p: (
            -int(rows[p]["classification_method"] == "actionable_environment_summary"),
            -int(bool(management(p))),
            -int(rows[p]["dominant_environment_topic"] not in represented),
            -rows[p]["claim_signal_score"],
            -rows[p]["environmental_density"],
            p,
        ),
    )
    for p in ranked[: max(0, 10 - len(selected))]:
        selected.add(p)
        rows[p]["reasons"].append("spare_claim_slot_role_and_topic_recovery")
    evidence = set(plan["selected_evidence_pages"]) | selected
    # Evict lower priority evidence-only previews only if the union cap is reached.
    if len(evidence) > 30:
        extras = sorted(
            evidence - selected,
            key=lambda p: (
                rows[p]["category"] != "assurance",
                -rows[p]["environmental_density"],
                p,
            ),
        )
        evidence = selected | set(extras[: 30 - len(selected)])
    plan.update(
        version=W5_SCOPE_VERSION if ranking_policy == SUPPORT_VERSION else VERSION,
        policy_sha256=W5_SCOPE_POLICY_SHA256
        if ranking_policy == SUPPORT_VERSION
        else POLICY_SHA256,
        method=W5_SCOPE_VERSION if ranking_policy == SUPPORT_VERSION else VERSION,
        baseline_plan_sha256=baseline_sha,
        assurance_status="undetermined",
    )
    plan["settings"]["max_ceo_pages"] = 1
    if selected:
        plan.update(status="candidate_only", failure_reasons=[], suggested_front_pages=[])
    if discovery is not None:
        plan["discovery"] = {k: v for k, v in discovery.items() if k != "texts"}
        plan["scope_incomplete"] = discovery["scope_incomplete"]
        plan["discovery_only_pages"] = sorted(discovery["texts"])
        # OCR proposals do not resolve original native/source-quality issues.
        plan["limitations"].append(
            "OCR discovery is not independent source verification; precise parsing required."
        )
    _update_selection(plan, selected, evidence)
    return _seal(plan)


def assurance_bundles(plan, headings=None):
    """Conservative contiguous heading runs, not declarations of scope coverage."""
    pages = []
    for row in plan["pages"]:
        titles = (headings or {}).get(row["page"], [])
        if row["category"] == "assurance" or any(
            re.search(r"검증\s*의견서|제\s*3\s*자\s*검증|assurance\s*(?:statement|report)", t, re.I)
            for t in titles
        ):
            pages.append(row["page"])
    bundles = []
    for p in sorted(pages):
        if bundles and bundles[-1][-1] == p - 1:
            bundles[-1].append(p)
        else:
            bundles.append([p])
    return bundles


def support_candidate_pages(plan, texts, headings=None):
    """Protect discovery candidates; this is not evidence binding or admission."""
    required = set()
    for row in plan["pages"]:
        p = row["page"]
        titles = (headings or {}).get(p, [])
        if (
            row["category"] == "environmental_data"
            or (row["category"] == "esg_data" and row["environmental_hits"] >= 2)
            or any(
                re.search(
                    r"보고\s*범위|보고\s*기준|reporting\s*(?:scope|boundary)|methodolog",
                    title,
                    re.I,
                )
                for title in titles
            )
        ):
            required.add(p)
    return sorted(required)


def compact_plan(base, texts, *, profile="S18", required_pages=(), assurance_bundles=()):
    """Candidate reduction; restore cap on any known support/bundle loss.

    Required pages must come from trusted frozen refs or original-page inspection,
    never from a model asserting present. Empty inventory cannot approve adoption.
    """
    if profile not in ("S18", "S14"):
        raise ValueError("unsupported compact scope profile")
    count = base["page_count"]
    bundles = [sorted(set(b)) for b in assurance_bundles]
    for pages in [list(required_pages), *bundles]:
        if any(type(p) is not int or not 1 <= p <= count for p in pages):
            raise ValueError("invalid required physical page")
    original_claims = list(base["selected_claim_pages"])
    claims = original_claims if profile == "S18" else original_claims[:8]
    cap = 18 if profile == "S18" else 14
    plan = deepcopy(base)
    rows = {r["page"]: r for r in plan["pages"]}
    for bundle in bundles:
        for p in bundle:
            if rows[p]["category"] not in ("unreadable", "conflict"):
                rows[p]["category"] = "assurance"
                rows[p]["reasons"].append("discovered_assurance_bundle;coverage_undetermined")
    all_bundle_pages = set(p for b in bundles for p in b)
    required = set(required_pages)
    candidates = set(base["selected_evidence_pages"]) | required | all_bundle_pages
    # Whole discovered assurance runs first, then support, then relevant previews.
    units = [b for b in bundles if b]
    bundled = set(p for b in units for p in b)
    ordered = sorted(
        candidates - bundled - set(claims),
        key=lambda p: (
            -int(p in required),
            -int(rows[p]["category"] == "environmental_data"),
            -rows[p]["environmental_density"],
            p,
        ),
    )
    units.extend([[p] for p in ordered])
    selected = set(claims)
    for unit in units:
        if len(selected | set(unit)) <= cap:
            selected.update(unit)
    missing = sorted((required | all_bundle_pages) - selected)
    short = profile == "S18" and len(candidates) <= cap
    proposed = sorted(selected)
    rejected = profile == "S18" and bool(missing)
    if rejected:
        # Preserve known direct refs and bundles before any low priority preview.
        selected = set(claims) | required | all_bundle_pages
        for unit in units:
            if len(selected | set(unit)) <= 30:
                selected.update(unit)
        if len(selected) > 30:
            selected = set(base["selected_evidence_pages"])
            # If even the original cap cannot contain complete support, block use.
            plan["status"] = "failed"
            plan["failure_reasons"] = ["EVIDENCE_BUNDLE_INCOMPLETE"]
    if short:
        selected = candidates
    incomplete = [b for b in bundles if not set(b) <= selected]
    plan.update(
        version=VERSION,
        policy_sha256=POLICY_SHA256,
        method=VERSION,
        baseline_plan_sha256=base["plan_sha256"],
        assurance_status="undetermined",
        evidence_bundle_incomplete=bool(incomplete),
        scope_incomplete=bool(incomplete) or base.get("scope_incomplete", False),
        missing_bundle_pages=sorted(all_bundle_pages - selected),
        discovered_assurance_bundles=bundles,
    )
    plan["settings"] = dict(
        plan["settings"],
        compact_profile=profile,
        claim_page_cap=10 if profile == "S18" else 8,
        evidence_only_cap=max(8, 18 - len(claims)) if profile == "S18" else 6,
        union_cap=cap,
        max_evidence_pages=30 if rejected else cap,
        effective_union_cap=30 if rejected else cap,
    )
    plan["reduction"] = dict(
        profile=profile,
        status="rejected_restored_cap"
        if rejected
        else "unchanged_short_scope"
        if short
        else "candidate_only",
        adoption="not_adopted",
        proposed_claim_pages=claims,
        proposed_evidence_pages=proposed,
        missing_required_pages=missing,
        baseline_union=len(base["selected_evidence_pages"]),
        candidate_union=len(proposed),
        excluded_baseline_claim_pages=sorted(set(original_claims) - set(claims)),
        excluded_baseline_evidence_pages=sorted(
            set(base["selected_evidence_pages"]) - set(proposed)
        ),
        source_binding_evaluation="not_run",
        model_semantic_recall="not_run",
        paired_precision_parse_wall="not_run",
    )
    plan["claim_candidate_pages"] = sorted(set(plan["claim_candidate_pages"]) | set(claims))
    plan["evidence_candidate_pages"] = sorted(set(plan["evidence_candidate_pages"]) | candidates)
    _update_selection(plan, claims, selected)
    return _seal(plan)


def main():
    """Explicit local opt-in; no shared hosted settings or paid provider calls."""
    import argparse
    import json
    from pathlib import Path

    from evaluation.hosted_scope_plan import inspect_streaming
    from evaluation.scope_discovery_ocr import CPUDiscoveryReader

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pdf", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--profile", choices=("E06", "S18", "S14"), default="E06")
    cli.add_argument("--tenant", required=True)
    cli.add_argument("--ocr-cache", type=Path)
    cli.add_argument("--ocr-page-cap", type=int, default=24)
    args = cli.parse_args()
    # Lazy initialization guarantees normal native reports incur no OCR/compile.
    reader = None

    def read(page):
        nonlocal reader
        if reader is None:
            reader = CPUDiscoveryReader(args.pdf, tenant_id=args.tenant, cache_dir=args.ocr_cache)
        return reader(page)

    plan = inspect_streaming(
        args.pdf,
        scope_profile=args.profile,
        discovery_reader=read if args.ocr_cache else None,
        max_discovery_pages=args.ocr_page_cap,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                k: plan.get(k)
                for k in (
                    "status",
                    "selected_claim_pages",
                    "selected_evidence_pages",
                    "scope_incomplete",
                    "failure_reasons",
                )
            },
            ensure_ascii=False,
        )
    )
    return 0 if plan["status"] == "candidate_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
