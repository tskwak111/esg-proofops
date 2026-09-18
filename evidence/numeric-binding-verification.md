# Full-span numeric binding guard — 2026-09-13 KST

Baseline2af2ff6; Orca run_1621a332a993. This is a structural correctness fix,
not a new domain criterion or proof of semantic accuracy.

Two failing-first cases showed that normalize_table_bindings accepted a merged
value spanning distinct metric rows or year columns using only its starting
coordinate. The shared function now requires the whole value row span to fit a
row-role cell and the whole value column span to fit an above-value year header.
Above-value headers must end before the value starts. Same-row period cells
remain supported; source identity and unverified/conflict/unreadable gates remain.

The only production-package caller path is this opt-in function; its existing
external caller is evaluation/e_scope_case.py. Default normalize_tables behavior,
API/DB shape and observation IDs of accepted assignments are unchanged. No DB
migration is needed. Rollback disables the opt-in binding path and preserves old
observations/receipts; it must not reinterpret historical snapshots as newly
verified output. No new dependency or source-quality approval was introduced.

Red:2 failed/7 passed. Added matching fully covered controls; focused numeric
normalization and binding tests:32 passed. An offline replay loaded the original
LG Chem PDF through its verified cached manifest and re-ran all nine original
fixture assignments:every observation including ID and source refs was unchanged,
all remained unverified. Artifact:.local/numeric-binding-loop/replay.json.
This is one development case with fixture role assignments, not live tagging,
held-out accuracy, or a table-value gold benchmark. No paid call was needed.

## Verification

- `uv run pytest -q`:1644 passed, two existing dependency warnings,114.37s.
  Includes unit, integration, contract, backend E2E and security tests.
- Final focused suite after removing overlap in positive-control fixtures:32 passed.
- `uv run ruff check apps packages tests evaluation`:passed.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`:
 153 files passed, three existing untyped-body notes.
- `uv build --all-packages --out-dir .local/numeric-binding-loop/dist`:four packages built.
- `uv run python scripts/verify_architecture.py`:passed.
- New model calls, browser E2E, held-out semantic benchmark, service element tagging
  and deployment:not_run. No web/dependency changes.

Shared USD10 ledger remains1201 calls,5 unsettled,USD6.1699600550 committed/reserved
at the prior checkpoint; this wave made no API calls and did not change reservations.

`uv run python scripts/validate_package.py`:742/742 passed, documents/contracts
only. Existing Antigravity readiness failure circuit was not retried; this wave
uses Kiro legacy UI (model selection auto), with no fallback Codex/Muse worker.

Kiro also demonstrated that an explicitly assigned same-row period cell containing
`tCO2e` remains an unverified raw period string. This guard validates structural
attribution, not the semantic truth of the role assignment. This limitation is
NOT evidence of service readiness: downstream period interpretation/validation
must prevent such a candidate from becoming a verified year binding. We did not
add a narrow four-digit-year heuristic that would reject legitimate period text.

Coordinator qualification: the reviewer calls semantic period checks a new domain
rule; that is too broad. Validating that a source actually expresses the claimed
period is legitimate engineering work under the existing provenance contract.
It remains open here because this patch is limited to full-span attribution.

Kiro task_eac3e5330d9d / dispatch ctx_bf9b14a6192d completed the bounded review,
ran32 focused tests and confirmed wrong/right-year column rejection/acceptance.
Report:.local/numeric-binding-review.md; coordinator qualification above governs
semantic limitations. Dispatch released, terminal closed; final reclaimable query
returned none. No claim of exhaustive correctness or service completion is made.
