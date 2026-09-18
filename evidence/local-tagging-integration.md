# Local tagging integration contract

Run creation may optionally freeze a complete TaggingSettings value with explicit
`tagging_mode=local_synthetic`. The selected model binding/model/region/output limit
must match the approved runtime snapshot. Extraction configuration is required for
this optional downstream stage. Existing runs without tagging settings remain readable
and retain parse/extract behavior; they cannot silently adopt a later configuration.

This adds optional fields inside the existing immutable run snapshot JSON, not a public
RunCreate field or SQL table. Its canonical input hash covers the new settings and mode.
Old snapshot readers ignore the extra fields. Rollback stops tagging workers and keeps
all snapshots, original documents, jobs and revisions; no data rewrite or deletion.
Real product model transport is not authorized by these local settings.

Implementation and actual verification are in progress; no finished tag pipeline is
claimed by this contract note.

Run-setting freeze verification: the new actual HTTP regression first failed because
tagging_settings was missing from the immutable snapshot. After implementation all
37 run-lifecycle checks passed, including frozen complete settings/hash, approved
model/binding/region/output-limit matching, no synthetic-to-real adapter switch, and
idempotent old-run recovery despite later configuration changes. Scoped Ruff and
checked-body mypy passed. This verifies configuration freezing, not tag execution.
