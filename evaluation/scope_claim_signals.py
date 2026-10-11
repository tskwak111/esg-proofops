"""Native-text ranking hints only: no claim extraction or evidence admission."""

import re
import unicodedata

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
