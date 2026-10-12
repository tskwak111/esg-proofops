# E06 opt-in discovery and page reduction

Baseline: `int-20261011` / `bdbe050`. Authority: X7 QUALITY-STABILITY-SPEC §4–5,
CONFIRMATION-SPEC §3, execution-plan X7-E06. This is declared subset discovery,
not full-document completion or evidence admission. Default AS1/W4 readers and
hosted deployment settings remain unchanged.

## Execution and artifacts

`python -m evaluation.e06_scope --pdf REPORT.pdf --output NEW.json --profile E06
--tenant TENANT --ocr-cache PRIVATE_CACHE` runs local native inspection, then free
CPU OCR only when the native environmental scope failed. Native covers and other
unreadable pages remain visible and do not trigger OCR in a working native scope.
The installed compiled Apple Vision reader or the existing pinned Linux Tesseract
runtime is reused. An unavailable reader remains unresolved; no provider fallback,
new dependency, network transport or credentials are introduced.

Discovery reads first/last six physical pages, then remaining pages, within page,
wall and per-call limits. Default page cap is 24. Runtime, tenant, original/input
SHA, physical page, pixels, rotation/CropBox and actual resolution are cache-bound.
OCR text is `discovery_only`, unverified, and excluded from native reporting-period
confirmation. Search exhaustion and a usable scope are separate states. Unsearched
and unresolved pages stay explicit. No source bbox, element state, assurance
coverage, grade or label is approved by this path.

`E06-scope-v1` can restore actionable environmental summaries outside section
routing and use spare slots for nonnumeric governance or missing dominant topics.
Existing non-CEO claim pages are retained; one CEO page remains. These ranking
signals are discovery heuristics, never domain grading rules or full-mode quotas.

## S18 and S14

The internal `S18` profile freezes baseline claim pages, requests a union cap of
18, protects support candidates and selects entire discovered assurance runs.
Known support or bundle loss rejects the reduction and restores the union cap to
30, with both proposed and effective selections retained. If even 30 cannot hold
required support, the plan fails with `EVIDENCE_BUNDLE_INCOMPLETE`. Short scopes
are not reduced. A selected bundle is still `assurance_status=undetermined`.

`S14` is a separate non-adopted lightweight proposal with claim cap 8 and union
cap 14. Removed baseline claims/support and incomplete bundles remain visible.
Manual selection cannot exceed its claim cap; missing bundle pages are recomputed
in the applied selection. Legacy `max_evidence_pages` remains the total union,
including claims. Requested and effective caps are recorded separately.

Adoption still requires no direct-source/binding/semantic-recall loss and a paired
performance gain. The current Kakao S18 fails support retention and is rejected;
local ODL timing is not paid precision-parser or end-to-end model timing.

## Compatibility and rollback

The new proposal/version is opt-in; AS1/W4 policy hashes and serialized defaults
are preserved. Existing immutable proposal hashes, source identity, physical
bounds, tenant checks, CAS revisions and report snapshots remain enforced. Public
request/response and DB schemas are unchanged; there is no migration. New metadata
lives inside existing opaque scope artifacts. A reader without E06 support rejects
its policy rather than silently reinterpreting it. Rollback stops creating E06
plans and retains the E06 reader for previously stored plans; no old artifact is
rewritten. Production hosted enablement remains a coordinator deployment task.
