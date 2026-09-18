# Local real-model service pilot — 2026-09-12

Upstage Solar Pro 3 is now connected to actual local HTTP upload → immutable run
creation → local parse → bounded paragraph extraction → claim list/detail → source
preview. The model only proposes exact quotes. Untagged claims have null grades,
no editable tag revision, and source candidates remain unverified. No rulepack was
approved or activated for this pilot; draft rules are pinned as extraction references.

Orca run `run_19e25886bdaa` used OpenCode Muse Spark 1.3 Free for the untagged UI/API
and Muse Spark 1.2 Free for bounded extraction. Coordinator replaced snapshot-mutating
worker test scaffolding, integrated runtime/authorization/accounting, and ran live tests.
Both worker terminals were explicitly closed; no reclaimable worker remains.

## Observations

- LG Chem sample page 1 corresponds to original physical page 25. Two separate local
  runs each made eight settled calls, producing 18 and 12 exact-quote proposals.
  Their selected paragraphs differ because the existing discovery order sorts source
  UUIDs. Those counts are **not** a valid before/after quality comparison.
- A separate matched-input comparison reused precisely the first run's eight packets
  with the new prompt hash. Proposals changed 18 → 9: six title/code proposals were
  removed; seven fragmented renewable-energy clauses became four fuller sentences.
  One general industry description still survives. No human gold accuracy/recall claim.
- Browser verified actual list, untagged detail, and authenticated PDF page image
  (1413×1999). A discovered PDFium float32-vs-PDF-decimal mismatch caused HTTP409;
  allowing only 0.0001-point rounding fixed it. Rotation and material geometry mismatch
  still fail. Unverified coordinates are not highlighted or shown as verified success.
- Cost API now reads immutable real worker usage instead of showing zero attempts
  from the unrelated Bedrock ledger. The second run reports eight calls, 5154 input
  tokens, 372 output tokens and USD0.0010959300. Unsettled usage keeps unknown cost.
- 24 actual calls this wave cost USD0.0030239550; no new unsettled calls. Cumulative
  settled/reserved balance USD3.3431744250 / USD10 includes three prior USD1 reservations.
  Raw receipts, failed setup logs and separate old/new snapshots stay under `.local/`.
  IDs and artifact hashes are recorded in `local-upstage-service-pilot.json`.

## Verification

- `uv run pytest -q`: **1523 passed**, two dependency deprecation warnings, 101.16s.
  Includes unit, integration, contract, E2E and security tests; this is not production load.
- `uv run ruff check apps packages tests evaluation/local_upstage_pilot.py`: passed.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`: 149 files passed; one untyped-body note.
- `npm run build`: TypeScript/Vite passed (workspace uses pnpm).
- `uv run python scripts/verify_architecture.py`: passed.
- `uv run python scripts/validate_package.py`: 736 documentation/contract checks passed.
- Exported locked dependencies + `pip-audit --strict --no-deps --disable-pip`: no known vulnerabilities.
- `pnpm audit`: no known vulnerabilities. Initial `npm audit` was not applicable because
  this workspace has a pnpm lockfile; no package-lock was created.
- Actual browser and model calls: run. AWS/staging/public deployment: not_run.

## Remaining service acceptance work

This is a local integration checkpoint, not service readiness. Next fix bounded
selection so new manifest UUIDs do not change the tested paragraphs; keep the policy
pinned for replay. Evaluate extraction on held-out reports and independently anchored
labels. General background false positives and context/atomicity remain unmeasured.
Then connect E claims to E + ESG DATA + APPENDIX evidence with year/unit/boundary
checks and selective external table recovery. Source-quality and domain approval gates
stay intact; this pilot does not perform evidence tagging, grading or export approval.

To review stored results without model calls, run `evaluation/local_upstage_pilot.py`
with the existing state directory and `--serve`; `--invoke` is explicitly required for
calls. The loopback harness uses a temporary local session, not production authentication.
