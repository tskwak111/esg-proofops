"""Opt-in lexical candidates over literal source text, never verified evidence.

Shared subjects/predicates stay in parent context. Each selectable atom has its
own disjoint offsets; no rewritten quote, inferred year or table join is minted.
Table axes must come from the caller's resolved same-table structural sources.
This deliberately conservative planner is not a semantic classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PROFILE = "extraction-atomic-v2"
PROFILE_V3 = "extraction-atomic-v3"
ENVIRONMENT = (
    r"환경|기후|탄\s*소|온실가스|Scope\s*[123]|CO2|CCS|수소|배출량|배출권|에너지|재생|재활용|용수|폐수|폐기물|생물다양성|"
    r"생태|오염|넷\s*제로|RE100|공정가스|대체가스|스크러버|태양광|전력|"
    r"carbon|emission|energy|water|waste|recycl|biodivers|net.zero|renewable|solar"
)
METRIC = (
    r"넷\s*제로|RE100|탄소중립|온실가스|배출량|재생에너지|에너지\s*(?:사용|소비)|"
    r"전력|용수|폐수|폐기물|재활용률|태양광|carbon|emission|renewable|water|waste"
)
ASSERTION = (
    r"목표|계획|달성|감축|감소|절감|저감|유지|도입|운영|설치|구축|수립|개발|"
    r"적용|추진|확대|전환|준공|생산|공급|건설|인증|모니터링|분석|평가|관리|"
    r"참여|이행|검토|감독|결의|점검|신설|취득|가입|의사결정|의결|기구|승인|수행|범위|발굴|선별|확보|"
    r"target|commit|achiev|reduc|implement|install|operat|certif"
)
UNIT = r"%|tCO2(?:-eq|e)?|톤|MWh|GWh|kWh|TJ|GJ|MW|kW|㎥|m3|m³|리터"
YEAR = r"(?<!\d)(?:19|20)\d{2}\s*년?(?!\d)"
NONCLAIM = (
    r"\b(?:GRI|TCFD|SASB)\s*(?:\d|INDEX|색인)|색인|범례|^단위\s*[:：]|"
    r"알려져\s*있|일반적으로|이란\s|을\s*의미합니다|means\b|is defined as"
)
ASSURANCE = r"검증인|검증기관|보증기관|assurance provider|auditor"
PROCEDURE = r"표본|인터뷰|독립성|책임|검증\s*범위|보증\s*범위|한계|절차|의견|sampling"
BOUNDARY = r".+?(?:[.!?](?=\s|$)|\n\s*\n|$)"
ROW_BOUNDARY = r".+?(?:[.!?](?=\s|$)|\n+|$)"
CONNECTIVE = (
    r"(?:했으며|하였으며|하였고|했고|하고\s*있으며|하고\s*있고|하였으나|했으나)\s*,?\s+|"
    r"중으로\s+|;\s+|,\s+(?=(?:19|20)\d{2}\s*년(?:까지|부터))"
)
# V3 adds completed award/recognition predicates so a sentence such as
# "에너지위너상을 수상하여 ... 인정받았으며, ISO 14001 인증을 ..." is split
# before the ISO assertion. V2's selector and policy bytes remain unchanged.
CONNECTIVE_V3 = r"(?:받았으며|받았고)\s*,?\s+"
TARGET_YEAR = r"(?<!\d)(?:19|20)\d{2}\s*년(?:까지|부터)"
CONJUNCTION = r"\s+(?:및|and)\s+"
QUANTITY = r"\d[\d,.]*\s*(?:천|만|억)?\s*(?:" + UNIT + r")"
STATUS = r"(?:했다|한다|습니다|합니다|입니다|하였다|됩니다|하고\s*있|함\b|중\b|받았|취득|선별하되)"
# These referents can require preceding climate context. Admission is only a
# chance to review the literal span, never approval of environmental attribution.
CONTEXT_DEPENDENT = (
    r"(?:MCM|지속가능경영위원회|PPA).*(?:검토|승인|상정|확대|추진)|"
    r"^\s*\d+[)）].*(?:19|20)\d{2}\s*년.*\d+\s*대\s*전환"
)
PURPOSE = r"(?:을|를|기)\s*위해|(?:을|를)\s*위한|목적으로"
PURPOSE_PRIOR_PREDICATE = r"하고|하며|했|하였|목표로"
POLICY = {
    "profile": PROFILE,
    "environment": ENVIRONMENT,
    "metric": METRIC,
    "assertion": ASSERTION,
    "unit": UNIT,
    "year": YEAR,
    "nonclaim": NONCLAIM,
    "assurance": ASSURANCE,
    "procedure": PROCEDURE,
    "boundary": BOUNDARY,
    "row_boundary": ROW_BOUNDARY,
    "connective": CONNECTIVE,
    "target_year": TARGET_YEAR,
    "conjunction": CONJUNCTION,
    "quantity": QUANTITY,
    "status": STATUS,
    "context_dependent": CONTEXT_DEPENDENT,
    "purpose": PURPOSE,
    "purpose_prior_predicate": PURPOSE_PRIOR_PREDICATE,
    "source_policy": "literal-disjoint-atoms-parent-context-only-resolved-table-axes-v2",
}
POLICY_V3 = {
    **POLICY,
    "profile": PROFILE_V3,
    "additional_connective": CONNECTIVE_V3,
    "binding_policy": "same-source-exact-claim-edge-whitespace-v1",
    "source_policy": "literal-disjoint-atoms-explicit-recognition-split-v3",
}


@dataclass(frozen=True)
class AtomicCandidate:
    start: int
    end: int
    parent_start: int
    parent_end: int
    kind: str
    context_dependent: bool = False


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def _quantity(text: str) -> bool:
    return _has(QUANTITY, text)


def _eligible(text: str, kind: str, table_context: tuple[str, ...]) -> bool:
    if _has(NONCLAIM, text):
        return False
    if (
        _has(ASSURANCE, text)
        and _has(PROCEDURE, text)
        and not (
            _quantity(text)
            and _has(YEAR, text)
            and _has(r"배출량은|배출량\s*[:：]|emissions were", text)
        )
    ):
        return False
    if (kind == "table_cell" or table_context) and re.fullmatch(
        r"[\d,.+−\s-]+\s*(?:" + UNIT + r")?", text, re.I
    ):
        axes = " ".join(table_context)
        return (
            bool(table_context)
            and all(_has(p, axes) for p in (ENVIRONMENT, YEAR))
            and _has(UNIT, axes + " " + text)
        )
    if not _has(ENVIRONMENT, text) and not _has(CONTEXT_DEPENDENT, text):
        return False
    # A metric + year + quantity is a disclosure even without a prose predicate.
    if _quantity(text) and _has(YEAR, text):
        return True
    if not _has(ASSERTION, text):
        return False
    # Bare topic headings and slogans are not assertions. A dated/status target,
    # a conjugated action or a named implemented means is selectable.
    return bool(
        _has(YEAR, text)
        or _quantity(text)
        or _has(STATUS, text)
        or _has(
            r"(?:시스템|설비|공정|위원회|ISO\s*14001|대체가스).*(?:도입|운영|구축|적용|인증)", text
        )
    )


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    fragment = text[start:end]
    return start + len(fragment) - len(fragment.lstrip()), end - len(fragment) + len(
        fragment.rstrip()
    )


def atomic_candidates(
    text: str,
    *,
    kind: str = "paragraph",
    table_context: tuple[str, ...] = (),
    diagnostics: dict[str, int] | None = None,
    policy_version: int = 2,
) -> tuple[AtomicCandidate, ...]:
    """Plan candidates; line wraps remain literal inside their parent sentence.

    No global evidence or coordinate inference. Separate bare chart labels/value
    blocks remain unknown unless a parser provided actual table axes. Connective
    cuts require assertions on both sides; metric enumeration cuts require two
    independent metric names, so Scope 1/2 and lists of means stay together.
    """
    if type(policy_version) is not int or policy_version not in (2, 3):
        raise ValueError("ATOMIC_CANDIDATE_POLICY_UNSUPPORTED")
    connectives = (CONNECTIVE, CONNECTIVE_V3) if policy_version == 3 else (CONNECTIVE,)
    result = []
    counts = dict.fromkeys(
        (
            "parent_count",
            "gate_rejected_count",
            "eligible_parent_count",
            "candidate_count",
            "context_dependent_count",
        ),
        0,
    )
    # Explicit row delimiters prove row boundaries; prose PDF wraps do not.
    boundary = (
        ROW_BOUNDARY
        if kind in ("table", "table_row", "figure") and ("\t" in text or "|" in text)
        else BOUNDARY
    )
    previous_start = 0
    previous_value = ""
    for parent in re.finditer(boundary, text, re.S):
        start, end = _trim(text, parent.start(), parent.end())
        if start >= end:
            continue
        value = text[start:end]
        counts["parent_count"] += 1
        parent_start = start
        dependent = not _has(ENVIRONMENT, value) and _has(CONTEXT_DEPENDENT, value)
        if dependent and _has(ENVIRONMENT, previous_value) and not _has(NONCLAIM, previous_value):
            parent_start = previous_start
        previous_start, previous_value = start, value
        if not _eligible(value, kind, table_context):
            counts["gate_rejected_count"] += 1
            continue
        counts["eligible_parent_count"] += 1
        cuts = {start, end}
        for connective in connectives:
            for match in re.finditer(connective, value):
                before, after = value[: match.end()], value[match.end() :]
                if _has(ASSERTION, before) and (_has(ASSERTION, after) or _quantity(after)):
                    cuts.add(start + match.end())
        years = list(re.finditer(TARGET_YEAR, value))
        for year in years[1:]:
            cuts.add(start + year.start())
        # Shared predicates/years remain available as parent context on the wire.
        major = sorted(cuts)
        for left, right in zip(major, major[1:]):
            part = text[left:right]
            for match in (
                re.finditer(CONJUNCTION, part) if (_has(YEAR, value) or _quantity(value)) else ()
            ):
                following = part[match.end() :]
                purpose = re.search(PURPOSE, following)
                if purpose and not _has(PURPOSE_PRIOR_PREDICATE, following[: purpose.start()]):
                    continue
                if _has(METRIC, part[: match.start()]) and _has(METRIC, part[match.end() :]):
                    cuts.add(left + match.end())
        ordered = sorted(cuts)
        for left, right in zip(ordered, ordered[1:]):
            a, b = _trim(text, left, right)
            if a < b:
                result.append(AtomicCandidate(a, b, parent_start, end, kind, dependent))
                counts["context_dependent_count"] += int(dependent)
    counts["candidate_count"] = len(result)
    if diagnostics is not None:
        diagnostics.update(counts)
    return tuple(result)
