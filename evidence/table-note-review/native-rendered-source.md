# Native and rendered paragraph source verification — 2026-09-14

## Scope and contract

`proofops.adapters.local.source_verification.attest_native_sources` creates a
`native_paragraph_attestation_v1` receipt from the original PDF and exact input
candidate graph. `replay_native_sources` recomputes the complete receipt before
returning a new graph quality view. Store receipts at new paths; never rewrite
parser graphs, revisions, archived extraction packets or prior reports.

The opt-in `evaluation.report_demo --native-source-receipt PATH` consumes this
receipt and embeds it in the new demo artifact before hashing. Default ingestion,
API/DB contracts and deterministic grading are unchanged. Rollback is omission
of this optional flag; retain prior artifacts. Source verification does not
establish claim meaning, geographic/organizational equivalence, numeric binding,
table structure, note ownership or a grade. Table/footnote candidates are excluded.

A paragraph requires complete upright native words inside the selected bounding
box and exact agreement under the existing citation normalization, then exact
agreement with OCR of the rendered region. Hidden text and white overpainting
reproduced false approvals with native-only matching; both are now unresolved.
Unsupported rotation/crop geometry, interactive forms/optional content/annotation
appearances, clipping, OCR disagreement or unavailable OCR remain unresolved.

Receipt pins include source PDF, tenant/version/manifest, complete input graph,
native word text/coordinates, region image hash/pixel coordinates, parser and
renderer versions, verifier/normalization/Swift code hashes, Apple Vision revision,
languages and OS. Replaying on a different runtime may reject an old receipt;
create a new receipt instead of modifying it. Apple does not expose OCR weight
hashes here. This is not a claim of independently audited OCR accuracy.

Runtime is opt-in macOS Swift + Apple Vision with Korean and English support.
No dependency was added: PDFium is already locked through pdfplumber. The built
proofops wheel includes `proofops/adapters/local/native_ocr.swift`. Linux/cloud OCR
execution is not_run; missing Swift is explicitly tested to remain unresolved.
Serial region OCR has a 30-second subprocess timeout and a 16M-pixel page cap;
this local evaluation path is not a production worker throughput implementation.

## Actual report replay

Fresh immutable receipts are under
`.local/note-review-integration/{kia,kakao,samsung-life}/native-rendered-receipt-v1.json`.
Both creation and independent replay ran with no paid API calls.

| Selected report graph | Records | Paragraphs verified | Unresolved | Create + replay |
|---|---:|---:|---:|---:|
| Kia | 562 | 14 | 548 | 17.88 s |
| Kakao | 373 | 0 | 373 | 0.20 s |
| Samsung Life | 1041 | 0 | 1041 | 0.33 s |

These are selected archived pages, not whole-report accuracy denominators. Kia
had 19 exact native matches: rendered OCR admitted 14 and held 5. Other unresolved
Kia records: 171 clipped/rotated words, 8 text mismatches, 364 excluded structures.
Kakao and Samsung Life have nonempty AcroForm field arrays: respectively 128 and
417 paragraph candidates were conservatively held; structures were excluded.
No fallback promoted those paragraphs. This limited coverage is a remaining
service blocker, not an accuracy score.

Kia's archived CLI command plus the new receipt produced
`.local/note-review-integration/kia/review-source-verified-v1` successfully:
17 claims, 19 extraction receipts, 0 decisions, `complete=false`. Its parsed body
pages remain 24/106/128; table-note page 45 is separate. This is source attestation
integration, not complete claim-to-note-to-rule validation. The earlier
`kia/native-source-receipt.json` was a superseded native-only experiment and is
not accepted by this verifier.

## Verification

Focused integration checks: 7 passed, including source/receipt/tenant tampering,
original graph immutability, table exclusion, hidden/overpainted text, forms and
optional content, missing OCR, and invalid page rejection.
Ruff passed. Mypy passed 163 files with existing untyped-body notes.
`uv build --all-packages` passed; Swift asset verified in the wheel.
Package validation is documentation/contract validation, not an application test.
Full regression: `uv run pytest -q` — 1852 passed, 2 existing deprecation
warnings, 132.49 s; log `.local/note-review-integration/pytest-native-rendered-final.log`.
The positive OCR check was rerun after adding an explicit non-macOS/Swift skip;
all 7 checks executed and passed on this macOS host. `validate_package.py`: 758/758.
Orca Muse Spark 1.3 Free read-only review: task `task_9f8b9361e103`,
dispatch `ctx_35121732afb0`, accepted completion `msg_5cbe1113fc90`.
Reviewer ran 8 PDF-mutation probes and all 7 integration checks; reported no
false-approval or provenance bypass in the tested cases. Rendering-mode-3, white
text, overpainting, transparency, mirrored text and stamp appearances remained
unresolved. Double-draw text and empty forms can cause false negatives. Native
PDF failures outside the narrow OCR exception handler can abort this opt-in CLI;
this is a robustness limitation, not approval or absence. The review is an agent
review, not human certification. No paid API calls occurred in this iteration.
