# Source-condition bootstrap and original-view HTTP integration

Three operations are wired into the full local API composition: explicit initial
publication, current/historical source-review inventory, and pinned fragment original
display (receipt or PNG). They reuse reviewer session/CSRF/rate checks, immutable
source-condition storage and committed-run graph/original/note replay. The public
OpenAPI and JSON Schema contracts were extended additively. Existing claim-review
request shapes and grading behavior are unchanged.

Publication pins the original document/version, object version, parse checkpoint,
base/published graph, run input and registered note artifacts. The complete bounded
inventory includes all canonical parser candidates, proposed note groups and individual
native fragments, including unassigned ones. Overlapping entries are not independent
evidence; inventory size does not mean complete coverage. The 5000-entry bound rejects
larger requests rather than truncating them. All returned coverage remains unknown.

An epoch comparison in the publication transaction prevents stale publication if the
run changes during loading. GET never initializes records. Empty-object POST is
idempotent by the source snapshot; it approves no facts and fabricates no claim tags.
Original displays check the requested fragment against that immutable snapshot and
recheck the committed run's source/graph pins before returning the image.

`tests/acceptance/test_source_condition_api.py` exercises real local upload/parser/HTTP,
including initial 409 without a record, CSRF rejection, malformed/oversized/extra-field
JSON, repeated publication, unmodified read/view state, PNG hash matching, missing
fragment 404, injected run epoch race 412, viewer 403, foreign-tenant 404 and logged-out
image 401. Existing store/view regressions retain atomicity, source replay and immutable
history checks. No model or source-approved graph was mocked to make these pass.

Full `proofops_api.main` composition was additionally exercised against existing real
worker checkpoints using local synthetic reviewer sessions:

| Report | Physical page | Inventory entries | Retained issues | Source snapshot SHA256 |
|---|---:|---:|---:|---|
| Samsung Electronics | 72 | 260 | 1 | `49ad12ba1a91488a3f6d10831b9e9ddfaf2c70564ebfae9437c8c4228a728096` |
| LG Chem | 97 | 228 | 3 | `7fa2fcb6334dd8a0f66091107189b7abfe4741e119801e625d16466321dd24ca` |

Both published revision 1, returned unknown coverage, served the prior visually checked
original page image with its expected hash, and retained unchanged review state after
viewing. The five-request local sequences took 3.808s and 2.869s respectively; these
single runs are not latency percentiles or load-test evidence. **Zero model calls**.
Private receipts and results: `.local/note-review-integration/source-condition-api-v1/`.
The harness initially lacked the test-helper import path; rerunning with explicit
`PYTHONPATH=.` completed without changing production imports or creating an external model client.

Orca contract worker: `task_1dd1728fb93f` / `ctx_58b18879f470`, completion
`msg_69aba65e9279`, changed only the two contract files. Independent read-only review:
`task_6dccbd9909a8` / `ctx_64c08eb14314`, completion `msg_80b7dd8b8daa`, passed seven
focused tests and a temporary native-note replay; no reproducible scoped defect found.
Both workers were released and their deliveries acknowledged.

Verification:

- `uv run pytest -q`: **1917 passed**, two existing dependency warnings, 149.41s;
  `.local/note-review-integration/source-condition-api-full.log`.
- `uv run ruff check .` and `uv run ruff format --check .`: passed, 287 files.
- CI mypy command: passed, 170 source files; existing untyped-body notes retained.
- `uv run python scripts/verify_architecture.py`: passed.
- `uv build --all-packages`: four Python packages built. Isolated wheel replay reopened
  18 actual worker checkpoints with identical graph hashes and zero model calls
  (`source-condition-api-wheel-replay.json`).
- `uv run python scripts/validate_package.py`: 775 document/contract checks passed,
  48 operations. This is not application accuracy.

Remaining: factual revision/confirmation API, source-view receipt persistence and
replay at write time, supported condition/ownership/coverage validation, actual numeric
checker invocation and immutable numeric receipts, shared approved-view consumers,
and browser review UX/E2E. These remain not_run, and the overall service goal remains
incomplete. No new dependency, external model call, AWS action, push or deployment.
