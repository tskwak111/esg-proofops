# Page-note coverage when no table is recognized

Samsung Electronics 2025 physical page 72 has two horizontal-rule tables and five
external note paragraphs. Both current parsers returned no canonical tables; the
automatic table-only reviewer therefore made no discovery request. This is a miss,
not evidence that the page has no notes. The pre-change measurement is preserved in
`unseen-layout-evaluation.json`.

The intended correction is source-page note discovery for every explicitly selected
page, including pages without canonical tables. It must reuse the existing bounded
discovery transport, source-word validation, lease fencing and cumulative ledger.
No table or cell is synthesized. Such pages have no ownership targets and every
note remains ineligible for scoring; native extraction gaps remain unknown.

New automatic runs use a versioned page-coverage policy. Publication must account
for each selected physical page exactly once, even if discovery yields no notes.
Old table-only policies and immutable artifacts remain readable with their original
coverage semantics; they cannot be presented as page-complete. No public API or DB
column migration is needed. Rollback must retain the new policy/artifact reader or
reject new-policy runs, never silently discard page-only note artifacts.

Acceptance: a native page with no detected table reaches discovery, preserves exact
source fragments and unknown ownership, and replays with no model call. Duplicate,
missing or unselected page artifacts fail publication. Earlier table-note artifacts
retain their original graph hashes. Re-run the original Samsung page against the
independent reference after implementation. These checks do not approve model
ownership or establish whole-corpus accuracy.

## Measured implementation

New runs use `automatic_pages_v2`; historical `automatic_v1` remains table-only.
Source-page packets have no table/source targets. Existing bounded discovery uses
native horizontal-rule rectangles only as untrusted column hints, never as repaired
tables. Disjoint column requests prevent the other column's data rows from leaking
into a note paragraph. Selected small embedded numeric glyphs are retained only
with a unique note-line geometry; distinct same-column numbered starts preserve
their respective continuation lines. No reference labels or report-specific crops
are supplied to inference.

Samsung Electronics physical p72, independently labelled before any model output:
initially 0/5 notes (no request); first page-only attempt 4 exact notes plus 7 extras;
glyph/region hints recovered 5 exact notes but retained 6 extras; column separation
removed the data-row extras but merged two multiline notes; final fresh run returned
5/5 exact native word sets, zero missing/extra paragraphs, two paid requests. All
targets remain empty and scoring is disabled. Every iteration and its original
source/result hash remains in the evaluation JSON and private immutable archives.

LG Chem physical p97, a second unseen layout, returned 7/7 exact word sets with no
extras before these changes. One link is model-proposed, not accepted; all seven
notes remain ineligible for scoring. Neither measurement estimates corpus accuracy.

Independent Orca review reproduced invisible off-page text acceptance and paid
discovery on empty native pages. Real synthetic-PDF regressions failed first; the
shared native-word geometry guard now rejects off-page words in both table and
page-only paths. Empty/all-unreadable pages retain a reasoned no-call receipt and
an unresolved page hold. Old safe artifacts replay after current source validation;
unsafe old geometry is deliberately not grandfathered.

Cumulative authorized ledger after this evaluation: USD7.8283551550 / USD10,
1351 calls; six old unsettled reservations untouched. No AWS/deployment or rule
label approval. Service goal remains active pending wider held-out layouts and
trustworthy ownership/condition application.

## Verification

- Final full application suite: `uv run pytest -q`, **1909 passed**, two existing
  dependency warnings, 131.98s; private log `page-notes-source-guards-final.log`.
- Ruff lint/format passed (281 files); CI mypy passed (167 source files).
- `uv build --all-packages` built all four packages. An isolated extracted-wheel
  reader, blocking evaluation/scripts/tests imports, reopened 12 historical/new
  real checkpoints with identical graph hashes and zero model calls, including the
  old zero-table result and every Samsung iteration. Receipt:
  `.local/note-review-integration/page-notes-wheel-replay-final.json`.
- Document/contract validator: 762 passed; this is not an application benchmark.
- Orca source-reference task `task_e0f9049382b4`, design review `task_a54ab79ecf32`,
  and code review `task_0577a4ce494c` completed and their terminals were released.
  Code review's two reproduced findings are covered by the final regressions.
- No new dependency, public API/DB column change, push, deployment or AWS call.
