# Nested table cells in native note target inventory

An actual POSCO Future M p139 parser delivery exposed a service bug: the original
canonical graph retained table → row → cell edges, but native note packet preparation
listed only direct table children. The exact total-label and value cells were absent
from the model/review candidate catalog. Version 3 now follows one explicit row chain
to its root table and includes those original cells. It rejects cyclic chains, competing
row parents, missing table roots and non-row intermediates into unresolved_source_ids,
rather than collapsing them to one owner or silently dropping orphan cells. A leaf's
unlocated status remains explicit candidate uncertainty under the existing contract;
an unresolved ancestor cannot confer a located lineage. No marker, source-quality,
condition, numeric or coverage acceptance is added.

Version 2 preparation remains available only for exact historical replay. Known old
validator/layout pins can replay v2, not a relabeled v3 packet; unknown versions/hashes
fail closed. No existing parser checkpoint, note artifact or source-review revision is
rewritten. New creation defaults to v3. Rollback must retain a v3-capable reader and
stop new v3 creation; no DB migration or automatic downgrade was performed.

The nested-cell regression failed before implementation. Independent Orca review
`task_1332442bc98e` / `ctx_1b0e4180eef5` found a cycle/ambiguous-parent hole in the
first draft. Four failing cyclic/competing/orphan/non-row cases were then added and
fixed with bounded original-parent traversal. The existing unlocated-leaf test caught
an overbroad exclusion; it remains unchanged and now passes. Final focused run: **46
passed, 2 dependency warnings in 5.99s**. The reviewer also checked five v2 canonical
byte comparisons, known/arbitrary validator pins and five focused tests. It settled,
was released and acknowledged; its review preceded the coordinator's final fixes.

Actual POSCO p139 canonical packet comparison: **8 → 18 targets**, including original
label `bda39b7a-386a-5efb-b89b-8436909e703a` and value
`eb8fc516-f8ed-5538-8d36-6ca656dca4a1`. V2 serialization hash and committed graph remain
unchanged. Final v3 packet hash:
`cc7c30abbaa24025c13f5df0c65e75ddc63236cc170477c1b8965415528c1d04`;
artifact hash `a418275145b588c5c3a8d0d9f8000a285105e4388ce7bbfa86a2188376e0a6ae`.
Private final packet/artifact: `.local/note-review-integration/nested-note-targets-real-v2/`.
All 18 older installed-wheel checkpoint replays retained original graph hashes; POSCO's
newly added v2 checkpoint also reopened with its original published hash.

Orca design audit `task_47537a4731dd` / `ctx_28cf62d1bfb4` inspected the actual PDF,
packets and lineage, and identified both the omitted cells and independent geometry
holds. The total-label native glyph extends below the parsed total-strip boundary by
about 1.317pt; marker/base glyph boxes overlap horizontally by about 0.078pt. The page's
visible table is fragmented into header/total strips, so relaxing marker proximity
would not prove full table ownership. The audit worker settled and was released/acked.
The two-line note spans f97/f100 (native words 393–406 and 412–416); approving only f97
would omit a remainder. Even proven ownership would leave its rounding prose unsupported.

A second report, Hanwha Solutions p169, was visually inspected but the existing upload
validation rejected the PDF with PDF_INVALID during preparation. That failed state/log
is retained under `original-marker-worker-v1/hanwha-solutions`; no parser delivery or
model request was made for it. This is a pending ingestion investigation, not a passing
cross-report case. POSCO original SHA256:
`65070d88297d4faf631a9545e6aa49b56ccae71531dda0248f69a3887ab779a8`.

Ruff lint/format (291 files), CI mypy (172 files), architecture checks and all four
package builds passed after the fixes. Model/AWS/deployment/browser-interaction checks
were not_run. Actual model calls: zero; cumulative ledger unchanged at USD7.8339376000,
1359 calls and six historical unsettled reservations. Native ownership approval,
source-derived geometry repair, condition coverage and immutable numeric receipts still
remain before the full service goal can be claimed.

A fresh actual worker delivery using the final v3 implementation also committed under
`.local/note-review-integration/original-marker-worker-v2/poscofuturem`: 3 parsed table
fragments, 18 candidate targets, note extraction explicitly not_run, zero model calls.
Published graph SHA256 `52b83843001cf4e2d130358bf0f011d58d2828bfc42206d59851967aea97b3ad`;
native artifact `a22c9ca878cfd5bdef65839db4afcdbb4262430262fdf884a93e26ef9aa64831`.
The older v2 run remains unchanged. This verifies new worker publication, not merely an
in-memory new packet, while retaining every native note/coverage hold.

Final full application suite: **2071 passed, 2 warnings in 147.19s**;
`.local/note-review-integration/nested-note-targets-release-full.log`. An earlier full
run using the intermediate overbroad unlocated-leaf exclusion was stopped once that
known regression was fixed; it is not counted as a passing run. Final documentation/
contract validation passed 790 checks (50 operations), not an accuracy measurement.
