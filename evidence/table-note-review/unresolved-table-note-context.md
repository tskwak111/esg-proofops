# Unresolved table structure and page-note discovery

The real automatic worker failed on Samsung Life p121 before any request because
canonical table winners were unresolved. Notes are native source-page text and do
not require selecting a winning table parser. Note preparation will explicitly
request page context for unresolved tables; their table rectangle, targets, cells
and marker bindings remain unavailable. No graph winner, candidate, edge or existing
quality issue changes. Cell/role/crop callers retain strict layout behavior.

Runtime artifact compatibility is bounded: the exact v1 validator/layout hash pair
from commit 125bbaf is accepted only for packets with all tables resolved and located,
and only after current source/packet/result replay and original digest validation.
Unknown code hashes still fail. New unresolved packets cannot impersonate that old
profile. Existing stored artifact bytes, IDs, checkpoints and reports never change.
No public API or DB schema changes. Rollback must retain the new reader for new
unresolved packets; old readers cannot silently discard their uncertainty.

Discovery may receive untrusted parser-region hypotheses after checking each
candidate's geometry against the actual PDF and page bounds. Their `uN` identifiers
are never source references or ownership targets. This restores column context
without picking a parser winner. For unresolved discovery only, request-local `nN`
fragment aliases avoid gaps in global fragment numbering; the exact alias map,
wire hash and raw response are saved. Surrounding whitespace on generated protocol
IDs is stripped before exact allowlist lookup. Raw PDF text is never normalized by
this step, and cross-request/global IDs and duplicate normalized citations fail.

Independent Orca review ctx_f1fffe3216b3 identified an actual CropBox gap; four
failing regressions reproduced it, and the shared layout reader now rejects actual
CropBox/MediaBox differences regardless of winner. Review ctx_8320acc4168f found no
blocking regression in the context/hypothesis change. Bounded alias review
ctx_b9fbac4bac61 found no finding, including separate duplicate and receipt checks.
All three review workers were released. These are agent reviews, not domain approval.

## Actual source evaluation

`unresolved-note-evaluation.json` records every live iteration, including failures.
The first fallback emitted 19 proposals: 10 matched reference note word sets,
9 were non-notes (including company names and footer text), and 2 notes were missed.
Adding region context exposed an invented global fragment ID; dense local aliases
then exposed leading whitespace in two valid returned IDs. Both failures stayed
unknown and published no invented note evidence. Exact replay of archived replies
with whitespace-safe alias lookup recovered all 12 reference note word sets, no
extras, with zero paid calls. A fresh real worker run (v5) independently obtained
12/12 exact word sets, no extras, using two paid requests, and replayed without calls.

The reference consists of the page's four left and eight right numbered notes,
compared against the rendered original source and the earlier archived source-bound
note groups. This single-page result does not estimate performance on unseen reports.
All 46 original parse-conflict issues and unresolved ownership/scoring states remain.
The cumulative authorized ledger is USD7.8195647800 / USD10, 1343 calls; six older
unsettled reservations were untouched. No AWS/deployment or domain label approval.

Before-upgrade Kia/Kakao checkpoints retained their exact graph hashes. The golden
synthetic legacy fixture was generated from actual `git archive 125bbaf` package
source (fixed parser UUID), not by merely changing a new artifact's hash fields.
The old known profile accepts only source-revalidated resolved/located packets;
unknown profiles and new unresolved packets disguised as old are rejected. Old
unsafe cropped geometry is intentionally rejected rather than grandfathered.

## Final verification

- `uv run pytest -q`: 1901 passed, two existing dependency deprecation warnings,
  142.73s; `.local/note-review-integration/pytest-unresolved-notes-alias-final.log`.
- Ruff lint and format passed; CI mypy passed on 167 source files.
- `uv build --all-packages` passed for all four workspace packages.
- Isolated `python -I` reads from extracted final wheels, with development imports
  blocked, preserved all six actual checkpoint graph hashes (Kia, Kakao, and four
  Samsung iterations), including the earlier failed/unknown outcomes. No new calls.
  Receipt: `.local/note-review-integration/unresolved-notes-wheel-replay.json`.
- Document/contract validation passed 761 checks; this is not an application benchmark.
- On final Samsung v5, base and reviewed blocks/candidates/edges were identical,
  all original issues remained, 46 parse-conflict issues persisted, and four open
  note-review issues were added. Every returned note had empty targets and remained
  ineligible for scoring.

The task goal remains active. This resolves the reproduced conflict-to-note abort
and the targeted page's discovery failures. Unseen-layout evaluation and trustworthy
note-to-cell ownership still need evidence before claiming service readiness; this
change deliberately makes neither a corpus-wide accuracy claim nor a grading claim.
