# Native paragraph attestation — bounded worker integration (Developer A)

Status: design contract + implementation. No domain criteria changes.
Scope: integrate the EXISTING `native_paragraph_attestation_v1` receipt
(`packages/proofops/adapters/local/source_verification.py`; coordinator precision fix recorded separately) into the
actual parser worker (`apps/worker/src/proofops_worker/local_runner.py`) and the
run-graph reader (`packages/proofops/adapters/local/run_artifacts.py`), with
durable fencing in `packages/proofops/adapters/local/job_store.py`.
Only those three implementation files plus focused tests and this note are owned
by this slice. Composition/CLI wiring is root-owned and follows later.

## 1. Versioned checkpoint contract

New envelope `local_parser_checkpoint_v4`, additive over v3:

- All v3 fields retained (`runtime_note_review_artifacts`, `graph_sha256`,
  `note_review_policy_sha256` when a note policy is bound).
- New fields, present **iff** a native policy is bound:
  - `native_paragraph_attestation`: the full receipt dict, schema
    `native_paragraph_attestation_v1` (includes `tenant_id`,
    `document_version_id`, `parse_manifest_id`, `source_sha256`,
    `input_graph_sha256`, per-paragraph `records`, `scope`,
    `artifact_sha256`).
  - `native_paragraph_policy_sha256`: `canonical_hash(native_paragraph_policy())`, pinning mode plus verifier,
    normalization and Swift OCR reader source hashes.
  - `graph_sha256`: pins the FINAL graph (note replay first, native overlay
    second). The receipt's `input_graph_sha256` pins the pre-native
    (post-note) graph, so ordering is cryptographically bound.
- An all-`unresolved` receipt is a valid publication. The coordinator's real-report
  observation (373/373 unresolved; 128 `interactive_visibility_requires_review`,
  245 `relationship_validation_required`) is the expected case, not a failure:
  the receipt is persisted and replayed as-is, applying only the recomputed
  `verified` subset (possibly empty). Unresolved never becomes approval.

## 2. Compatibility matrix

| Reader \ envelope | v1 | v2 | v3 | v4 |
|---|---|---|---|---|
| old code (pre-slice) | ok | ok | ok | explicit `PARSER_CHECKPOINT_SCHEMA_UNSUPPORTED` / policy mismatch (never silent) |
| new reader, default publication (`verify_paragraphs=False`) | ok | ok | ok | readable; never newly produced with default flag |
| new code, opt-in (`verify_paragraphs=True`) | ok | ok | ok | recompute-and-compare replay |

Rules enforced in code:

- v1/v2/v3 envelopes containing any `native_paragraph_*` key are rejected
  (`NATIVE_PARAGRAPH_CHECKPOINT_INVALID`), mirroring the existing v1 rule that
  rejects stray note keys. Legacy artifacts are never reinterpreted.
- v4 requires a bound native policy whose hash matches
  `native_paragraph_policy_sha256`, a well-formed receipt, and a final
  `graph_sha256` equal to the recomputed post-overlay graph.
- `replay_native_sources` (recompute against original bytes) is the ONLY path
  to a `verified` quality. A matching `artifact_sha256` or a caller-claimed
  `verified` status is never trusted — the existing trust guard is preserved.

## 3. Ordering and trust

1. Worker: parse → verified load → note-policy bind → note replay (existing) →
   native-policy bind → `attest_native_sources(notes_replayed_graph)` →
   `replay_native_sources(receipt, ...)` → publish v4 with final hash.
2. Reader (`load_run_evidence` / `load_run_graph`): verified load → note replay
   (existing) → `replay_native_sources` recompute-and-compare → final-hash
   check. Notes replay strictly precedes native attestation on both paths.
3. Tenant/document/source/receipt binding comes from `attest_native_sources`
   itself (`_validate_graph`, `source_sha256` equality); the reader surfaces
   mismatches as `NATIVE_PARAGRAPH_REPLAY_INVALID` / existing integrity errors.
4. Retry-choice immutability: the native policy (mode + three source hashes vs `None`) is bound immutably per parse job
   (`parser_native_policy` kind, same pattern as `parser_note_policy`). A retry
   with a different `verify_paragraphs` flag fails closed on bind; a checkpoint
   whose native shape disagrees with the bound policy fails closed on commit.
   Attempt identity/fencing/usage rules are unchanged (existing
   `fencing_token`, immutable `lease`/`usage` records).

