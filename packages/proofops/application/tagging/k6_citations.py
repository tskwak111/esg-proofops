"""Restore repeated units only through model-selected adjacent scalar anchors."""

import re

from proofops.application.ingest.k6_coverage import UNIT
from proofops.application.tagging.pb6_citation_restore import POLICY as OLD_POLICY

POLICY = OLD_POLICY | dict(
    profile="citation-selected-adjacent-unit-k6-v1",
    repeated_unit="preceding-selected-unique-whole-number-same-catalog; exact-adjacent-whitespace",
    credit="restore-literal-only; existing-source-binding-and-semantic-guards-required",
)
RISK_POLICY = dict(
    profile="risk-need-not-commitment-k6-v1",
    action="goal-vote-with-uncommitted-need-is-review; never-convert-to-management-or-absence",
    trigger=r"필요성\s*(?:증가|증대|확대)|필요(?:가|성이)\s*(?:커|높|증)",
    commitment=r"목표(?:로|를|입니다|이다)|계획(?:입니다|이다|으로|을|하고)|예정|추진(?:하고|할)|(?:도입|투자|전환|확대|달성)하(?:겠|기로)|(?:도입|투자|전환|확대|달성)할\s*(?:계획|방침)",
)


def risk_without_commitment(quote):
    return bool(
        re.search(RISK_POLICY["trigger"], quote) and not re.search(RISK_POLICY["commitment"], quote)
    )


def anchor_units(selected, refs):
    result = []
    for index, choice in enumerate(selected):
        fixed = choice
        if (
            isinstance(choice, dict)
            and set(choice) == {"id", "quote"}
            and UNIT.fullmatch(choice["quote"])
        ):
            raw = refs.get(choice["id"], {}).get("quote", "")
            previous = selected[index - 1] if index else None
            if (
                isinstance(previous, dict)
                and previous.get("id") == choice["id"]
                and re.fullmatch(r"[+−-]?\d+(?:[,.]\d+)*", previous.get("quote", ""))
            ):
                number = previous["quote"]
                scalar = rf"(?<![\d.,+−-]){re.escape(number)}(?![\d.,%])"
                pattern = scalar + rf"\s+{re.escape(choice['quote'])}(?![A-Za-z0-9₂³/])"
                matches = list(re.finditer(pattern, raw))
                if len(matches) == 1 and len(list(re.finditer(scalar, raw))) == 1:
                    fixed = choice | dict(quote=matches[0][0])
        result.append(fixed)
    return result
