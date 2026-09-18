# Raster v5 runtime validation — 2026-09-19

Scope: explicitly injected local parser worker, existing SQLite publication and
shared offline evidence reader. No paid provider call, budget-ledger mutation,
cloud change or domain-label change was made by this validation.

The new worker integration uses an actual generated PDF and OpenDataLoader. A
24-point title above a 12-point two-line paragraph produces a paragraph candidate;
a two-line-only document is classified as a heading and is retained as the
zero-eligible regression. Native glyph geometry/text checks are real. Only local
rendered OCR disagreement and the external HTTP response are controlled. No
paragraph/coordinate/eligibility gate is bypassed.

The positive path recovers one paragraph, publishes v5 with exact request/receipt
pins, counts one provider call and one submitted crop page, reopens the durable run
store and replays with provider calls forbidden. Publication bytes remain unchanged.
Timeout retains the unresolved reservation and prevents publication. Coverage and
receipt-pin tampering prevent readback. Lower-level tests cover ownership, policy
changes, duplicate/pending dispatch, page billing and legacy schema rejection.

Validation already completed:

- `uv run pytest tests/integration/test_raster_parser_worker.py -q`: 6 passed,
  2 existing deprecation warnings; includes store-reopen replay.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: 353 files already formatted.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`:
  passed, 191 source files; existing untyped-body notes remain.
- `uv build --package proofops`: source distribution and wheel built.
- `uv run python scripts/validate_package.py`: 864 documentation/contract checks
  passed. This does not measure application or model correctness.

Remaining rollout evidence: CLI/composition wiring, complete downstream extraction
and tagging acceptance for v5, fresh multi-report live runs, independent semantic
gold, original-crop visual review, cold/repeated read latency, and exact-head CI.
Cloud testing remains not_run. This is not a production-readiness claim.

Full local regression:
`uv run pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q`
finished with **2702 passed, 7 skipped, 2 existing deprecation warnings in 202.06s**.
The subsequent store-reopen strengthening of the worker test also passed its
6-test focused run. No application source changed during the full suite.
