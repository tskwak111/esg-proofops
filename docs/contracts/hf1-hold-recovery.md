# HF1 hold recovery — new finals-unattended-v2 runs

HF1 adds `upstage-ocr-page-v6`, `citation-whitespace-partial-v1` and the
`hf1-v1` projection under a new analysis-policy hash. Existing v1, initial v2
and pre-HF1 v2 policy hashes still select their original behavior; resume does
not replace their pins or rewrite receipts, tagging revisions or reports.

The v6 reader keeps v5 and the literal v3 reader bytes unchanged. A quote must
match a unique native glyph sequence in its original region; each glyph must
intersect that region, with horizontal and bottom containment unchanged.
Only the glyph-proven top portion extends the verification crop. The original
bbox, text and offsets remain in SourceRef. The receipt records `original_bbox`,
the verification `bbox`, glyphs, source hash and verification-region policy hash.
Literal quantity spacing, row/column continuity, foreign glyphs in the new
area, table ownership, annotations and original rendered pixels still gate
admission. Only its exact original owner is excluded from OCR competing regions,
inside a scoped context after the native/layout proof. Other peers remain.

New element packets pin the citation policy. Unique whitespace-run differences
and existing number/unit-protected Hangul display boundaries map back to raw
codepoint offsets. Missing/ambiguous or altered numeric/unit quotes fail. A
failed element retains `unknown`, no refs/value/credit, and an explicit warning;
other elements proceed through the unchanged source/binding/consensus guards.
Original provider responses are retained. New packet identity separates caches.

`provisional_grade.gap_ids` is additive. On `hf1-v1`, “규칙 미정” means actual
engine gap IDs, rather than a counterfactual envelope's possible unmapped rule.
`grade_range.rule_gap` retains its display-only meaning. Existing grade/range,
status, display and hold fields remain; replica/citation reason codes distinguish
missing guarded headers from superlative disagreement. Grades remain provisional.

No API route, database schema or migration changes. Rollback selects a prior
analysis policy and v5 for future runs, preserving v6 artifacts with this reader.
Source-upgraded evidence packets require a new tagging run/revision; the offline
saved-response comparison is not a confirmed result or a model-accuracy claim.
