# PB1 local extraction policy

New `finals-unattended-v2` runs pin `pb1-v1`, the PB1 preliminary prompt,
`upstage-ocr-page-v7`, and a distinct analysis/extraction policy hash. Old HF1,
pre-HF1 and initial v2 analysis hashes remain selectable for stored replay.

Python selects time-series rows with an explicit year column, environmental
metric context and a literal unit. The latest explicit observed-year column is
the focal value; older columns are retained as comparison context. The quote is
the original contiguous parser-grid row, with no concatenation of headers into
it. Per-cell PDF characters, numbers, unit and focal year header must pass the
new native proof before the row can be verified. Unknown/conflict/unlocated
cells stay unresolved. The parser refuses a raised digit as part of a numeric
quantity. Exact x-ordered native glyphs can recover subscripted unit cells;
this does not repair or strip digits from quantities. These local native table
proofs are a new policy, not an inherited rendered-reader release approval.

Merged row/column spans and explicit multi-level year headers are linked only
inside the same table, parser run and page. Each table contributes at most 24
numeric row claims, in source row order. Existing extraction/tagging call caps
and provider/run/task budgets still stop further work conservatively. Other
literal table disclosures use the existing source-ID model selection path.
LLMs select/classify/tag; Python alone computes grades.

GAP-002 admission preserves the model's goal track and sets ordinary targets'
forward-looking category to null. Explicit projections require calculation
basis, assumptions or uncertainty; inadequate context stays in review.
Selected adjacent source line wraps can be joined without rewriting bytes;
isolated connector/tail fragments are excluded with uncovered spans preserved.
Table footnote rows are context, not independent time-series observations.

New result JSON may include `table_observation` and `duplicate_occurrences`.
Quotes, occurrence IDs, source refs and original receipts remain independent.
These optional fields are compatible with existing opaque-result consumers;
there is no DB migration or new production dependency. Rollback stops PB1
assignment and uses the preserved HF1 policy for new runs. Existing PB1
artifacts must remain with a reader that supports their exact pinned policies.
No hosted deployment or release-gate approval is included in PB1.
