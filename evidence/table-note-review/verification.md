# Source-bound table notes in report review — 2026-09-14 KST

The existing report-demo CLI now accepts an archived note packet/result and its
exact CandidateBatch. It revalidates the original PDF and packet, tenant/document
version/source hash, exact table identity/page/cells/spans and the existing numeric
candidate discovery output before attaching anything. Both body and note parse
manifest IDs are retained: these are separate parser stages over the same source,
not an invented shared parse identity. No API/DB contract or dependency changed.

Notes follow the value and its bound year/unit/metric/covered row-column headers.
Preceding subtotal rows do not confer ownership. Unassigned notes appear once at
page level. Returned artifacts are new deep copies, with new content hashes and
request/result provenance. Duplicate table projections, foreign source identity,
changed cells and altered numeric candidates fail closed. All note coverage stays
unknown; numeric checks are explicitly not_run, admission blocked. No rule grade
or source approval is produced by this evaluation projection.

## Actual replay and display

Final local artifacts:
- `.local/note-review-integration/samsung-life/review-final/index.html`: 1 claim,
  190 cell candidates, 116 with proposed note context; 12 source note proposals.
- `.local/note-review-integration/kakao/review-final/index.html`: 13 claims,
  114 cell candidates, 60 with proposed note context; 4 assigned and 2 unassigned notes.

Counts include missing/non-numeric cells and are not accuracy or accepted-number
counts. These are declared-page subsets, not complete-report coverage. Samsung's
older review belonged to another tenant/version and was not mixed into this run.
One new Solar Pro4 claim call used the current identity (USD0.0002349600); all note
and table records were replayed without paid calls. Shared committed/reserved
ledger is USD7.8065947900 across1334 calls, with6 old unsettled reservations intact.
Kakao's stale section map was rejected; a fresh local map was generated before
replaying existing claim receipts. Old reports/receipts remain unchanged.

The final Kakao HTML was opened in Orca's embedded browser. Snapshot and two
screenshots confirm readable table rendering, separately listed unassigned notes,
PDF page links, proposed note text and explicit withheld judgment. Screenshots:
`.local/note-review-integration/kakao/{screenshot,notes-screenshot}.png`.
This checks the review artifact UI, not a deployed application E2E.

Orca Muse Spark1.3 Free independently reviewed task task_fd9a10ddbcd1,
dispatch ctx_7c50861f5535, run run_bd4f467aede6. The dual-parse identity concern is
addressed by explicit provenance pins and exact source-cell replay; unprocessed
tables retain unknown coverage. The worker settled, was released, its terminal
closed and delivery acknowledged. No active model worker is needed for this replay.

## Verification and remaining scope

Ruff passes; mypy passes162 source files (untyped-body notes remain); all4 Python
packages build. Documentation/contracts validator passes758 checks, separately
from app testing. The integration regression covers cross-year isolation,
source/cell mismatch, immutable packet/demo copies, duplicate tables and failed
extraction/unassigned display. Full suite result is recorded below.

Production numeric-service wiring, full-cell source verification and semantic
interpretation of conditions remain open. This change makes unresolved conditions
reviewable; it does not certify service readiness or complete the active goal.

Final full suite:1838 passed,2 existing deprecation warnings,124.26s;
`.local/note-review-integration/pytest-final.log`. Diff check passes.
