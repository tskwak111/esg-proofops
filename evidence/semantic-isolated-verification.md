# Single-claim semantic extraction and period-role guard — 2026-09-10

## Controlled live probe

Reused the four exact original p25/p46 source spans and same few-shot prompt from
`semantic-expanded-results.json`, with solar-pro3, JSON mode, temperature 0 and
2,048 output tokens. Changed batching only: four single-claim requests (each with
packet-local q0) instead of one four-claim request. Source/tenant/manifest and
request, prompt, packet, wire, replica and original rule hashes were recorded
before execution. No context inheritance, string-null coercion or partial salvage.

All four new responses passed the then-current source/schema guard and contained
JSON null rather than string null. This is not semantic success or causal proof
that isolation fixes the model: each input was sampled once and aliases also
became packet-local q0. Manual diagnostic review found:

1. Cumulative reduction: metric `온실가스` was recovered, but reporting period
   `2023년부터 2025년까지` was incorrectly assigned to organizational boundary.
2. Renewable procurement/carbon reduction: metric still includes quantity/unit;
   two measurement assertions remain in the parent, and domestic-business entity
   attribution is not accepted.
3. Industrial-complex water supply: source entity names the complex, not the
   reporting company's water consumption. The metric mixes rate/quantity/unit.
4. Company-facility water use: `남해(광양만)` is the receiving water body, not an
   organizational boundary; the metric includes time/amount/unit and a verb.

No grade or evidence binding was accepted. These are coordinator-selected diagnostic
sentences, not a human-adjudicated gold set or a report-accuracy benchmark.

## Reproduced shared validation defect

A source-exact quote consisting solely of a year or year range passed as an
organizational boundary. Added a failing-first regression and a minimal guard in
`validate_dimensions`, reused by `validate_semantics`, rejecting only explicit
1900–2099 year-only periods in the supported forms. Wider phrases containing an
actual boundary remain model proposals requiring semantic review. This does not
claim to reject locations, every date format or every other wrong role.

Offline replay validates all four original source packets and unchanged prompt
against the PDF-validated graph. With the new guard the first response is rejected;
the other three still pass source/schema checks but remain semantically unresolved.
The original live result/guard hashes are preserved; new validation is recorded
separately in `semantic-isolated-review.json`, without rewriting past revisions.
No domain grading threshold, API/DB migration, production binding, dependency or
source-quality approval changed. Rollback removes the new input guard for new
runs only; archived responses/results remain immutable.

## Cost and checks

Four additional calls cost $0.0005778300 under the existing pinned-price ledger.
Cumulative committed/reserved is $2.0405921450 / $10 across 104 calls, including
two previously unsettled calls. No retries, Bedrock/AWS calls or credential output.

- `uv run --no-sync pytest -q tests/integration/test_claim_dimensions.py`
  — 25 passed, including period rejection and boundary-containing phrase retention.
- `PYTHONPATH=. uv run --no-sync python .local/semantic-isolated/replay.py`
  — four archived source/request replays and the new rejection passed; no extra API calls.
- `uv run --no-sync ruff check .` / `uv run --no-sync ruff format --check .`
  — passed, 234 files formatted.
- `uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`
  — passed, 146 files, existing untyped-body note.
- `uv build --all-packages --out-dir .local/semantic-isolated/dist` — four packages built.
- `uv run --no-sync python scripts/verify_architecture.py` — passed.
- `uv run --no-sync python scripts/check_licenses.py --root . --env ENABLE_LEGACY_PYMUPDF=false`
  — passed; human rights and deployed-image verification remain separate gates.

AWS/deployed E2E, deployed-image security checks, approved source-quality profile,
semantic gold evaluation and automatic claim/evidence attribution: not_run.

Final full suite:
`PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`
— 1,458 passed in 108.66s, two existing Starlette/AnyIO deprecation warnings.
`uv run --no-sync python scripts/validate_package.py` — 730/730 documentation and
contract checks passed, separately from application tests. Artifact accounting
also confirms the four receipts sum to the budget delta and all review decisions
remain null with undetermined binding.
