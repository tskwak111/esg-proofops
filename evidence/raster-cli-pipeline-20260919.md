# Raster activation and downstream integration — 2026-09-19

Terra implemented worker CLI/composition and trusted runtime-file loading in two
bounded Orca tasks. The coordinator reviewed those changes, added pilot opt-in
configuration and tested downstream propagation. No paid model call was made.

`tests/integration/test_raster_tagging_pipeline.py` executes actual generated PDF
parsing, native geometry validation, v5 publication, Upstage extraction and tagging
transports, receipts, one shared test ledger and candidate review publication.
Local OCR disagreement and provider HTTP responses are controlled; document
quality, offsets and classification gates are not bypassed. It verifies one
recovered paragraph reaches one verified-source claim, three preliminary and
three element responses, unknown tags and no grade under unapproved rules.
Reopened review/store reads forbid provider calls and preserve usage/publication.

- Downstream + raster worker + existing live pipeline: 11 tests passed.
- Pilot/worker CLI settings: 28 tests passed.
- Initial pilot-policy red test: 5 failed on missing helper, then passed after
  implementation. Loader and CLI agents also ran their focused test groups.
- Ruff and format passed (356 files); mypy passed (191 source files).
- Build produced source distribution and wheel; package validator passed.
- Previous commit 7f3e208 CI run 35405357540 completed successfully.

No-invoke CLI smoke used a generated title/body PDF, `--verify-paragraphs
--raster-ocr --live-tagging`, and source-scoped local-test grants. Run
`afb75bf3-1e68-4c28-92c8-493ba67a4e71` was created under
`.local/raster-cli-smoke-20260919/state`. Read-only SQLite inspection confirmed
that the exact raster policy, image consent and pinned Document Parse vision
binding reached the immutable snapshot. No key was read and no provider was
invoked; claims HTTP409 is expected before worker execution.

Actual v5 multi-report evaluation and semantic accuracy remain pending. Cloud
verification is not_run. Earlier actual OCR results are kept as separate
experimental evidence, not relabelled as current runtime evaluation.

Full local regression command:
`uv run pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q`
reported 2726 passed, 7 skipped and one failure in 212.41s. The sole failure was
an existing CLI mock expectation omitting the new default-off `raster_ocr=False`
argument. The expectation now explicitly verifies that default; no product code
or authorization assertion was weakened. Re-running the complete affected file
(`tests/integration/test_automatic_note_runner.py`) passed all 13 tests. Ruff and
format were rerun successfully after that test-only change. Full-suite rerun on
this final exact tree is delegated to CI; do not describe the earlier failing
invocation as an all-green run. Package validation passed 864 checks.
