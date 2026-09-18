# Note review publication contract — 2026-09-14

Before any extraction/tagging publication, LocalParserRunner may receive a tuple
of canonical runtime_note_review_v1 artifacts bound to its exact prepared graph.
It replays original-source validation before publishing local_parser_checkpoint_v2,
which retains all v1 fields plus runtime_note_review_artifacts (nonempty JSON list)
and graph_sha256 (the rich derived graph). The fenced checkpoint and next extract
outbox commit together using the existing transaction; no database column or public
HTTP request shape changes. Prepared private files never publish note evidence.

The shared load_run_graph reader accepts v1 without note fields, or v2 with both
fields and a matching replayed graph hash. Unknown versions, partial note fields,
invalid notes and inconsistent graph hashes fail closed. Old v1 checkpoints remain
byte-for-byte unchanged. New reviews cannot be added to an already published parse:
use a new run; do not mutate a historical checkpoint or rebase a note artifact.
Retries reuse the durable input; a supplied nonempty tuple must match it.
Committed runs verify a supplied tuple rather than silently dropping new input. No model calls are added by this path.

Migration is an additive immutable checkpoint version, not an in-place rewrite.
Deploy readers and writers together; do not roll a database containing v2 runs back
to a reader that ignores v2 note fields. Rollback must retain the v2-aware reader or
make those runs unavailable; stripping notes or converting v2 to v1 is forbidden.
Coverage remains unknown/open. Runtime replay cannot approve a note, source or grade.
An omitted tuple preserves legacy execution and makes no note-coverage claim.

## Durable retry input

The existing job_records table also stores one immutable parser_note_input record
per parse job (JSON array of canonical artifacts, including an explicit empty
array for new legacy executions). Binding occurs under the active lease before
validation; it does not publish evidence or mutate the frozen run snapshot.
An empty/default argument on retry reads the existing binding. A nonempty different
argument is rejected, even before first publication; corrections require a new run.
Commit compares the checkpoint artifacts with this binding in its transaction.
The shared reader checks the same binding; v2 without a binding is invalid.
Historical v1 jobs without a binding remain readable. Retention follows existing
run/job_records retention; rollback retains this record with the checkpoint.


## Executed boundary checks

The first failing integration test showed that the runner had no note input.
After initial implementation, an injected crash immediately before checkpoint
commit followed by a retry without arguments reproduced a v2-to-v1 downgrade.
The immutable lease-bound input fixes this root cause: retry reloads the tuple,
revalidates original PDF notes and commits v2. A deliberately downgraded v1 commit
is rejected inside the transaction before either checkpoint or extract publication.

The tests also reopen SQLite, compare the derived rich graph hash, reject duplicate
or changed note input, bad schema/hash and checkpoint note removal, and confirm
invalid notes publish neither parse nor extraction. A separate upload/parse/extract
integration checks that LocalClaimStore replay pins the derived graph after restart.
This uses an actual generated PDF and a synthetic extractor; it is a runtime
provenance test, not real-report claim accuracy or a new paid-model evaluation.

No new HTTP input/automatic note extraction/provider dispatch was added. A local
caller must prepare source-bound artifacts before the first parser delivery.
The production API still does not select a note provider or automatically review
all eligible tables. Historical runs and source artifacts are not rewritten.

A second negative test reproduced direct v2 publication without any durable input
binding. It now rejects NOTE_REVIEW_INPUT_NOT_BOUND before advancing extraction.
This prevents a malformed v2 checkpoint from being published even though downstream
replay would already reject it. Focused parser tests: 26 passed; parser/extractor
integration before this additional fence test: 49 passed. Ruff passed; full CI
mypy command passed 165 source files; all package builds passed. Documentation and
contract validation passed 758/758 (not an application performance measurement).
No paid model calls, original-report edits, API/DB-column changes or deployments.

Final regression: `uv run pytest -q` — 1875 passed, 2 existing deprecation warnings,
133.86 seconds. Log: `.local/note-review-integration/pytest-note-checkpoint-final.log`.
Final wheel/sdist build log: `.local/note-review-integration/build-note-checkpoint-final.log`.

Orca independent reviews (Muse Spark 1.3 Free): initial architecture task
`task_aedaa9b6d2f3`, dispatch `ctx_ffa0a52c0838`, completion `msg_5199e1f43d9f`
identified missing schema/retry binding boundaries addressed above. Final task
`task_7ee749e81f63`, dispatch `ctx_c9afccfd2c7f`, completion `msg_e9748add2cac`
reported no correctness blockers and independently ran the 26 parser tests.
Its nonblocking note: binding errors use generic PARSER_FAILED telemetry; automatic
provider selection remains out of scope for this checkpoint change. Both workers
settled, were released, their exact terminals closed, and deliveries acknowledged.
Agent review is not human approval or production certification.
