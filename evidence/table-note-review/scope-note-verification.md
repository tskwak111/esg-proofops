# Bounded Scope notes in normalization and numeric checks

The shared numeric grammar recognizes only a complete trimmed `Scope 1`, `Scope 2`,
`Scope 3`, or `Scope:` followed by optional whitespace and one of those literals.
Geography, exclusions, arbitrary prose, alternate capitalization, combined scopes and
unsupported scope numbers remain uninterpreted. This implements the existing finite
syntax in source-condition-review-contract §3; it adds no rubric or grade criterion.

Both automatic table normalization and explicit cell-role normalization use the same
helper. An explicitly owned note can supply missing scope, retaining the full original
reference and the value-to-note scope role. A conflicting cell scope is retained and
marks the observation conflicted with no numeric value; unsupported Scope-prefixed
prose remains unreadable. Normalization still does not verify source quality.
The normalizer signature is version 4, so changed semantics cannot reuse version-3
observation IDs. Existing stored observations, graphs and reports are not rewritten;
rollback uses the previous code and its original immutable artifacts.

The numeric checker requires complete verified original note references and the literal
must match the observation scope. A scope-field note reference also needs actual note
ownership, not merely presence in a collection of source quotes. Unresolved sibling
notes and source issues still block computation. A matching scope is not evidence of
organizational boundary, geography, method or complete page coverage.

Initial normalization regression: five failures in
`.local/note-review-integration/scope-normalize-red.log`; the same five cases pass after
implementation. They cover both normalizers, missing scope, conflicting scope,
unsupported remainder and neighboring year isolation. Orca task `task_0d5b56fcd8dc` /
dispatch `ctx_9c523a3f729e` owns the numeric grammar/checker regression work; the
coordinator owns normalization and reviews integration. Its 248 focused tests passed;
the coordinator reproduced and fixed wrong-year extra-reference admission and preserved
the graph-ancestor guard before accepting relation targets. Both bare and prefixed Scope
notes are covered by the negative regression. The worker settled successfully and was
released/acknowledged. Coordinator tables/numeric suite: 183 passed in 1.36s.

Lint and format (287 files), CI mypy (170 files), architecture checks and all four
Python package builds passed. Full suite: **1967 passed, 2 warnings in 143.72s**;
log: `.local/note-review-integration/scope-note-full.log`. Document/contract validation:
782 checks passed (not an accuracy metric).

Installed-wheel replay reopened 18 actual worker checkpoints with unchanged graph
hashes and zero model calls. Applying automatic normalization to each returned **zero
observations**, so this proves replay compatibility, not successful real-report numeric
comparison. These checkpoints include selected note/table pages with layouts not
recognized by the automatic normalizer. Explicit role normalization currently has an
evaluation caller (`evaluation/e_scope_case.py`) but no production caller. The next
service step must connect original-backed factual table roles to normalization and the
numeric receipt path, then demonstrate a nonempty real-report comparison. Detailed
per-checkpoint counts: `.local/note-review-integration/scope-note-wheel-replay.json`.

A follow-up used the existing evaluation LG Chem p97 role assignments against the
current installed-wheel checkpoint. The nine original-cell assignments normalized to
nine **unverified** observations with unknown Scope, not verified comparisons. An initial
harness lookup using zero-based row/column coordinates failed: current candidates retain
one-based coordinates. Using the existing exact native source IDs succeeded without
changing parser coordinates or immutable artifacts. This confirms the explicit role
normalizer works on this actual table while its service input path remains missing.
Private output: `.local/note-review-integration/scope-note-lg-explicit.json`.

This is an internal numeric/normalization integration, not a completed source-review
service path. Factual HTTP annotation records still do not promote source quality or
create accepted ownership/conditions, numeric receipts or coverage completion.
Actual HTTP positive comparison, approved-view consumers and review browser E2E remain
outstanding. Synthetic verified fixtures demonstrate the finite rule; they are not
independent human verification or corpus accuracy measurements. No external model call
is required for this work.
