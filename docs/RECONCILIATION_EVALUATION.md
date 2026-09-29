# C1–C4 reconciliation objective evaluation

`evaluation.reconciliation_benchmark` is an offline, reusable verification harness for
prepared reconciliation candidates. It answers only whether declared original bytes and
candidate source facts can be reproduced. It does not decide whether evidence is relevant,
complete, or sufficient for C1–C4.

## Command and exit codes

From the repository root:

```powershell
$env:PYTHONPATH = 'packages;apps/api/src;apps/worker/src;apps/agent/src'
uv run --no-sync python -m evaluation.reconciliation_benchmark `
  --manifest .local/reconciliation-completion/evaluation-manifest.json `
  --output evidence/reconciliation-completion/evaluation/run-001.json
```

The output path must not exist. The command creates it with exclusive-create semantics and
never replaces a prior report. Exit code `0` means all non-empty cases passed, `1` means the
manifest was valid but at least one objective check failed (an empty dataset also returns
`1`), `2` means input was rejected, and `3` means an unexpected I/O/internal failure occurred.
The command has no network or model path and reads no API-key environment variable.

## Manifest contract

All paths are relative to the directory containing the manifest. Absolute paths, drive
qualified paths, traversal, missing paths, and resolved paths outside that directory are
rejected. A minimal case is:

```json
{
  "schema_version": "reconciliation-evaluation-manifest-1",
  "dataset_id": "declared-b-corpus-2026-09-21",
  "cases": [
    {
      "case_id": "ottogi-c1-source-1",
      "company_id": "00141529",
      "split": "holdout",
      "item": "C1",
      "candidate_catalog": "00141529/prepared/candidates.json",
      "artifact_root": "00141529/prepared/artifacts",
      "originals": [
        {
          "path": "00141529/originals/ab/cd/<64-lowercase-hex>.zip",
          "sha256": "<64-lowercase-hex>"
        }
      ],
      "expectations": [
        {
          "candidate_type": "document_element",
          "artifact_sha256": "<prepared-source-artifact-sha256>",
          "locator": "chars:0:42",
          "quote_sha256": "<sha256-of-source-quote-utf8>",
          "original_artifact_sha256": "<sha256-of-pinned-original-bytes>"
        }
      ]
    }
  ]
}
```

Each non-empty case requires at least one pinned original and one expectation. Every object
uses an exact field set; missing and extra fields are rejected. Hashes are lowercase SHA-256.
`quote_sha256` is calculated over `candidate.source.quote.encode("utf-8")` exactly: no newline,
Unicode normalization, whitespace rewrite, or locator text is added.

`company_id` is an eight-digit DART corporation code, not a free-form dataset label. Each
case must match `candidate_catalog.identity.corp_code`; pointing the same catalog at another
company fails with `catalog_company_identity_mismatch` while still reporting independently
measurable source metrics. Catalog fiscal year and receipt identity must also be well-formed.
For every pinned `.json` original, the harness strictly parses the DART statement response and
checks every row's `corp_code`, `bsns_year`, and `rcept_no` against that catalog identity.
Duplicate keys, non-finite JSON values, malformed/empty responses, and row mismatches fail
closed.

Allowed candidate types are the types emitted by the current preparation adapter:
`statement_row`, `document_element`, `xbrl_fact`, and `sustainability_source`. The expectation
does not assert a human interpretation. It pins an objective tuple of candidate type, prepared
artifact hash, locator, quote hash, and original lineage hash. Exactly one catalog candidate
must match the tuple. That candidate is then independently read through
`FileSourceReader`, which rechecks the prepared bytes, manifest hash, locator, and exact quote.
Its lineage hash must also name original bytes that this case successfully rehashed.

The candidate catalog must be `reconciliation-candidates-1` and include its emitted
`limits.truncated` flag. A truncated catalog fails the case with
`candidate_catalog_truncated_incomplete_search`. A non-truncated bounded catalog is reported
as `search_completeness: not_measured`; it is not treated as proof that evidence search was
complete.

## Company split guard

Only `development` and `holdout` are accepted. A `company_id` may occur in many cases, but all
of its cases must have the same split. Any company appearing in both splits rejects the whole
manifest before scoring or output creation. Independently, an original SHA-256 digest may not
occur in both splits, even if the cases use different company labels. This prevents a copied
or relabelled original from bypassing the company guard.

This guard proves disjointness only within the companies declared in that manifest. It does
not authenticate a company name/code, discover undeclared prior exposure, establish global
gold-set provenance, or prove disjointness from repositories and datasets not supplied to the
harness. Those limits must remain in any downstream report.

## Report interpretation

The report contains per-case pass/fail and failure codes, expectation indices without source
text, aggregate numerators and denominators, a canonical manifest-content hash, and the
evaluator source hash. It intentionally does not echo manifest paths, quotes, artifact bytes,
environment values, URLs, or credentials.

The objective metrics are:

- `case_pass_rate`: cases for which every required objective check passed.
- `original_artifact_hash_match_rate`: pinned originals whose local bytes matched SHA-256.
- `original_statement_identity_match_rate`: verified JSON statement originals whose rows all
  matched the catalog corporation code, fiscal year, and receipt number.
- `catalog_company_identity_match_rate`: case catalogs whose DART corporation code matched
  the declared company.
- `candidate_expectation_exact_match_rate`: expected tuples matching exactly one candidate.
- `candidate_source_verification_rate`: matched candidate sources whose prepared bytes,
  locator, and quote were verified by `FileSourceReader`.

Every metric includes `numerator` and `denominator`. A zero denominator produces
`status: not_run` and `value: null`, never `1.0` or `100%`. An empty manifest is valid for
pipeline diagnostics but has `overall_status: fail`.

The following remain explicitly unmeasured: candidate relevance, discovery completeness and
recall, C1–C4 reconciliation status/grade/label, accounting interpretation, policy approval,
search receipts, human review quality, and independent authentication of company/split
provenance. The harness uses no human gold labels and cannot support a claim of semantic or
grade accuracy.

## Authoring expectations from real prepared data

Create expectations only after retaining the original bytes and running
`evaluation.reconciliation_prepare`. Copy objective values from the resulting immutable
candidate snapshot; compute the quote hash locally from the exact JSON string. Do not select
or relabel candidates to manufacture a desired pass rate. Record why each expectation was
chosen outside this machine-scored report, and have a human decide any semantic relevance or
policy question separately.

For a PowerShell quote-hash check without sending text anywhere:

```powershell
$bytes = [Text.Encoding]::UTF8.GetBytes($candidate.source.quote)
$quoteSha256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLower()
```

Use a new output filename for each run. Keep the manifest, prepared catalog/artifacts, pinned
originals, and report together if the result must be reproduced.
