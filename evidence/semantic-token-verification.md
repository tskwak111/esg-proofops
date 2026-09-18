# Source token selection trial — 2026-09-09

Added an opt-in evaluation prompt, local whitespace token enumeration and strict
token-range validation in `evaluation/claim_dimensions.py`. The model selects
inclusive start/end token IDs for entity/metric/boundary, or null. Code reconstructs
the exact original substring and reuses semantic/dimension source validation.
Unknown IDs, reversed ranges, foreign-claim IDs, malformed ranges and extra fields
are rejected. Existing completeness, unique-quote and graph identity checks remain.
Particles and punctuation stay literal; this is not morphology, a curated metric
candidate catalog, canonical metric normalization or semantic approval.

## Actual result: failed

One Upstage request reused all 13 LG Chem E-section targets from the previous
failed free-quote experiment. The returned response assigned all 39 fields and
included a foreign-claim metric token range for q11 (t212–t213 belong to q10).
The whole response failed with `ordered own-claim token range required`.
No fields were salvaged, accepted as evidence, or used for numeric comparison.

Manual inspection also found semantically wrong but source-local proposals:
q1 entity was `향후 생산능력`, while its boundary was `Scope 1`;
q0 entity included `LG화학은 2050년`. These demonstrate that source-range validity
does not establish semantic role correctness. The validator intentionally does not
pretend to detect every such meaning error. All outputs stay model proposals or
unresolved; no source-quality revision, domain grade, product API or DB changed.

This token-ID approach did not solve semantic extraction in this trial and is not
promoted into product inference. A useful next experiment must evaluate model/task
capability against explicit positive/negative examples; merely changing the JSON
format again is not supported as a remedy by these results. No accuracy or corpus
performance claim follows from this 13-claim development sample.

Receipts, raw returned IDs, source identity and per-field range diagnostics:
`evidence/semantic-token-results.json`. Full packet/request/response/budget under
`.local/dimension-pilot/semantic-tokens/`; runner
`.local/dimension-pilot/run_semantic_tokens.py` (invoke with `PYTHONPATH=.`).
Prompt, rule, model, packet and wire hashes and replica are retained.

One call added $0.001019865. Shared ledger: 91 calls, $2.038545155
committed/reserved of $10, including two prior unsettled calls. No retries,
Bedrock/AWS actions or secret output.

## Verification

Failing-first token-range regression, then 8 focused tests passed. The test uses
two claims sharing an original block and checks a valid multi-token source quote,
foreign-claim IDs, unknown IDs, reversed and malformed ranges, and unknown entity.
Ruff lint/format passed (232 files); mypy passed (146 source files); four-package
builds, architecture and supply-chain checks passed. Production E2E/AWS not_run.

`PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`:
1,439 passed in 105.11s, two existing Starlette/AnyIO deprecation warnings.
`uv run --no-sync python scripts/validate_package.py`: 715/715 documentation and
contract checks passed (separate from application tests).
