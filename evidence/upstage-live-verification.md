# Upstage live connection and claim probe — 2026-09-09 KST

User approved a cumulative **USD 10** test budget and provided an Upstage API key
in `.env.upstage.local`. The key was read locally, never printed or committed.
The file is Git-ignored. Model access is now verified by actual HTTPS requests,
not synthetic responses. No Bedrock/AWS call occurred.

## What executed

Requested `solar-pro3` at `https://api.upstage.ai/v1/chat/completions`; the actual
provider version returned is **solar-pro3-260323**. The initial two probes returned
HTTP 200, but strict exact-model validation rejected the version suffix. An
observed-version regression failed before the fix; only that confirmed version
and the documented alias are now allowed. A subsequent JSON smoke probe passed.

One real paragraph from LG Chem physical p24 was loaded through the existing
verified immutable parser-artifact loader. Its SHA256, document version, parser
manifest, source ID, prompt, response and model hashes are recorded locally.
The first extraction response copied five original spans but assigned incorrect
character offsets; the existing span validator rejected it. That failed artifact
is preserved unchanged. The revised prompt asks for exact quotes only; code
locates unique original matches and passes them through the same strict validator.
The next live response produced **four source-matched claim candidates**.
Ambiguous, absent, overlapping or extra-grade output remains rejected.

This verifies literal quote/position correctness for one paragraph only. It does
not validate atomicity, semantic claim classification, recall, source visual
quality, appendix attribution, or a final grade. Source quality remains unverified.
No fixed extraction fixture was substituted for the live outputs.

## Budget and price

Official [Upstage pricing](https://www.upstage.ai/pricing/api), checked 2026-09-09:
Solar Pro 3 input USD 0.15 / million tokens and output USD 0.60 / million tokens;
listed prices exclude 10% VAT. The implementation uses the existing `PricingSnapshot`,
`TokenUsage` and `usage_cost`, charges cached input at the higher ordinary rate,
and includes a 10% allowance. Values below are conservative calculated amounts,
not a reconciled invoice or account balance.

- Five network calls were made.
- Three settled receipts total **USD 0.0005586900** including the allowance.
- The first two rejected receipts remain unsettled, reserving **USD 1 each**.
- Ledger commitment: **USD 2.0005586900**; this is not USD 2 of known spending.
- The corresponding remaining uncommitted allowance is USD 7.9994413100.

Before each call, an atomic SQLite transaction reserves USD 1 against the shared
USD 10 ceiling. Only complete, valid usage can reduce that reservation. Failure,
timeout or unknown usage retains it. Duplicate request IDs cannot dispatch again;
concurrent reservations cannot exceed the ceiling. There are no automatic retries.
The probe limits encoded request bodies to 16 KiB and output to 4096 tokens; the
USD 1 reservation deliberately exceeds these small calls at the pinned rates.
Prices expire on 2026-09-16 and must be rechecked before additional live execution.

This guard covers this project's **local probe path and shared ledger**, not
other applications using the same API key or provider-side billing behavior.
Keep `.local/upstage/budget.sqlite3` across runs; deleting/replacing it resets local
history and is not authorized as a way to obtain another USD 10 allowance.
The price policy is immutable in that database; differing policy content fails.

## Reproduce and artifacts

```sh
uv run --no-sync python evaluation/upstage_live_probe.py \
  --pdf '기업보고서/배터리 에너지/LGChem_Sustainability_Report_2025_KOR.pdf' \
  --manifest .local/e-scope/case/artifacts/bc76169c-b170-4166-baa5-b678df2191b9/b2bb195a-a7d0-4b83-ad4a-724b85803017/dbb4010d-78a7-4b58-9771-34eeb8847612/manifest.json
```

This command makes a new billed request under the same budget. It reads the key
from `.env.upstage.local` by default; it does not send the key as document text.
No document content or credential is printed. The transport uses a fixed HTTPS
host, does not follow redirects, and does not enable tools or document uploads.

Local artifacts: `.local/upstage/smoke.json`, `diagnostic.json`,
`533e4924-b68c-40bb-a5c5-3fbc526fec1f/result.json` (failed offsets),
`5aae69c8-7e4c-4645-965a-ddaebc1b675a/result.json` (passed quote locations), and
`budget.sqlite3`. Raw successful extraction output is saved before validating it.
The original report and previous parser manifests were not modified.

## Checks and scope

Focused tests: **15 passed** covering durable/concurrent USD limits, duplicate
requests, failed usage reservations, response version validation, oversized-input
rejection, exception redaction, and strict quote resolution. Missing module and
observed-version tests were recorded failing before implementation/fix.
Mypy: **139 source files** passed. Ruff and four Python package builds passed.
Broad regression: **1405 passed**, 2 existing deprecation warnings, 99.05s.
Formatting: **217 files** passed. Document/contract checks: **705/705 passed**
(not application tests). Overlapping test counts are not added.

Commands:

```sh
uv run --no-sync pytest tests/unit/test_upstage_quotes.py tests/integration/test_upstage_probe.py -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py
uv build --all-packages --out-dir .local/upstage/build
uv run --no-sync pytest tests/unit tests/contracts tests/acceptance tests/integration tests/security tests/e2e/test_staging_gate.py -q
uv run --no-sync python scripts/validate_package.py
```

No new dependency or core API/DB contract change was introduced. The new SQLite
sidecar only stores the local probe's policy/reservations/receipts. Rollback stops
new probe calls and retains that ledger and artifacts. This is an opt-in local
transport; API/worker production composition, regional processing verification,
three-replica tagging, full E/DATA/APPENDIX evaluation and source-quality approval
remain incomplete. No legal applicability or production approval was created.
