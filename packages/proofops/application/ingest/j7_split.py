"""Conservative independent clauses inside already selected J3 source spans."""

import re

from proofops.application.ingest.j3_recall import ACTION
from proofops.application.ingest.j3_recall import POLICY as J3_POLICY
from proofops.application.ingest.j3_recall import refine_selected as refine_j3

PROFILE = "j7-independent-clauses-v1"
PREDICATE = ACTION + r"|도입|투자|검토|검증|달성|구체화|선언|수행"
BOUNDARY = (
    rf"(?P<action>{PREDICATE})(?:하고\s+있으며|하고|하며|했으며),\s+"
    rf"|(?P<bare>{PREDICATE})하고\s+"
    r"|(?P<comparison>예정으로),\s+(?=이는\s)"
)
FORECAST = r"\d[\d,.]*\s*(?:%|퍼센트|톤|tCO2|kWh|MWh|GWh).*?(?:예상|기대|전망)"
DEPENDENT = r"(?:이를|이로|이에|그에|이러한|그러한|이를\s*통해)"
CONDITION = r"(?:\s시\s|경우|조건|(?:한다면|하면|되면|된다면))"
COMPARISON = r"^이는\s.+?\d+\s*년\s*앞선\s*목표"
POLICY = dict(
    profile=PROFILE,
    parent=J3_POLICY,
    boundary=BOUNDARY,
    forecast=FORECAST,
    dependent=DEPENDENT,
    shared_condition=CONDITION,
    comparison=COMPARISON,
    repeated_means="keep-repeated-completion-and-governor-detail-together",
    scope="selected-claim-only; literal-disjoint-subspans; no-neighbour-completion",
    conditions="preserve-full-condition-clause; no-split-at-causal-or-conditional-connectives",
    expectations="numeric-forecast-only; qualitative-expectation-stays-with-means",
    nesting="no-boundaries-inside-quotations-brackets-or-parentheses",
    evidence="reverify-each-new-source; no-parent-tags-track-year-or-verification-inheritance",
    fallback="keep-parent-on-incomplete-child-or-validation-failure; no-truncation",
    max_candidates=64,
)
CONTEXT_POLICY = dict(
    profile="j7-connected-sentence-context-k4-v1",
    atomic="unchanged-J7-focal-spans-and-identities",
    interpretation="same-block-complete-bullet-or-sentence; no-cross-bullet-or-paragraph",
    credit="interpretation-only; no-dimension-or-element-credit",
    goal="connecting-clause-without-explicit-future-marker-requires-retag",
)


def sentence_context(claim, graph):
    """Retain the whole literal sentence behind a connective atomic clause."""
    from dataclasses import asdict

    from proofops.application.evidence.span_citations import verify_source_ref

    if len(claim.source_refs) != 1 or claim.tenant_id != graph.tenant_id:
        return None
    ref = claim.source_refs[0]
    block = next((b for b in graph.blocks if b.source_id == ref.source_id), None)
    if (
        block is None
        or block.kind != "paragraph"
        or block.winner is None
        or verify_source_ref(ref, graph, tenant_id=graph.tenant_id).verification_state != "verified"
    ):
        return None
    text = block.raw_text
    boundaries = {0, len(text)}
    for match in re.finditer(r"(?<!\S)[•▪▶]|\n\s*\n|[.!?。！？](?=\s|$)", text):
        boundaries.add(match.start() if match[0] in {"•", "▪", "▶"} else match.end())
    start = max(x for x in boundaries if x <= ref.char_start)
    end = min(x for x in boundaries if x >= ref.char_end)
    while start < ref.char_start and text[start].isspace():
        start += 1
    while end > ref.char_end and text[end - 1].isspace():
        end -= 1
    quote = text[start:end]
    if not re.search(r"하고|하며|있으며|했으며|예정으로", quote):
        return None
    if end - start == ref.char_end - ref.char_start or len(quote) > 2000:
        return None
    whole = block.source_ref(normalized_char_start=start, normalized_char_end=end)
    checked = verify_source_ref(whole, graph, tenant_id=graph.tenant_id)
    return dict(
        policy=CONTEXT_POLICY,
        text=quote,
        source_ref=asdict(whole),
        verification_state=checked.verification_state,
        role="parent_paragraph",
        rule_credit=False,
    )


def goal_requires_retag(claim, graph):
    context = sentence_context(claim, graph)
    return bool(
        context
        and not re.search(
            r"목표|계획|예정|예상|전망|기대|(?:19|20)\d{2}년.*(?:까지|달성)", context["text"]
        )
    )


def _top_level(text):
    """Allowed cut positions; unclosed or nested quotations stay conservative."""
    pairs = {"(": ")", "[": "]", "{": "}", "‘": "’", "“": "”", "'": "'", '"': '"'}
    stack: list[str] = []
    allowed = {0}
    for index, char in enumerate(text):
        if stack and char == stack[-1]:
            stack.pop()
        elif char in pairs:
            stack.append(pairs[char])
        if not stack:
            allowed.add(index + 1)
    return allowed


def clause_bounds(text, start, end):
    value = text[start:end]
    allowed = _top_level(value)
    cuts = []
    for match in re.finditer(BOUNDARY, value):
        if match.start() not in allowed or match.end() not in allowed:
            continue
        action = match["action"] or match["bare"]
        right = value[match.end() :]
        # A leading condition can govern both clauses. Copying it would invent
        # overlapping citations; removing it changes the forecast. Keep its parent.
        if re.search(CONDITION, value[: match.end()]):
            continue
        if action == "총괄" or (action == "완료" and "완료" in right):
            continue
        if re.match(DEPENDENT, right):
            continue
        numeric_forecast = re.search(FORECAST, right)
        if re.search(r"예상|기대|전망", right) and not numeric_forecast:
            continue
        if match["bare"] and action != "반영" and not numeric_forecast:
            continue
        cuts.append(start + match.end())
    parts = []
    for a, b in zip([start, *cuts], [*cuts, end]):
        chunk = text[a:b]
        a += len(chunk) - len(chunk.lstrip())
        b -= len(chunk) - len(chunk.rstrip())
        parts.append((a, b))
    if any(
        len(text[a:b].strip("• ,\t\n")) < 8
        or not (re.search(PREDICATE, text[a:b]) or re.search(COMPARISON, text[a:b]))
        or re.search(r"(?:위한|대한|및|또는|의|을|를)\s*[,]?\s*$", text[a:b])
        for a, b in parts
    ):
        return [(start, end)]
    return parts


def refine_selected(spans, text, *, kind, cells=None):
    output, changes = [], []
    for original in spans:
        if original.get("kind", "claim") != "claim":
            output.append(original)
            continue
        parents, ancestry = refine_j3([original], text, kind=kind, cells=cells)
        changes.extend(ancestry)
        for span in parents:
            a, b = span["char_start"], span["char_end"]
            bounds = clause_bounds(text, a, b) if kind == "paragraph" else [(a, b)]
            output.extend(dict(span, char_start=x, char_end=y, quote=text[x:y]) for x, y in bounds)
            if bounds != [(a, b)]:
                changes.append(
                    dict(
                        parent_start=a,
                        parent_end=b,
                        children=[dict(char_start=x, char_end=y) for x, y in bounds],
                    )
                )
    if len(output) > POLICY["max_candidates"] and len(output) > len(spans):
        return spans, []
    return output, changes
