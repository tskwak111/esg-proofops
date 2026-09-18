# Packaged original-PDF note validation — 2026-09-14

The runtime previously could not import original-PDF note validation without
importing `evaluation`. The same implementation now lives in
`proofops.adapters.local.table_notes` and `table_layout_context`; evaluation
modules re-export existing function names for compatibility. The adapter performs
source/graph/packet/fragment/marker checks, not semantic ownership approval or
numeric grading. Model invocation and the evaluation CLI remain outside it.

This is a runtime dependency fix on the service integration path. It does not
claim the production tagging worker now consumes model-proposed notes: that
connection and accepted numeric inputs remain incomplete. No API/DB contract or
migration changes, domain imports, new dependency, source-quality promotion or
rule changes. Install the existing `proofops[parsing]` extra for PDF dependencies.
Rollback can restore the prior module placement while retaining all archives.

New model request receipts retain helper/prompt/contract/model hashes and add
`validator_sha256` and `layout_sha256` for the split implementations. A failing
KeyError regression preceded those additions. Historical receipts are unchanged;
missing historical code pins are not invented. Existing packet validation still
recomputes against the original PDF and exact graph. A failed import regression
preceded moving the functions.

`uv build --all-packages` passed. An isolated `python -I` process loaded the
validator from `dist/proofops-0.0.0-py3-none-any.whl`, with a meta-path guard rejecting
all `evaluation`, `scripts` and `tests` imports. It reconstructed the exact archived
candidate batches selected by the previously validated report CLI commands,
replayed original PDFs, and compared every validator output field with the prior
archive using canonical hashes. All three matched:

| Selected report | Notes | Unassigned | Coverage | Decision |
|---|---:|---:|---|---|
| Kia | 3 | 0 | unknown | null |
| Kakao | 6 | 2 | unknown | null |
| Samsung Life | 12 | 0 | unknown | null |

Reproduction: `.venv/bin/python -I .local/note-review-integration/check-packaged-notes.py`.
Result: `.local/note-review-integration/packaged-notes-replay.json`.
The first probe selected the wrong Kia batch using an unordered glob and was
rejected (`located unconflicted table required`); the final probe selects the exact
batch from `command-final.json`. This was a test-input correction, not a validator
relaxation. No paid model calls, uploads, AWS changes or existing archive rewrites.

Orca Muse Spark 1.3 Free read-only review: task `task_6484e1f6a421`, dispatch
`ctx_7f8ee6c4ba49`, accepted completion `msg_5e14232b7214`. Moved function ASTs match
HEAD; compatibility exports are identical function objects; no package-to-evaluation
imports. Reviewer did not run the wheel replay or full suite; root ran those.
Worker released, exact terminal closed, delivery acknowledged.

Focused checks: 26 passed. Ruff passed. Mypy passed 165 source files (existing
untyped-body notes). Build passed. Documentation/contract validation passed 758/758;
this is not an application accuracy benchmark. Full regression: `uv run pytest -q`
— 1861 passed, 2 existing deprecation warnings, 127.19 s. Log:
`.local/note-review-integration/pytest-packaged-notes-final.log`. `git diff --check`
passed.
