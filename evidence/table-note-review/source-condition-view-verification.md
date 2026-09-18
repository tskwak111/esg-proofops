# Source-condition original display receipts

The committed-run source loader now exposes the same verified base graph, original
bytes and registered note artifacts used by graph replay. Existing graph consumers
retain the same return value through `load_run_graph`. `render_run_fragment` resolves
only a note artifact actually published in that run; caller-provided note bytes are
not a runtime substitute for registration.

Display receipts bind canonical candidate identity/raw offsets or native fragment IDs
and exact word unions to PDF/page/geometry/PNG and implementation hashes. Tampering
with image/page/quote and recomputing a caller-side hash does not pass original replay.
No graph, source quality, note ownership, numeric result or grade is changed.

Orca task `task_33da8fc760a6`, dispatch `ctx_13c849246f71`, found a real display defect:
FreeText and Square annotations without appearance streams were accepted but hidden
by the old preview renderer. Two failing PDF regression cases reproduced this. The
new optional rendering mode draws default annotations and initializes/draws AcroForms;
the old preview default is unchanged. XFA and optional-content layers are unsupported,
not silently stripped and accepted. The worker was settled/released and acknowledged.

Real runtime exercise used existing committed worker checkpoints, with **zero model
calls**, for Samsung Electronics physical page 72 and LG Chem physical page 97. The
first Samsung attempt failed the earlier blanket AcroForm rejection. The new mode
rendered its widget-bearing page and the LG Chem page successfully. Original images
were visually inspected; note locations and surrounding table context are visible.
Private receipts/images: `.local/note-review-integration/source-condition-views-v1/`.
Samsung image SHA256: `139ffbb4f75d06d7382ae0e5c4a90a7299f08c2a2c64f3bd8dae096862499f2a`.
LG Chem image SHA256: `e318cde3397387ba47fbc5373e35122c6949d9e9ee36bd97ac9b19c376d0321f`.

Limitation exposed by this check: Samsung's native text places the subscript of NF₃
in a separate fragment. The selected original word set is retained, but the joined
string is not a corrected transcription. The original image is required for review;
neither this string nor the display receipt grants numeric comparability/ownership.
Annotations outside native text remain part of the unresolved coverage problem.

Focused tests: `uv run pytest -q tests/integration/test_source_condition_view.py`,
four passed with two existing dependency warnings. They use actual PDFium rendering
and the actual local upload/run/parser path, not a mocked source-approved graph.
Ruff lint/format passed (284 files); CI mypy passed (168 files); architecture checks
and four Python package builds passed. Full `uv run pytest -q`: **1916 passed**,
two existing dependency warnings, 138.77 seconds (`source-condition-view-full.log`).
Isolated extracted-wheel replay reopened all **18** real worker checkpoints with
identical graph hashes and zero calls (`source-condition-view-wheel-replay.json`).
Document/contract validation passed 763 checks; this is not application accuracy.
Follow-up Orca task `task_97dca7745885`, dispatch `ctx_dd63b36c261c`, completion
`msg_c0740fd24d10`, independently passed the four new tests and confirmed the annotation
omission closed in this view path. This worker was also released and acknowledged.
No public API/DB contract change or dependency
addition in this slice. Source-review HTTP publication/confirmation, numeric-check
receipts and shared approved-view consumers remain **not_run**; service completion
is not claimed.
