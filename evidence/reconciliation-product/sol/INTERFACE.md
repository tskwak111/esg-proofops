# Reconciliation candidate preparation interface

## Python

```python
build_candidate_catalog(
    manifest, ArtifactStore(original_root),
    corp_code="00126380", fy=2024, rcept_no="20250311001085",
    consolidation="consolidated", max_candidates=500,
) -> PreparedCandidates

add_operator_sr_sources(
    prepared, sr_manifest, sr_manifest_parent,
) -> PreparedCandidates

prepare_review_draft(prepared, operator_selections) -> dict
```

`PreparedCandidates.catalog` is `reconciliation-candidates-1` and remains
`candidate_only`. `PreparedCandidates.artifacts` contains the exact bytes which
must be published under `artifacts/`; `artifact_index` is directly serializable
as `artifacts.json` for `FileSourceReader`.

## CLI

```powershell
$env:PYTHONPATH = 'packages;apps/api/src;apps/worker/src;apps/agent/src'
.venv/Scripts/python.exe -m evaluation.reconciliation_prepare `
  --manifest .local/dart-live-samsung-2024/collection.json `
  --store .local/dart-live-samsung-2024/originals `
  --corp-code 00126380 --fy 2024 --rcept-no 20250311001085 `
  --consolidation consolidated --max-candidates 500 `
  --output .local/reconciliation-candidates
```

Always emitted:

- `candidates.json`: bounded candidate catalog, raw quotes, optional normalization
  suggestions, and original-to-derived lineage.
- `artifacts/` and `artifacts.json`: real hash-addressed bytes and reader index.

With `--sr-sources sr-sources.json`, SR candidates are added only after byte,
SHA-256, format-aware locator, and quote validation. With `--selections
selections.json`, `review-draft.json` is emitted. A complete draft additionally
emits the established `packet.json`, `policy.json`, `documents.json`,
`coverage.json`, and `policies.json`. The last two are always empty trusted
registries; imported choices cannot create coverage receipts or policy approval.

## SR source manifest

`reconciliation-sr-sources-1` has exactly `artifacts`, `documents`, and `sources`.
Artifact entries use the `FileSourceReader` shape (`path`, `format`, `sha256`),
with paths relative to the manifest directory. Each source has the ordinary five
source-reference fields plus explicit lineage:

```json
{
  "schema_version": "reconciliation-sr-sources-1",
  "artifacts": {
    "sr-v1": {"path": "report.pdf", "format": "pdf", "sha256": "<64 hex>"}
  },
  "documents": {
    "sr-v1": {
      "tenant_id": "tenant-1",
      "company_id": "company-1",
      "package_id": "package-1",
      "document_version_id": "sr-v1",
      "document_role": "sustainability",
      "artifact_sha256": "<64 hex>",
      "corp_code": "00126380",
      "fiscal_year": 2024,
      "rcept_no": null,
      "consolidation": "consolidated",
      "published_at": "2025-06-27",
      "available_on": "2025-06-27",
      "as_of_date": "2025-06-30",
      "period_start": "2024-01-01",
      "period_end": "2024-12-31",
      "synthetic": false
    }
  },
  "sources": [{
    "source_id": "sr-page-86",
    "document_id": "sr-v1",
    "artifact_sha256": "<64 hex>",
    "locator": "page:86",
    "quote": "<literal substring extracted from page 86>",
    "lineage": {
      "representation": "original",
      "original_artifact_sha256": "<same 64 hex>",
      "transformation": "none",
      "transformation_locator": "PDF page:86"
    }
  }]
}
```

For a derived UTF-8 SR projection, `representation` is `derived`; the exact
parent `original_path` (relative to the manifest), its exact original hash, and
a non-empty transformation and transformation locator are mandatory and
verified. Derived `chars:` locators are never described as original byte offsets.

## Operator selection shape

`reconciliation-operator-selections-1` requires explicit `identity`, `item`,
`claim`, `comparability`, `sustainability`, `financial`, `explanation`, `search`,
`c3_context`, `c4_context`, and a complete unapproved schema-1.1 `policy` draft.

- `claim`: `candidate_id`, `track`, `trigger_elements`, `fiscal_year`.
- `sustainability` / `financial`: `candidate_id`, `raw`, `normalized`, `kind`,
  `unit`. Sustainability must select an SR candidate; financial must select a
  DART candidate.
- `explanation`: `candidate_id` or null, and `search_complete: false`.
- C3 replaces source IDs with explicit `commitment_candidate_id` and
  `funding_plan_candidate_id`; account IDs, periods, currency, and policy
  threshold remain operator choices.
- C4 uses explicit `definition_candidate_ids` and `calculation_candidate_ids`.

Missing fields yield a `candidate_only` review draft with `missing_choices` and
no input packet. `search.state=complete`, imported approvals, mismatched identity,
or arbitrary source text are rejected rather than trusted.
