# Explicit manual scope selection v1

GD2 requires gold physical claim pages and the AS1/gold evidence union. Add optional
`manual_selection` (strict boolean, default false) to POST
`/v1/documents/{id}/scope-plan/selection`. True bypasses only AS1 category restrictions.
It does not establish readability, evidence admission, element presence or a grade.
Source identity, proposal hash, sorted unique physical pages, claim-in-evidence,
10/30 page caps, CEO cap, editor/tenant authorization and If-Match remain required.

A true selection records `manual_selection=true` inside the immutable selection
and its existing hash, propagated to pinned run options. Existing requests,
automatic scopes and failed-plan recovery retain their behavior. No DB migration;
JSON readers accept the additive field. Rollback: stop new manual-mode runs before
reverting; preserve all selections, runs and result snapshots. Previous code can
read pinned options but cannot create this new selection.
