"""DEC-24 user interpretation; tagging guidance and table-context filtering only."""

import re

from proofops.application.tagging.quality import ELEMENT_DEFINITIONS
from proofops.application.tagging.semantic_admission import DEFINITIONS as W8_DEFINITIONS
from proofops.domain.provenance import canonical_hash

DEFINITIONS = (
    ELEMENT_DEFINITIONS
    + """
DEC-24 (user '추천대로', 2026-10-11; domain-owner confirmation pending):
G2 = target value/metric. A baseline emissions '수준 유지/관리' target can
support G2 only when the baseline year AND literal baseline value are in the
same sentence as that target. Cite that original sentence and select the exact
baseline value as normalized_value; never rewrite maintenance into a reduction
percentage, copy another sentence's value/year, or invent a target deadline.
A maintenance intention without both local year and value remains unknown.
G3/G4 use the existing same-sentence/same-table direct-source contract for
non-GHG metrics too; no document-wide numerical/year credit.
M1/M2/P2 context may clarify a pronoun or omitted subject only inside the same
paragraph with an explicitly continuous subject. A company name or year from
another paragraph/page is never attributable context. The current source/binding
guard is deliberately more conservative: this guidance never authorizes a new
cross-source binding or PC1 opt-in binding. Unsupported attribution stays unknown.
Policy declarations remain management claim candidates. Numbered table notes
are table context, never standalone claims. These are extraction/tagging
interpretations only; Python calculates grades. Preserve exact quotations,
unknown/conflict/unreadable, source verification and independent replicas.
""".rstrip()
)
DEFINITIONS_HASH = canonical_hash(DEFINITIONS)
# A separate prompt identity composes the approved interpretations. Historical
# DEC-24 and W8 strings/hashes above remain unchanged.
INTEGRATED_DEFINITIONS = DEFINITIONS + "\n" + W8_DEFINITIONS
INTEGRATED_DEFINITIONS_HASH = canonical_hash(INTEGRATED_DEFINITIONS)
INTEGRATED_V2_DEFINITIONS = " ".join(
    """
I1/QI1/W8/DEC-24: tagging only; Python grades.
M1: named means/standard or concrete operation; keep real means amid intent.
Support/effort/consideration/exploration/possibility/opportunity/intent-to-plan
alone -> unknown, never willingness_only/absence.
M2: explicit organization/facility/division/legal entity; 전사/domestic/named/
specified groups count. Time/risk/material/quantity or 사업장별 영향 do not.
P2: explicit previous/base-year comparison, not merely reporting year.
G6: transition means (PPA/generation/roadmap), not target declaration; never
borrow next paragraph's plan. Preserve G2 conflict.
G2 수준 유지/관리: BOTH baseline year AND literal value in SAME sentence;
cite value exactly, otherwise unknown. No invented reduction/deadline or
other-sentence numbers/years.
G3/G4 non-GHG: same-sentence/table direct evidence; no global numbers/years.
M1/M2/P2 omitted subject: same paragraph, explicit subject continuity only;
no company/year from another paragraph/page, PC1 or cross-source widening;
keep stricter binding.
Policy declarations stay claims; numbered table notes=context. Scope3
emissions_estimate items stay held independently of P1.
Preserve quotes/source approval/replicas/unknown/conflict/unreadable;
no absence authority or new grade thresholds.
""".split()
)
INTEGRATED_V2_DEFINITIONS_HASH = canonical_hash(INTEGRATED_V2_DEFINITIONS)
ESTIMATE_HOLD = "추정치 · 산정 근거 확인 필요"
_SUPERSCRIPT = re.compile(r"^\s*[⁰¹²³⁴⁵⁶⁷⁸⁹]+\s*[).]?\s*\S")
_NUMBERED = re.compile(r"^\s*\d{1,2}[).]\s*\S")
# Parsers flatten superscripts to ordinary digits. Require a table and an
# explicit accounting/disclosure note; numbered policy lists stay candidates.
_NOTE = re.compile(
    r"산정\s*(?:시|기준|범위)|산출\s*(?:시|기준)|측정\s*지표"
    r"|포함하여\s*산정|구분\s*없이\s*공시|공시하였습니다"
)
TABLE_FOOTNOTE_POLICY = dict(
    profile="table-footnotes-dec24-v1",
    superscript=_SUPERSCRIPT.pattern,
    numbered=_NUMBERED.pattern,
    note=_NOTE.pattern,
    table_context="same-page-table-immediately-above-with-horizontal-overlap-60pt",
    action="exclude-selected-span; retain-receipt-and-source-as-table-context",
)
LOCATED_TABLE_CONTEXT_POLICY = dict(
    profile="located-table-context-p2-v1",
    geometry="only-located-focal-and-table; preserve-invalid-native-coordinates-and-issues",
    isolation="unlocated-table-is-not-adjacency-context; continue-with-located-peers",
    authority="context-only; unchanged-source-span-selector-and-evidence-guards",
)


def table_footnote(quote, *, kind, table_context=False):
    if kind not in {"table", "table_row", "table_cell"} and not table_context:
        return False
    return bool(_SUPERSCRIPT.match(quote) or (_NUMBERED.match(quote) and _NOTE.search(quote)))


def adjacent_table(packet, graph, *, located_only=False):
    """Geometry supplies note context only, never semantic evidence attribution."""
    if packet is None or graph is None:
        return False
    data = packet["untrusted_document_data"]
    focal = next((b for b in graph.blocks if b.source_id == data["source_id"]), None)
    if focal is None or focal.winner is None:
        return False
    if located_only and focal.bbox is None:
        return False
    box = focal.source_ref().bbox
    if box is None:
        return False
    for block in graph.blocks:
        if block.kind != "table" or block.page_num != focal.page_num or block.winner is None:
            continue
        if located_only and block.bbox is None:
            continue
        table = block.source_ref().bbox
        if table and 0 <= box[1] - table[3] <= 60 and max(box[0], table[0]) < min(box[2], table[2]):
            return True
    return False
