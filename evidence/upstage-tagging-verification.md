# Actual Upstage tagging and new-report diagnostics — 2026-09-13 KST

Baseline a67c070; Orca run_d94fe987bf0e. This checkpoint adds a real local element
transport and fixes a real extraction omission. It does not complete the worker/API
non-synthetic tagging composition or establish service-grade semantic accuracy.
Contract: `docs/local-upstage-tagging-contract.md`.

## Observed failures and changes

The first live full-SourceRef response changed Korean `처리` to `처뤬` while copying
citations. Across six settled calls, all responses missed required element entries.
A seventh call returned an invalid completion receipt; the USD1 reservation remains
unsettled and that operation stopped without trying its remaining replicas.

The transport now asks for packet-local evidence IDs and expands exact source
metadata locally. Literal-Unicode model input avoids escaped Korean JSON contents.
An initial compact-only diagnostic still over-proposed elements, and a Unicode
variant still duplicated G1 once. These are failures, not successful semantics.
The final transport requires frozen classification and allowed element IDs, pins
them in the model-visible schema, and retains downstream validation as mandatory.

A separate new-report failure was reproduced: Samsung Life p23's two prose
sentences were classified as `heading` by the parser, so the real worker made zero
extraction calls for them. Both worker selection and dispatch now admit long
headings without changing their source type/quality. A failing-first worker test
now reaches the transport, and actual Upstage extraction recovered two exact claims.
The 60-code-point threshold remains an unvalidated routing heuristic.

## Actual API diagnostics

All calls used solar-pro4 and the existing cumulative USD10 ledger. Models proposed
extraction, classification and elements only; no report received a grade or label.

| Stage | Settled tagging calls | Complete, unique element sets |
|---|---:|---:|
| Full metadata copying, reused Doosan/Kia paragraphs | 6 | 0 |
| Compact IDs, escaped Korean input | 6 | 4 |
| Compact IDs, literal Korean + clearer instruction | 6 | 5 |
| New-report packets, classification not frozen | 6 | 5 |
| New-report packets, separate classification then frozen tagging | 6 | 6 |

The first three rows reuse two hand-selected development paragraphs. Input/prompt
changes are confounded; this is not a controlled causal benchmark. Mean output fell
from2014.5 to572 tokens between the full-copy and literal-Unicode variants. Mean
input fell from5080.5 to2133 tokens. No accuracy percentage is inferred from these
cost or structural measurements. Full details: `upstage-tagging-diagnostics.json`.

Kiro selected KEPCO, Samsung Life and Hyundai Steel outside its inspected semantic/API
loops. They are not certified untouched holdouts; broader corpus parsing may have
exposed them. Coordinator checked actual filenames, hashes, TOCs and selected page
images. Raw original PDFs were not modified.

- Samsung Life: parsed p23/24/121/138 (E body, E data, GHG assurance). The first
  selected claim came from a long heading; a second claim remained separately
  preserved. Final preliminary classification: management.
- KEPCO: parsed p75/76/205/259. Initial p74 was a photo collage, so the next body
  pages were explicitly selected after visual review. Final classification: goal.
- Hyundai Steel: p17/113/138 ingestion rejected as PDF_INVALID. Read-only diagnosis
  found /Named /Print actions outside the existing allowlist. This remains an
  ingestion compatibility blocker; the security policy was not bypassed.

The final new-report packets each contain one extracted body claim, its full source
paragraph, and one bounded paragraph from each selected data/assurance page. This
is curated retrieval, not exhaustive table/evidence recall. All three sections were
included, but full data tables were not claimed reconstructed or verified.

For both successful new reports, three distinct tagging requests preserved packet
identity, matched the separately frozen model classification, returned all required
unique elements and restored allowed refs exactly. Samsung Life proposed M1/M2/M4;
KEPCO proposed G1/G2/G3/G4/G6. Consistency does not establish semantic correctness:
these proposals still require source and attribution verification and human-gold
evaluation. Every source stayed unverified, every decision null, verified present0.

Local receipts/plans: `.local/tagging-live/`, `.local/tagging-compact-live/`,
`.local/tagging-compact-utf8/`, `.local/tagging-holdout/`. Early unfrozen experiments
predate the final mandatory-classification boundary and are retained as diagnostics.

## Budget

Before:1201 calls,5 unsettled,USD6.1699600550 committed/reserved.
After:1236 calls,6 unsettled,USD7.2388412850 committed/reserved.
This wave:35 calls,34 settled; settled costUSD0.0688812300 plus one retained USD1
reservation. Cumulative settled costUSD1.2388412850; the six unknown reservations
are not assumed free. No automatic API retry, refund, alternate ledger or Bedrock.

## Verification and remaining work

Verification commands/logs are in `.local/tagging-live/`; final results recorded
below after checks complete. The initial architecture command used a nonexistent
filename; the correct `scripts/verify_architecture.py` was subsequently executed.
Two evaluation-harness errors (duplicate pages keyword; heading-only claim lookup)
were recorded and corrected without calling the API for those failed attempts.

Still open: approved real tokenizer/accounting and worker/API tagging composition;
source-quality workflow; robust table reconstruction and attribution; independent
human labels and representative held-out accuracy; PDF Print-action compatibility;
actual browser/staging/deployment validation. No production claim or human/source
approval was manufactured.

Final coordinator checks:
- `uv run pytest -q`:1672 passed,2 existing dependency warnings,269.05s. Includes
  unit/integration/contract/backend E2E/security coverage; no new browser E2E.
- `uv run ruff check apps packages tests evaluation`:passed after fixing two long
  test string lines and import spacing; no assertions removed or relaxed.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`:
 155 source files passed,3 existing untyped-body notes.
- `uv run python scripts/verify_architecture.py`:passed.
- `uv build --all-packages --out-dir .local/tagging-live/dist-profile-final`:four Python
  packages built (sdists and wheels).
- `uv run python scripts/validate_package.py`:743/743 passed, documentation/contracts
  only. It does not certify model accuracy or production readiness.
- Final six fixed-track calls had six distinct provider request IDs. No cached
  response was counted as an independent replica.

Failing-first checks covered nonexistent transport, duplicate/spend boundaries,
compact-ID expansion/invented IDs, interrupted receipts, a busy operation lock,
frozen output schema, mandatory classification and the long-heading worker path.
Actual model diagnostics were separate from fake-HTTP regression fixtures.
The final coordinator-only profile guard was also failing-first: an arbitrary
model_profile previously passed construction, then was rejected before spending.
The wire transform now requires MODEL_PROFILE in existing model/cache identity.
After this guard, the focused suite passed29 tests and the full suite above passed;
Kiro's28-test review preceded that last guard. No further paid calls were made.

Kiro performed the initial integration-risk review, new-company selection and a
separate implementation review. The last review ran28 focused tests and found no
reproduced correctness defect in the reviewed boundaries; it noted optional
catalog deduplication. That optimization was deferred because these bounded inputs
had no demonstrated duplicate-ref cost problem. Review assurances are limited to
those cases, not a source-quality or production approval. Reports:
`.local/upstage-tagger-integration-review.md`, `.local/unseen-report-selection.md`,
`.local/tagging-implementation-review.md`. Antigravity was not relaunched after its
previous readiness failure circuit; no Codex worker fallback was needed.

Review qualification: the wire JSON schema is prompt text sent with JSON-object
mode; it does not make provider schema compliance guaranteed. Existing application
validation remains responsible for rejecting wrong tracks, duplicates and evidence
misattribution. The six compliant real outputs above are an observation, not a
universal guarantee from schema pinning.
