# Reporting-period validation — 2026-09-13 KST

Baseline8d731d3; Orca run_87475a23aa74. Coordinator reproduced six failing tests:
identical period strings tCO2e, MWh, 기간, invalid ISO date2025-13-01, reversed
range2025–2024 produced numeric consistent; assigning the same metric span as a
period on both sides produced accepted evidence binding. These were explicitly
synthetic, verified-source fixtures, not customer source approval.

A shared pure supported-period syntax guard now returns undetermined binding or
not_comparable/reporting_period_unresolved. Source text, existing normalization,
identities and revisions remain intact. This closes these false admissions but
does not establish correct temporal semantics for arbitrary text. See
`docs/reporting-period-validation-contract.md` for supported syntax and limits.

Failing-first:6 failed. Focused numeric/binding tests after implementation and
positive explicit-period controls:130 passed. Existing source/quantity/unit
attribution guards remain exercised; new valid year/FY/quarter/range/date forms
retain consistent comparison in fixtures. No network or paid API calls.

Offline LG Chem replay through the original verified cached parse manifest kept
all nine observations identical, including their IDs and source refs, unverified;
all nine period strings passed the syntax gate. Artifacts:
`.local/period-validation/replay.py`, `replay.json`. This is a reused development
fixture, not held-out semantic accuracy. New live model tagging, browser E2E,
source approval and deployment:not_run.

## Verification

- `uv run pytest -q`:1656 passed, two existing dependency warnings,127.97s;
  unit/integration/contract/backend E2E/security tests included.
- `uv run ruff check apps packages tests evaluation`:passed.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`:
 154 source files passed, three existing untyped-body notes.
- `uv run python scripts/verify_architecture.py`:passed, including new pure module.
- `uv build --all-packages --out-dir .local/period-validation/dist`:four packages built.
- `uv run python scripts/validate_package.py`:742/742 passed, docs/contracts only.

Kiro reviewed both consumers, ran12 focused regressions/positive controls and
probed parser boundaries. No additional reproducible bypass was found. This is a
bounded engineering review, not exhaustive proof. Report:
`.local/period-binding-review.md`. Its suggestion that supporting additional
literal period syntax automatically needs domain approval is not adopted:
source-backed parser support is engineering work already authorized; interpreting
unresolved domain criteria or inventing fiscal/calendar equivalence is different.

The existing USD10 ledger was not changed by this wave:prior checkpoint1201 calls,
five unsettled,USD6.1699600550 committed/reserved. No API retry or reservation refund.
Antigravity was not retried after its existing readiness failure circuit; Kiro
legacy UI (auto model selection) handled this review, no Codex/Muse substitute.

Task task_fdbbd892d254 / dispatch ctx_979ce2a6bdf9 settled successfully. Review
notes were assessed before acknowledgment; dispatch released and external terminal
closed. Final reclaimable-worker query returned none. Report wording about no
bypass is limited to the reviewed cases, not a universal security/accuracy claim.
