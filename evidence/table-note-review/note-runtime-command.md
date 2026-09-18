# Runtime note extraction and CLI input — 2026-09-14

The parser command accepts repeatable `--note-review-artifact FILE` arguments.
Each file contains the exact canonical JSON returned by freeze_note_review, bound
to this run's prepared graph and original PDF. Reading is UTF-8 with a 16 MiB limit
per artifact before runner construction. Input paths/content are excluded from
runtime error logging. Only the parse stage accepts the option; other stages reject
it before constructing a runner. No implicit model calls are introduced by this flag.

```
uv run python -m proofops_worker.main --once --stage parse \
  --tenant-id TENANT_UUID --run-id RUN_UUID \
  --note-review-artifact page-one-review.json \
  --note-review-artifact page-two-review.json
```

Existing LOCAL_DATABASE_PATH and LOCAL_PARSER_PROFILE_PATH composition settings
still identify the exact store/parser. The existing immutable job input binds the
artifact tuple. Retries may omit file arguments and rehydrate it from SQLite;
resubmission of different artifacts rejects. Prior archives, parser manifests and
published checkpoints are never rewritten. The optional CLI input does not change
public HTTP or database-column contracts. See note-checkpoint.md for v2 migration
and rollback requirements.

The library extractor is moved from evaluation into the installed adapter package,
with explicit evaluation compatibility reexports. It retains original-source
validation, discovery/binding prompts, request/response archives, bounded splitting
and unknown coverage. Its source-code hash changes with the move; new requests pin
the packaged helper while historical receipts remain unchanged. This packaging
change alone does not configure a live provider or authorize a new budget ledger.

This is input/transport availability, not completion of automatic note review for
all reports. Initial per-run graph preparation and provider selection still need
connection in the service composition. No semantic note approval is implied.

## Executed evidence

The actual worker subprocess test was extended with a notes variant. Before the
CLI change it failed on the unsupported option. After the change it imports a
canonical artifact against an actual generated/uploaded PDF, persists v2, and a
second subprocess without file arguments reloads the durable input. Changed input
and notes supplied to extract are rejected; invalid UTF-8 and >16 MiB files reject
before parse publication without leaking the sensitive filename. The legacy
no-note command still passes. Parser integration: 27 passed; final expanded CLI
variants: 2 passed. These generated-PDF checks are separate from the real-report
archive replay below.

A python -I process prepended the built proofops wheel and explicitly rejected
imports of evaluation/scripts/tests. It ran the full packaged extractor on the
original PDFs and exact archived graphs, using an offline client that checks each
prompt/wire hash before returning the matching historical response. Seven stored
responses and Samsung Life's preflight rejection were replayed; no network client
or new paid call was used. New request/result directories preserve old archives.

| Report | Notes reproduced | Request stages reproduced | Coverage | Decision |
|---|---:|---|---|---|
| Kia | 3 | discovery, binding | unknown | null |
| Kakao | 6 | discovery, binding | unknown | null |
| Samsung Life | 12 | preflight rejection, split discovery x2, binding | unknown | null |

Notes, packet hash, coverage and decision exactly match the archived validated
results. This is behavior-preserving replay, not a fresh model accuracy benchmark.
Both prompts and join_note_lines are AST-identical to the pre-move implementation.
The original-source validator and layout code were not changed.

Reproduction: `.venv/bin/python -I .local/note-review-integration/check-packaged-extractor.py NEW_OUTPUT_DIRECTORY`.
Evidence: `.local/note-review-integration/packaged-extractor-replay-v1.json` and
`.local/note-review-integration/runtime-extractor-wheel-v1/{kia,kakao,samsung-life}`.

Final checks: full pytest 1877 passed, 2 existing deprecation warnings, 136.84 s
(`.local/note-review-integration/pytest-note-runtime-command.log`); Ruff passed;
full CI mypy command passed 166 source files; all package builds passed
(`.local/note-review-integration/build-note-runtime-command.log`). Documentation
and contracts passed 758/758, which is not an application accuracy benchmark.

Orca packaging task `task_298df43185d0`, dispatch `ctx_12e004c25765`, completion
`msg_a12f9cb8b25b`: 25 focused extraction/packaging tests passed; validator unchanged.
The same settled terminal was reused for an independent review of coordinator CLI
changes while the coordinator reviewed the packaging diff and executed wheel replay.

Independent CLI review: task `task_126c9030527b`, dispatch `ctx_d8fc61bcf406`,
completion `msg_d79829fd56ba`: no blockers; independently reran both real command
variants and scope/error-privacy test. After accepted completion the worker was
released, its exact terminal closed and delivery acknowledged. This is agent review,
not human approval or production certification.
