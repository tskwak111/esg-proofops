# I29 · finals-20261016-v29

I29 composes the authorized CF1, CF2, CF4, CF5 and CF6 policies on the complete
v28 policy. `finals-unattended-v2` selects v29 for new runs. CF3, CF7, QT5 and S6
are excluded. The authoritative changes are DEC-125 and DEC-127 in the R108
decision log; their scoped treatment of unknown supersedes the older blanket
unknown-to-absence prohibition.

## Decision and evidence

- CF6 requires three completed replicas and unanimous claim type. Two verified
  element votes must agree on value, attribution and scope. A verified opposite
  source or conflict vetoes confirmation.
- After three completed replicas, elements not verified and linked inside the
  selected pages become `absent_in_scope`. CF1 inventory completeness is not a
  prerequisite for this DEC-127 rule.
- Only the Python rule engine assigns grades. An unverified claim, unresolved
  claim type, grade-blocking rule gap, conflict, unreadable input or unfinished
  TIME_BUDGET item remains held. Source verification remains mandatory for present.
- CF1 restores unique literal offsets in inventory responses. CF2 bounds C3
  citation lookup to the approved source span and retains review receipts. CF4
  adds exact native/region OCR recovery. CF5 preserves full local context for
  preliminary interpretation without granting that context source authority.
- v28 memory, publication digest, input isolation and deadline policies remain.

## API and historical compatibility

CF6 adds `cf6_confirmation`, `cf6_status`, `cf6_elements`, `cf6_track` and hold
diagnostics. Its decided result also uses the existing `decision` and
`confirmed_grade` fields. Existing manual decisions retain priority. SC1 fields
and old projection meanings remain readable. The web can display E0 as confirmed;
confirmation describes a completed scoped rule decision, not a positive grade.

v28 remains pinned at
`31808287164e43e17495bccb17e31e7c53c7746ff0f7c9148276958f7d28cab2`.
Policy objects, original receipts, source graphs and prior result revisions are
immutable. Saved server vote evaluation is counterfactual only: it cannot reseal
old responses, publish new confirmations or measure changed prompts/OCR.

RC1 `514887e` adds opt-in sealed result reuse after resolved policy/scope options
and before quota admission. `RC1_RESULT_REUSE_ENABLED` defaults to false; the
coordinator controls activation in `runtime.env`. The cache key includes the
assigned analysis pin, effective scope and reporting period, so v28 cannot seed
v29. Reuse creates a separate immutable run with no provider cost or reservation.
Its additive audit table/index/trigger initialize with the existing control DB;
existing rows and result revisions are not rewritten. See `rc1-result-reuse-v1.md`.

Rollback uses `e6b1a8f` and the v28 pin for new work. First disable result reuse;
RC1 copies must remain behind an RC1-compatible reader because a pre-RC1 reader
lacks detached-copy integrity and coordinate support. v29 results also remain
under a compatible reader. Deployment and rollback both
require the existing API 1536 MiB compose override. I29 does not push, deploy,
change EC2 or call the real OpenAI API. Local evidence and the final deployment
handoff are in `outputs/agent-results/R108-redesign/lab/perf/I29/` in the project root.
