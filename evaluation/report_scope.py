"""Bounded, editable offline scope proposals. No models or evidence admission.

Opt-in policy AS1-v1 leaves report_sections v11 and its hash unchanged.
Physical pages only; snippets are native previews, never verified SourceRefs.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import Counter
from hashlib import file_digest
from importlib.metadata import version
from pathlib import Path
from statistics import median

from proofops.domain.provenance import canonical_hash
from pypdf import PdfReader

from evaluation.report_sections import POLICY_HASH, build_map
from evaluation.report_sections import inspect as inspect_sections

VERSION = "AS1-v1"
CEO_PATTERN = (
    r"(?:(?:총괄\s*)?ceo\s*(?:message|letter|statement|인사말|메시지)|"
    r"(?:message|letter|statement)\s+(?:from|by)\s+(?:the\s+|our\s+)?"
    r"(?:ceo|chairman|president|chief\s+executive(?:\s+officer)?)|"
    r"(?:chairman|president)\s*(?:message|letter)|"
    r"(?:대표\s*이사|최고\s*경영자|경영진|회장)\s*(?:인사말|메시지)|"
    r"letter\s+to\s+(?:our\s+)?stakeholders)"
)
ENV_GROUPS = {
    "climate": r"climate|기후|탄소|\bcarbon\b|net\s*zero|탄소중립",
    "emissions": r"온실가스|배출량|\bemissions?\b|\bghg\b|greenhouse",
    "energy": r"에너지|재생에너지|\benergy\b|renewable",
    "water": r"용수|수자원|물\s*관리|\bwater\b",
    "circularity": r"폐기물|자원순환|순환경제|재활용|\bwaste\b|recycl|circular",
    "nature": r"생물다양성|자연자본|biodiversity|ecosystem",
    "environment": r"환경|environment|pollution|오염",
}
EVIDENCE_PATTERNS = {
    "assurance": r"assurance\s*(?:statement|report)|independent\s*assurance|"
    r"검증\s*의견서|제\s*3\s*자\s*(?:검증|보증)|온실가스.*검증",
    "gri_index": r"gri\s*(?:content\s*)?index|gri\s*(?:콘텐츠|내용)\s*인덱스",
    "environmental_data": r"환경\s*(?:데이터|성과)|environmental\s*(?:data|performance)|"
    r"온실가스\s*배출량\s*(?:현황|데이터)|esg\s*data|facts\s*(?:&|and)\s*figures|"
    r"데이터북|성과\s*데이터",
}
POLICY = {
    "version": VERSION,
    "section_policy_sha256": POLICY_HASH,
    "ceo_pattern": CEO_PATTERN,
    "environment_groups": ENV_GROUPS,
    "evidence_patterns": EVIDENCE_PATTERNS,
    "max_claim_pages": 10,
    "max_ceo_pages": 2,
    "front_scan_pages": 20,
    "default_environment_pages": 8,
    "default_evidence_pages": 30,
    "evidence_cap_semantics": "total_union_including_claim_pages",
    "minimum_native_letters": 80,
    "minimum_body_chars": 200,
    "density": "hits_per_1000_body_chars; tie:distinct_groups,hits,physical_page",
    "fallback": "unknown_main_native_heading_plus_2_groups_4_hits; preserve_original_unknowns",
    "repeated_lines": "remove_short_lines_repeated_on_max(3,20percent)_pages",
    "prominent_heading": (
        "pypdf_visitor_effective_font_size: CEO>=12pt; others>=max(12,median*1.15)"
    ),
    "container_guard": "prominent_data_appendix_policy_book_until_next_main_chapter",
    "ceo_hierarchy": "physical_CEO_title_plus_only_intro_and_CEO_anchors; keep_original_conflict",
    "primary_heading": (
        "alphabetic_runs_at_75percent_of_largest_font; remove_body_subheading_fallback"
    ),
    "failure": "no_readable_environmental_narrative; suggest_front_3_never_full_pdf",
}
POLICY_SHA256 = canonical_hash(POLICY)


def _normal(text):
    return unicodedata.normalize("NFKC", text).casefold()


def _heading_lines(text, repeated):
    return [
        line.strip()
        for line in text[:1400].splitlines()
        if 0 < len(line.strip()) <= 100 and _normal(line.strip()) not in repeated
    ]


def _ceo_title(title):
    return re.fullmatch(CEO_PATTERN, _normal(title).strip(), re.I) is not None


def build_plan(
    study,
    page_texts,
    *,
    max_environment_pages=8,
    max_evidence_pages=30,
    page_headings=None,
    page_primary_headings=None,
):
    """Rank readable candidates; uncertainty and exclusions remain explicit."""
    if type(max_environment_pages) is not int or not 1 <= max_environment_pages <= 10:
        raise ValueError("environment limit must be an integer in 1..10")
    if type(max_evidence_pages) is not int or not 10 <= max_evidence_pages <= 500:
        raise ValueError("evidence limit must be an integer in 10..500 (includes claims)")
    count = study["page_count"]
    roles, anchors, range_anchors = {}, {}, {}
    for section in study["sections"]:
        for p in range(section["start_page"], section["end_page"] + 1):
            roles[p] = section["role"]
            range_anchors[p] = section["anchors"]
        for anchor in section["anchors"]:
            anchors.setdefault(anchor["page"], []).append(anchor)
    conflicts = set(study["conflict_pages"])
    line_counts = Counter(
        line
        for text in page_texts.values()
        for line in {_normal(s.strip()) for s in text.splitlines() if 0 < len(s.strip()) <= 160}
    )
    repeated = {s for s, n in line_counts.items() if n >= max(3, count * 0.2)}
    # Front navigation labels should not turn every introductory page into a CEO message.
    ceo_counts = Counter(
        _normal(line)
        for p, text in page_texts.items()
        if p <= 20
        for line in set(_heading_lines(text, set()))
        if _ceo_title(line)
    )
    records, env, ceos, evidence, unreadable, boundary_resolved = [], [], [], [], [], []
    inherited_container = None
    for p in range(1, count + 1):
        text = page_texts.get(p, "")
        body = "\n".join(s for s in text.splitlines() if _normal(s.strip()) not in repeated)
        native_letters = len(re.findall(r"[a-zA-Z가-힣]", text))
        readable = native_letters >= 80 and text.count("(cid:") < max(1, len(text) // 100)
        if not readable:
            unreadable.append(p)
        headings = (
            [t for t in page_headings.get(p, []) if _normal(t) not in repeated]
            if page_headings is not None
            else _heading_lines(text, repeated)
        )
        heading = "\n".join(headings)
        anchor_titles = [a["title"] for a in anchors.get(p, [])]
        boundary_titles = [a["title"] for a in range_anchors.get(p, [])]
        groups = {
            g: len(re.findall(pattern, _normal(body), re.I)) for g, pattern in ENV_GROUPS.items()
        }
        hits = sum(groups.values())
        distinct = sum(bool(n) for n in groups.values())
        density = round(1000 * hits / max(200, len(body)), 4)
        source_role = roles.get(p, "unknown")
        toc = p <= 20 and any(
            re.fullmatch(r"contents?|table\s+of\s+contents|index|목차", t.strip(), re.I)
            for t in text.splitlines()
        )
        for title in headings if not toc else []:
            if re.fullmatch(
                r"esg\s*(?:data|fact\s*book)|fact\s*book|facts\s*&\s*figures", title, re.I
            ):
                inherited_container = "esg_data"
            elif re.fullmatch(r"appendi(?:x|ces)|부록|policy\s*book", title, re.I):
                inherited_container = "appendix"
            elif re.fullmatch(
                r"environment(?:al)?|planet|환경|social|people|governance|principle|"
                r"overview|introduction|our\s*company|사회|지배구조",
                title,
                re.I,
            ):
                inherited_container = None
        category, method, reasons = "unknown", "unclassified", []
        evidence_kind = next(
            (k for k, pattern in EVIDENCE_PATTERNS.items() if re.search(pattern, heading, re.I)),
            None,
        )
        ceo = p <= 20 and (
            any(_ceo_title(t) for t in anchor_titles)
            or any(
                _ceo_title(t) and (page_headings is not None or ceo_counts[_normal(t)] <= 2)
                for t in headings
            )
        )
        intro_ceo_hierarchy = (
            ceo
            and page_headings is not None
            and any(_ceo_title(t) for t in headings)
            and bool(boundary_titles)
            and all(
                _ceo_title(re.sub(r"\s*\d+$", "", title))
                or _normal(title).strip() in {"introduction", "overview", "회사 소개"}
                for title in boundary_titles
            )
        )
        if p in conflicts and not intro_ceo_hierarchy:
            category, reasons = "conflict", ["section_boundaries_disagree"]
        elif not readable:
            category, reasons = "unreadable", ["native_text_missing_or_unusable"]
        elif toc:
            category, reasons = "toc", ["navigation_is_not_claim_text"]
        elif evidence_kind or inherited_container or source_role in ("esg_data", "appendix"):
            category = evidence_kind or inherited_container or source_role
            method = "native_heading" if evidence_kind else "section_container"
            reasons = ["evidence_search_only", method]
            evidence.append(p)
        elif ceo:
            category, method = "ceo_message", "front_title_or_physical_destination"
            reasons = ["front_20_pages", "ceo_title", "claim_extraction_candidate"]
            ceos.append(p)
            if p in conflicts:
                boundary_resolved.append(p)
                reasons.append("scope_only_intro_ceo_hierarchy;original_conflict_preserved")
        elif len(body) >= 200 and hits >= 2 and source_role == "e_narrative":
            category, method = "e_narrative", "section_and_native_density"
            reasons = ["environmental_section", "readable_environmental_body"]
            env.append(p)
        elif (
            source_role != "other"
            and len(body) >= 200
            and distinct >= 2
            and hits >= 4
            and any(
                re.search(ENV_GROUPS["environment"] + "|" + ENV_GROUPS["climate"], t, re.I)
                for t in (
                    page_primary_headings.get(p, [])
                    if page_primary_headings is not None
                    else headings
                )
            )
        ):
            category, method = "e_narrative", "native_density_fallback"
            reasons = ["physical_page_heading", "environmental_density", "source_role_unresolved"]
            env.append(p)
        else:
            category = "other" if source_role == "other" else "unknown"
            reasons = ["insufficient_environmental_body_density"]
        snippet_title = next(
            (
                t
                for t in headings
                if (
                    _ceo_title(t)
                    if ceo
                    else evidence_kind and re.search(EVIDENCE_PATTERNS[evidence_kind], t, re.I)
                )
            ),
            None,
        )
        snippet_start = max(0, text.find(snippet_title) - 30) if snippet_title else 0
        records.append(
            dict(
                page=p,
                category=category,
                source_role=source_role,
                classification_method=method,
                reasons=reasons,
                snippet=text[snippet_start : snippet_start + 320],
                native_text_sha256=canonical_hash(text),
                environmental_density=density,
                environmental_hits=hits,
                environmental_groups=[g for g, n in groups.items() if n],
                claim_selected=False,
                evidence_selected=False,
            )
        )
    by_page = {r["page"]: r for r in records}
    ranked_env = sorted(
        env,
        key=lambda p: (
            -by_page[p]["environmental_density"],
            -len(by_page[p]["environmental_groups"]),
            -by_page[p]["environmental_hits"],
            p,
        ),
    )
    selected_ceos = sorted(ceos)[:2]
    selected_env = ranked_env[: min(max_environment_pages, 10 - len(selected_ceos))]
    # Never run CEO-only as a successful environmental scope.
    selected_claims = sorted(selected_ceos + selected_env) if selected_env else []
    priority = {
        "assurance": 0,
        "gri_index": 1,
        "environmental_data": 2,
        "esg_data": 3,
        "appendix": 4,
    }
    ranked_evidence = sorted(
        evidence,
        key=lambda p: (priority[by_page[p]["category"]], -by_page[p]["environmental_density"], p),
    )
    selected_evidence = (
        sorted(selected_claims + ranked_evidence[: max_evidence_pages - len(selected_claims)])
        if selected_claims
        else []
    )
    for record in records:
        p = record["page"]
        record["claim_selected"] = p in selected_claims
        record["evidence_selected"] = p in selected_evidence
        if p in env + ceos + evidence and p not in selected_evidence:
            record["reasons"].append(
                "excluded_by_declared_cap" if selected_claims else "scope_failed_no_paid_dispatch"
            )
    plan = dict(
        version=VERSION,
        status="candidate_only" if selected_claims else "failed",
        source_path=study["source_path"],
        source_sha256=study["source_sha256"],
        page_count=count,
        policy_sha256=POLICY_SHA256,
        settings=dict(
            max_environment_pages=max_environment_pages,
            max_claim_pages=10,
            max_ceo_pages=2,
            max_evidence_pages=max_evidence_pages,
            evidence_cap_semantics="total_union_including_claim_pages",
        ),
        section_policy_sha256=POLICY_HASH,
        section_map_sha256=study.get("map_sha256"),
        method=VERSION,
        sections_method=study["method"],
        issues=study["issues"],
        ceo_candidate_pages=sorted(ceos),
        environmental_candidate_pages=sorted(env),
        claim_candidate_pages=sorted(ceos + env),
        evidence_candidate_pages=sorted(ceos + env + evidence),
        selected_claim_pages=selected_claims,
        selected_evidence_pages=selected_evidence,
        evidence_only_pages=sorted(set(selected_evidence) - set(selected_claims)),
        excluded_claim_candidate_pages=sorted(set(ceos + env) - set(selected_claims)),
        excluded_evidence_candidate_pages=sorted(
            set(ceos + env + evidence) - set(selected_evidence)
        ),
        unknown_pages=list(study["unknown_pages"]),
        conflict_pages=sorted(conflicts),
        unreadable_pages=unreadable,
        scope_boundary_resolved_pages=boundary_resolved,
        other_candidate_pages=study["other_candidate_pages"],
        failure_reasons=[] if selected_claims else ["NO_READABLE_ENVIRONMENTAL_NARRATIVE"],
        suggested_front_pages=[] if selected_claims else list(range(1, min(3, count) + 1)),
        pages=records,
        declared_subset=True,
        source_quality="unverified",
        parser_versions=study.get("parser_versions", {}),
        live_model="not_run",
        limitations=[
            "Native snippets and density are scope proposals, never verified evidence.",
            "Unknown/conflict/unreadable pages remain unresolved, never evidence absence.",
            "Declared subset: excluded pages were not analyzed; no full-report completion.",
            "CEO title heuristics may miss untitled messages; scan OCR is not performed.",
            "Edit only selected_claim_pages/selected_evidence_pages; validate source before use.",
        ],
    )
    plan["plan_sha256"] = canonical_hash(plan)
    return plan


def inspect(pdf: Path, *, max_environment_pages=8, max_evidence_pages=30):
    """Original bytes only. A section-reader failure becomes explicit native fallback."""
    if pdf.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("local scope study limit: 100 MiB")
    with pdf.open("rb") as stream:
        digest = file_digest(stream, "sha256").hexdigest()
    reader = PdfReader(pdf)
    if reader.is_encrypted:
        raise ValueError("encrypted input requires the existing ingest gate")
    count = len(reader.pages)
    if not 1 <= count <= 500:
        raise ValueError("local scope study limit: 500 pages")
    try:
        study = inspect_sections(pdf)
    except ValueError:
        raise  # Includes changed-source and input gates; never recover those.
    except Exception as error:
        study = build_map(count, [])
        study.update(
            source_path=str(pdf.resolve()),
            source_sha256=digest,
            page_count=count,
            method="native_fallback_section_reader_failed",
            issues=[dict(kind="section_reader_failed", error_type=type(error).__name__)],
            parser_versions={name: version(name) for name in ("pypdf", "pdfplumber")},
        )
    texts, headings, primary = {}, {}, {}
    for number, page in enumerate(reader.pages, 1):
        try:
            runs = []

            def visitor(text, cm, tm, font, size):
                effective = size * math.hypot(tm[0], tm[1]) * math.hypot(cm[0], cm[1])
                if text.strip() and math.isfinite(effective) and effective > 0:
                    runs.append((effective, text.strip()))

            texts[number] = page.extract_text(visitor_text=visitor) or ""
            body_size = median(s for s, t in runs) if runs else 0
            headings[number] = list(
                dict.fromkeys(
                    t
                    for size, text in runs
                    for t in text.splitlines()
                    if 0 < len(t) <= 100
                    and size >= (12 if _ceo_title(t) else max(12, body_size * 1.15))
                )
            )
            title_sizes = [size for size, text in runs if re.search(r"[a-zA-Z가-힣]", text)]
            main_size = max(title_sizes, default=0)
            primary[number] = [
                t
                for size, text in runs
                for t in text.splitlines()
                if t in headings[number] and size >= max(12, main_size * 0.75)
            ]
        except Exception as error:
            texts[number] = ""
            study["issues"].append(
                dict(kind="native_text_unreadable", page=number, error_type=type(error).__name__)
            )
    with pdf.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("source changed during scope inspection")
    if study["source_sha256"] != digest:
        raise ValueError("source changed during section inspection")
    return build_plan(
        study,
        texts,
        max_environment_pages=max_environment_pages,
        max_evidence_pages=max_evidence_pages,
        page_headings=headings,
        page_primary_headings=primary,
    )


def validate_selection(plan, source_sha256, page_count):
    """Allow selection edits only; revalidate immutable proposal and physical bounds."""
    if not isinstance(plan, dict):
        raise ValueError("scope-plan must be a JSON object")
    if plan.get("version") != VERSION or plan.get("policy_sha256") != POLICY_SHA256:
        raise ValueError("unsupported scope policy")
    if plan["source_sha256"] != source_sha256 or plan["page_count"] != page_count:
        raise ValueError("scope source identity mismatch")
    # Reconstruct the original selection before checking the immutable proposal hash.
    original = {k: v for k, v in plan.items() if k != "plan_sha256"}
    original["selected_claim_pages"] = [r["page"] for r in plan["pages"] if r["claim_selected"]]
    original["selected_evidence_pages"] = [
        r["page"] for r in plan["pages"] if r["evidence_selected"]
    ]
    if canonical_hash(original) != plan["plan_sha256"]:
        raise ValueError("immutable scope proposal changed; edit only selected page lists")
    claims, evidence = plan["selected_claim_pages"], plan["selected_evidence_pages"]
    for selected in (claims, evidence):
        if (
            not isinstance(selected, list)
            or not selected
            or any(type(p) is not int or not 1 <= p <= page_count for p in selected)
            or selected != sorted(set(selected))
        ):
            raise ValueError("selection must be sorted unique physical pages")
    if len(claims) > 10 or len(evidence) > plan["settings"]["max_evidence_pages"]:
        raise ValueError("scope exceeds declared page cap")
    if not set(claims) <= set(evidence):
        raise ValueError("claim pages must be a subset of evidence pages")
    categories = {r["page"]: r["category"] for r in plan["pages"]}
    if sum(categories.get(p) == "ceo_message" for p in claims) > 2:
        raise ValueError("scope exceeds two CEO pages")
    if any(categories.get(p) not in ("ceo_message", "e_narrative") for p in claims):
        raise ValueError("evidence-only or unresolved page cannot be a claim page")
    if any(categories.get(p) in ("conflict", "unreadable", "unknown", "toc") for p in evidence):
        raise ValueError("unresolved page requires a new inspected proposal")
    applied = dict(
        pages=list(evidence),
        claim_pages=list(claims),
        declared_subset=True,
        excluded_claim_candidate_pages=sorted(set(plan["claim_candidate_pages"]) - set(claims)),
        excluded_evidence_candidate_pages=sorted(
            set(plan["evidence_candidate_pages"]) - set(evidence)
        ),
        proposal_sha256=plan["plan_sha256"],
    )
    applied["selection_sha256"] = canonical_hash(applied)
    return applied


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pdf", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--environment-pages", type=int, default=8)
    cli.add_argument("--evidence-pages", type=int, default=30)
    args = cli.parse_args()
    plan = inspect(
        args.pdf,
        max_environment_pages=args.environment_pages,
        max_evidence_pages=args.evidence_pages,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                k: plan[k]
                for k in (
                    "status",
                    "selected_claim_pages",
                    "selected_evidence_pages",
                    "failure_reasons",
                    "suggested_front_pages",
                )
            },
            ensure_ascii=False,
        )
    )
    return 0 if plan["status"] == "candidate_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
