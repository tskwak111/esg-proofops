# Literal reporting-period guard — 2026-09-13 KST

A literal match is insufficient when the reporting-period tag contains a metric,
unit or uninterpretable date. The shared pure `is_supported_period` guard applies
to new `accept_binding` and `check_numeric_consistency` calls. It recognizes
whole-string years (optional FY prefix or 년 suffix), optional Q1–Q4 after a year,
ordered year ranges with -/–/—/~, ISO dates and ordered ISO date ranges with
~/–/—/to or a spaced hyphen. Dates must be valid Gregorian calendar dates.

This is a limited parser capability, not a domain criterion or complete period
ontology. Unsupported legitimate forms, relative periods and narrative context
remain unresolved. No conversion of fiscal years to calendar years, period alias
matching, trimming of narrative to extract a year, inferred reference dates or
rewriting of source text occurs. Supported syntax alone does not prove the
semantic role; original source, coordinates, identity, literal equality and other
existing attribution gates remain necessary. Four-digit quantities wrongly tagged
as a year still require upstream semantic/source review.

Unsupported matching period tags yield binding_state=undetermined. Numeric checks
yield not_comparable with reason=reporting_period_unresolved when their selected
periods, including a reduction baseline, are unsupported. Earlier source/value
failures retain precedence. Neither result is absent, present or a grade.
Raw normalization and its original period field/source refs are unchanged.

Existing API/DB shapes remain valid; no migration or dependency is added. The
new numeric reason is a string within the existing result contract. This guard
applies to newly computed results; historical revisions, source snapshots and
paid receipts are not rewritten. Future re-evaluation must create a new revision.
Rollback disables new automatic binding/numeric checks until this guard is restored;
do not reinterpret saved accepted states or present rollback as source approval.

Test scope: reproducible synthetic source/tag fixtures, no human gold. The local
LG Chem nine-assignment fixture replay remains byte-equivalent at observation
JSON level and all nine period strings are supported; it is not a generalization
benchmark or actual model-tagging trial. Real Upstage element-tagging composition
remains separate work.