## 4. Rollback

- Stop constructing `LocalParserRunner(..., verify_paragraphs=True)`; default
  `False` reproduces v1–v3 checkpoint contents. New jobs also pin a null
  native choice to prevent false→true retry changes; existing unbound legacy jobs remain readable.
- Retain the DB file, immutable artifacts, and the v4-capable reader. Old
  readers must not be assigned v4 runs; v4 runs stay readable on the new reader
  and are never downgraded by stripping pins.
- No migration, no new dependency, no API change, no model call. Native verification adds no product model calls. Existing opt-in note review
  may still invoke its authorized model.

## 5. Explicitly unresolved (not claimed)

Tables, table-cell/note ownership, footnote binding, numeric-check effects,
rule approval, and any grade/label consequence of paragraph verification remain
unresolved per docs 28/31 (GAP-003/004/007) and `docs/source-condition-review-contract.md`:
paragraph attestation covers native+rendered paragraph text only and changes no
grade. This slice adds no rubric, threshold, or approval semantic.

## 6. Implementation record (actual runs, 2026-09-18)

Owned files changed (coordinator owns everything else; untouched):
- `packages/proofops/adapters/local/run_artifacts.py`: `NATIVE_PARAGRAPH_POLICY`,
  `checkpoint_native_attestation`, v4 handling in `checkpoint_note_reviews`,
  notes-then-native replay in `load_run_evidence`, additive
  `native_attestation` return key.
- `apps/worker/src/proofops_worker/local_runner.py`: `verify_paragraphs: bool
  = False` opt-in; native policy bind per attempt; attest+replay after note
  replay; v4 publication with receipt + final graph hash.
- `packages/proofops/adapters/local/job_store.py`:
  `bind_parser_native_policy` / `parser_native_policy` (immutable per-job
  choice, same pattern as note policy); v4 commit validation
  (`NATIVE_PARAGRAPH_INPUT_NOT_BOUND` / `POLICY_MISMATCH` /
  `CHECKPOINT_INPUT_MISMATCH`).
- New `tests/integration/test_native_paragraph_worker.py` (8 tests):
  non-boolean rejection; default v1 preservation; opt-in v4 publish + immutable
  replay; tampered receipt/graph rejection; source/tenant mismatch rejection;
  flipped-flag retry fails closed + operator `retry_run` recovery publishes
  once; superseded worker cannot replace checkpoint; unbound-v4 and
  v1-with-native-keys rejection.
- This document (checkpoint contract first, implementation record second).

Results (`.venv/bin/python -m pytest`, real local parse, no model calls):
- new file: 8 passed.
- `test_native_source_verification.py`: 9 passed (existing trust guard intact).
- `test_local_parser_runner.py`: 28 passed (default/v2/v3 paths unchanged).
- `test_automatic_note_runner.py` + `test_run_lifecycle.py`: 50 passed.
- `test_local_extract_runner.py` + `test_local_tag_runner.py`: 42 passed.
- `ruff check` clean on all four touched Python files; `mypy` clean on
  `run_artifacts.py`. Full-repo suite, package validation, live-model/AWS
  checks: not_run (root scope). No commits/pushes, no secrets, no
  dependencies, no domain changes.

Limitations: fixture PDFs verify few/no paragraphs (rendered Swift OCR is
environment-dependent; unresolved receipts persist by design). v4 runs are only
readable by the new reader; composition/CLI wiring for the opt-in flag is root
follow-up. Downstream extract/tag readers receive the overlaid graph only on
opt-in v4 runs; default runs are bit-identical to before.

## Coordinator integration review

Added `--verify-paragraphs` to the worker and local Upstage pilot; composition
rejects nonboolean flags and use outside parse. Pilot state refuses changed flags.
Four failing counterexamples were reproduced after worker delivery: both directions
of changed flags after publication, automatic notes plus v4, and absent code pins.
Coordinator fixed the shared publication/read paths and added regression checks.
Receipt recomputation is intentionally retained: the KB 3-page replay took 62.54s,
so interactive-read performance is not accepted as service-ready. No receipt
cache, relaxed OCR match, or blanket table-source approval was added.

Focused integration after coordinator fixes: 25 passed, 2 existing warnings, 62.57s.
