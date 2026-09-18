# External-note discrimination

The latest worker incorrectly selected four groups on KB Financial p30: two
investment narrative paragraphs and two rows containing parenthetical conditions
inside the table. Native text and original rendered page had been inspected before
the live call; there are no external table footnote paragraphs on this page.

The discovery instruction now explicitly distinguishes general strategy/investment
prose and in-cell parentheses from external qualifications of measurement data.
A fresh KB invocation returned zero note proposals. An independent negative page, NAVER
p84 (KPI table, management roles and organization diagram), also returned zero.
These are two negative controls, not a corpus-wide specificity estimate.

Positive regression: Samsung Electronics p72 retained all five exact native word
sets. LG Chem p97 initially returned all source text in one group: an unnumbered
biomass qualification followed by six numbered notes. A failing regression exposed
the splitter's requirement that the first fragment be numbered. It now preserves
the unnumbered prefix separately and keeps each numbered note with its following
lines. A fresh LG Chem invocation returned seven exact word sets, no missing/extra
paragraphs. All source/ownership/scoring guards remain in force.

`note-discriminator-evaluation.json` preserves failures and successful follow-ups,
source/reference/result hashes and private receipt paths. Final selected outcomes:
KB 0/0 proposals, NAVER 0/0, Samsung Electronics 5/5, LG Chem 7/7. Empty predictions
are not proof of complete coverage or accepted absence. No source annotation,
note-to-cell ownership, numerical consistency or ESG grade is approved by these runs.

Cumulative authorized ledger: USD7.8339376000 / USD10, 1359 calls, six old unsettled
reservations untouched. The remaining service integration gap is recorded in
`service-path-audit.md` and is not hidden by these extraction results.

Verification: full `uv run pytest -q` passed 1910 tests with two existing dependency
warnings in 136.26s (`note-discriminator-final-full.log`). Ruff lint/format and CI
mypy (167 source files) passed; all four packages built. The isolated extracted-wheel
reader reopened 18 real checkpoints with identical graph hashes and zero calls,
including failed earlier outcomes (`note-discriminator-wheel-replay.json`).
Document/contract validation passed 763 checks; it is not an application benchmark.
No push, deployment, AWS call, new dependency or public API/DB change.
