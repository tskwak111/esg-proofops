"""Native-text ranking hints only: no claim extraction or evidence admission."""

import re
import unicodedata
from typing import TypedDict

ENVIRONMENT = (
    r"기후|탄소|온실가스|배출|에너지|전력|재생|태양광|용수|수자원|폐기물|재활용|"
    r"생물다양성|오염|환경경영|climate|carbon|emission|energy|renewable|water|"
    r"waste|recycl|biodiversity|pollution|scope\s*[123]"
)
PATTERNS = {
    "target_year": r"(?<!\d)20[3-9]\d(?!\d)",
    "metric": (
        r"\d[\d,.]*\s*(?:tco2[- ]?(?:eq?|e)?|mwh|gwh|kwh|mw|톤|천\s*m3|%)|"
        r"(?:tco2[- ]?(?:eq?|e)?|mwh|gwh|kwh|톤|천\s*m3|%)\s+\d[\d,.]*"
    ),
    "implementation": (
        r"수립|운영|도입|개발|설치|구축|전환|감축|절감|확대|이행|달성|시행|감독|"
        r"implement|operat|install|develop|reduc|achiev|transition"
    ),
    "named_means": r"\bppa\b|\brec\b|re100|iso\s*14001|위원회|전담|협의체|로드맵|roadmap",
}
HEADING = (
    r"목표|성과|전략|거버넌스|정책|체계|관리|활동|strategy|governance|"
    r"target|progress|approach|performance|action"
)
TABLE_UNIT = r"tco2[- ]?(?:eq?|e)?|mwh|gwh|kwh|천\s*m3|톤|%"
ASSURANCE = (
    r"limited\s+assurance|reasonable\s+assurance|moderate\s+assurance|"
    r"independent\s+(?:limited\s+)?assurance|aa1000as|isae\s*3000|"
    r"제\s*3\s*자\s*(?:검증|보증)|제3자\s*(?:검증|보증)|"
    r"제한적\s*(?:검증|보증)|외부\s*(?:검증|보증)"
)
WEIGHTS_CAPS = {
    "target_year": [3, 4],
    "metric": [2, 8],
    "implementation": [2, 12],
    "named_means": [2, 6],
    "heading": [2, 3],
    "table_rows": [3, 4],
}
POLICY = {
    "environment_pattern": ENVIRONMENT,
    "patterns": PATTERNS,
    "heading_pattern": HEADING,
    "table_unit_pattern": TABLE_UNIT,
    "context_chars": 120,
    "weights_caps": WEIGHTS_CAPS,
    "density_tiebreak": "legacy_density_groups_hits_page",
    "normalization": "NFKC_casefold_whitespace_join",
    "table_density": "environment_metric_unit_line_with_3_numeric_cells; cap_4_rows",
    "native_subheading": "short_body_line_up_to_60_chars; unique_headings; cap_3",
}


class SourceSupportPolicy(TypedDict):
    version: str
    assurance_pattern: str
    metric_environment_context_chars: int
    max_metric_to_assurance_chars: int
    bonus: int
    scope: str


SOURCE_SUPPORT_POLICY: SourceSupportPolicy = {
    "version": "same-page-quantified-assurance-v1",
    "assurance_pattern": ASSURANCE,
    "metric_environment_context_chars": 120,
    "max_metric_to_assurance_chars": 900,
    "bonus": 24,
    "scope": "one physical page; ranking hint only; never evidence admission",
}


def claim_signals(body: str, headings: list[str]) -> tuple[int, dict[str, int]]:
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", body).casefold())
    signals = {}
    for name, pattern in PATTERNS.items():
        signals[name] = sum(
            bool(re.search(ENVIRONMENT, text[max(0, m.start() - 120) : m.end() + 120]))
            for m in re.finditer(pattern, text)
        )
    lines = [unicodedata.normalize("NFKC", line).casefold().strip() for line in body.splitlines()]
    titles = set(headings) | {line for line in lines if 0 < len(line) <= 60}
    signals["heading"] = sum(bool(re.search(HEADING, h, re.I)) for h in titles)
    signals["table_rows"] = sum(
        bool(re.search(ENVIRONMENT, line))
        and bool(re.search(TABLE_UNIT, line))
        and len(re.findall(r"(?<!\w)\d[\d,.]*", line)) >= 3
        for line in lines
    )
    score = sum(weight * min(signals[name], cap) for name, (weight, cap) in WEIGHTS_CAPS.items())
    return score, signals


def claim_support_signals(body: str, headings: list[str]) -> tuple[int, dict[str, int]]:
    """Boost an environmental metric page only when assurance text is nearby on that page.

    The caller supplies one physical page at a time. This score helps choose pages for
    inspection; it does not bind a claim to an assurance statement or verify evidence.
    """
    score, signals = claim_signals(body, headings)
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", body).casefold())
    metric_positions = [
        match.start()
        for match in re.finditer(PATTERNS["metric"], text)
        if re.search(
            ENVIRONMENT,
            text[
                max(
                    0, match.start() - SOURCE_SUPPORT_POLICY["metric_environment_context_chars"]
                ) : match.end() + SOURCE_SUPPORT_POLICY["metric_environment_context_chars"]
            ],
        )
    ]
    assurance_positions = [match.start() for match in re.finditer(ASSURANCE, text, re.I)]
    paired = int(
        any(
            abs(metric - assurance) <= SOURCE_SUPPORT_POLICY["max_metric_to_assurance_chars"]
            for metric in metric_positions
            for assurance in assurance_positions
        )
    )
    signals["same_page_quantified_assurance"] = paired
    return score + SOURCE_SUPPORT_POLICY["bonus"] * paired, signals
