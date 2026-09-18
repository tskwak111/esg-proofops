# Atomic table claim extraction — 2026-09-13

Correction from the later enlarged-image review: KB's original table itself shows
`개발 개발`; the source-fidelity-defect diagnosis below was incorrect. See
[document-input verification](../document-atomic/verification.md). Original receipts
remain unchanged.

Baseline 3560ffe. User approved external-LLM atomic extraction, source validation
and report comparison before downstream evidence linking. This adds an opt-in
evaluation path; it does not activate production discovery or change rule grades.

## Implemented path

`evaluation.table_atomic_claims.prepare` reuses table_role_pilot row/header/layout
packets, limiting each request to one row and explicit target cells. This keeps
KB's selected requests below the existing serialized 16 KiB transport limit.
No source truncation or budget-policy change was needed.

The model now returns several exact claim quotes per target rather than one role
for an entire mixed cell. `validate` rebuilds the packet from the graph and optional
matching original PDF, then reuses `locate_quotes` and the application span validator.
It rejects rewritten/ambiguous/overlapping quotes, wrong sources, omitted targets,
extra grading fields and packet/tenant tampering. Each child preserves exact source
offsets and its parent reference. All unreturned text remains unknown, including an
entire target when the model returns nothing. All children remain model proposals,
undetermined and ineligible for scoring. Exact quote matching is not a semantic check.

`run` archives immutable packets, prompts, responses, helper/graph/contract/model
identities and replica1. Transport/budget hard stops defer remaining rows without
another paid call. Invalid content retains unknown coverage. The existing
`claim_dimensions.prepare_dimensions` accepts the resulting claim artifact; no
second dimension extractor, SDK, dependency, domain/API/DB migration was added.

Runnable API: restore a source-verified graph and select canonical table-cell IDs;
call `run(graph, source_ids, shared_budget_client, new_output_path,
tenant_id=graph.tenant_id, source_pdf=original_pdf_bytes)`. Omitting source_pdf is
the text-only variant. `prepare` is offline and returns the exact planned packets.

## Real model/source comparison

18 settled requests: two Pro3 prompt versions and Pro4 on the second version,
each across Naver, KB and Kia (six row requests per experiment). Prompt v1 used
English instructions; v2 uses Korean instructions and an unrelated illustrative
goal example. Inputs and raw outputs are archived separately under
`.local/table-atomic-{v1,v2,v2-pro4}`. Hashes and costs are in live-comparison.json.
These companies have already been used for development: this is not a holdout.

| Diagnostic | Pro3 v1 | Pro3 v2 | Pro4 v2 |
| --- | --- | --- | --- |
| Naver RE70 goal retains its 2025–2026 qualifier | No, split off | Yes | Yes |
| Naver distinct activities separated | Partly; extra qualifier fragment | No, whole cells | Yes, six candidates |
| Naver progress correctly left unassigned | No | No | No: attached to PPA |
| KB two opportunity activities separated | Yes | No | Yes |
| KB planned installation-budget statement retained | Yes | No | No |
| Kia isolated label/unit/value outputs (expected zero narrative claims) | 8 | 3 | 1 |

All 18 responses passed schema/source-span checks. That is NOT 100% extraction
accuracy: the table above records concrete semantic failures. Pro4 improves some
atomic separation here, but does not justify switching every pipeline stage to it.
Kia's isolated numeric cells belong to the existing structured observation path;
not extracting a narrative claim from them must never imply absent evidence.

Directly viewed Naver original physical84, KB30 and Kia45. Naver's status is beside
the bullets, so keeping `(진행 중)` attached to the first PPA is unresolved even
though it exactly matches the flattened parser text. KB's parser duplicate 개발
remains a source-fidelity defect; an exact parser quote does not repair it. Kia's
remaining Pro4 output is just the metric label. No reviewed source was approved.

These were TEXT API calls with optional native word geometry, not image-input
LLM calls. Images were inspected by the coordinator. The existing UpstageProbe
accepts text; paid multimodal API comparison is not_run. The next source-layout
comparison must use a verified image-capable transport and the same budget ledger.

Cost USD0.0109619400. Shared committed/reserved USD7.2868950600 / USD10,
1,265 ledger entries. Six pre-existing unsettled reservations remain untouched.
No AWS, production deployment, assurance conclusion or automatic grade ran.

## Verification and next bottleneck

- Nine initial source/packet/coverage checks failed before the module existed;
  they pass after implementation. Transport-stop regression also failed first.
- Full `uv run pytest -q`: 1,772 passed, two existing dependency warnings,137.50s.
- After final prompt/summary metadata changes, focused atomic/role/layout suite:
  31 passed. Ruff passed and mypy checked160 files (existing notes).
- Four Python packages built. Documentation/contracts validator751 passed;
  this is separate from application and model verification.

The remaining blocker is semantic ownership and completeness, not JSON decoding.
Status-versus-activity relationships, omitted plans and metric-only false positives
need source-aware review before these candidates can feed automatic decisions.
General grammar/atomicity is deliberately not claimed to be validated by exact
substring matching. No report-specific exclusion rules were added to conceal it.
