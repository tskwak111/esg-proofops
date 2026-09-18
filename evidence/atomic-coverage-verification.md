# Atomic coverage and evidence replay — 2026-09-09

Orca run `run_344276c2e62b`, OpenCode Muse Spark 1.3 Free review task
`task_4faf708e44a3` / dispatch `ctx_7a58a293f11a`. Worker completed, released and
its dedicated terminal closed. Coordinator owns code and fixes. No live model
calls, new dependency, source approval, grade, API/DB change, or cloud action.

## Changes and results

`evaluation/atomic_pilot.py` now rebinds serialized target offsets, quotes, complete
source refs and quality to the original graph before CLI extraction. Stale manifest,
changed quote and Boolean-offset inputs are rejected. Existing E-map, overlap and
tenant checks remain. Raw and normalized offsets are mapped by existing source_ref.

Each request records individual target coverage: full_text_returned, partial or
not_returned, with exact unreturned substrings marked unknown. This is character
coverage only; full_text_returned is neither semantic completeness nor atomicity.
The original discovery gaps remain immutable; new target records distinguish a
dropped selected sentence from never-selected context without relabeling either.
`status: passed` means quote/schema validation, not a complete semantic extraction.

`--replay ARCHIVE` and `--live` are mutually exclusive. Replay uses exact system
prompt + wire packet hashes and the original request ID; absent or ambiguous
requests fail, with no network fallback. Saved replies run through the same quote
and target-range guards. Replay is explicitly labeled, not counted as another
independent replica. It is a local artifact replay, not cryptographic attestation
of provider authorship; keep the request/response folders together.

Actual LG Chem replay: 13 selected sentences, 12 full_text_returned, one
not_returned (K-taxonomy management sentence, normalized [287,406]). The complete
missing quote is in `atomic-coverage-results.json`. No claim recovery or measured
accuracy improvement is asserted. Compounds, the introductory tail, and five
subject-less table-like fragments still require semantic/structure review.

The same 12 reconstituted claims were passed through existing SectionSearch and
retrieve_evidence across E + ALL ESG DATA + ALL APPENDIX. Twelve packets were
created; all have not_found_state=unknown. Verified evidence candidates and
candidate bindings are both empty because source quality remains unverified;
retrieval retains unresolved source IDs. The test did NOT exercise accepted
metric/year/unit bindings or numeric comparison on these reports. The earlier
numeric/binding guard tests remain separate from real-source approval.

Local artifacts: `.local/atomic-pilot/coverage-replay/`, `evidence-replay/`, and
`run_evidence_replay.py`. The latter reuses the existing pinned local rulepack
validation pattern, leaves approved_by/approved_at null, and issues no model call.
Reproduce coverage with the previous atomic CLI PDF/manifest/map/candidates paths,
a fresh --output directory and `--replay .local/atomic-pilot/targeted`.
For the end-to-end local probe: `PYTHONPATH=. uv run --no-sync python
.local/atomic-pilot/run_evidence_replay.py` with a fresh output directory.

## Review resolution

`atomic-coverage-worker-review.md` reviews the prior targeted trial. Its P-1 loss
is now explicitly recorded per target; P-2/P-3 are handled by replaying archived
wire requests, not discovery JSON alone. No automatic forced extraction or label
change was applied from reviewer suggestions. Q-4 must NOT imply that the word
온실가스 establishes tCO2e as the unit: the raw 톤 remains unresolved. The user
already authorized the cumulative $10 pilot budget; no fresh permission gate was
introduced by the review. This turn spent $0; latest recorded committed/reserved
amount remains $2.034728870, including two earlier unsettled calls.

## Verification

Targeted regression tests pass: exact quotes, context-only rejection, partial
coverage, request replay, changed prompt, and tampered candidate provenance.
Full suite: `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`: 1,427 passed, two existing Starlette/AnyIO warnings, 123.16s. Ruff lint/format, mypy (144 source files),
four Python package builds, architecture and supply-chain checks pass.
Production E2E/AWS not_run. No precision/recall or production-readiness claim.
