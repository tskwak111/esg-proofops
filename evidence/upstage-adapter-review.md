# Upstage Adapter Review — trust boundary, receipt/budget, identity/provenance

Scope: `apps/agent/src/proofops_agent/upstage_extraction.py`,
`packages/proofops/adapters/local/upstage_parse.py` (+ parent
`packages/proofops/adapters/local/upstage.py` where settlement is shared),
tests `test_upstage_extraction.py` / `test_upstage_parse.py` /
`test_upstage_probe.py` / `test_upstage_quotes.py`.
No code edited. No model calls, credentials, commits, or env reads.
Unicode model-input handling is coordinator-owned and excluded here.

## HIGH

### H1 — Budget/price errors relabeled retryable TimeoutError
- `upstage_extraction.py:139-141,232-244` — `_fail(..., transport=True)` raises
  `TimeoutError` for **every** known transport code, including
  `BUDGET_EXHAUSTED`, `PRICE_RECHECK_REQUIRED`, `PROBE_REQUEST_TOO_LARGE`.
- Caller `packages/proofops/application/claims.py:241-256` treats
  `TimeoutError` as per-block transient `unknown` (`extraction_failed`) and
  continues to the next block. A budget/price-stop therefore becomes N
  per-block retries, each creating a new receipt dir (disk growth) instead of
  a hard stop.
- Repro (fake transport, no network; run from repo root with `.venv/bin/python`):
  ```python
  from pathlib import Path
  from dataclasses import asdict
  from proofops_agent.upstage_extraction import UpstageClaimExtractor
  import tempfile
  tmp = tempfile.mkdtemp()
  class P:
      def complete(self, s, u, *, request_id, max_tokens=1024, json_mode=False):
          raise ValueError("BUDGET_EXHAUSTED")
  ex = UpstageClaimExtractor(P(), Path(tmp) / "r")
  pkt = {"tenant_id": "b490d4e4-0192-426c-9dff-c6c7b8c498d3",
         "document_version_id": "35d03dcb-c9d0-40d6-a3d1-8f9dc7322ee1",
         "parse_manifest_id": "62919374-bd2d-4273-85b4-7a1f793b8c14",
         "source_sha256": "c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde",
         "extraction_profile": asdict(ex.profile),
         "untrusted_document_data": {"source_id": "11111111-2222-4333-8444-555555555555",
                                      "text": "hello world"}}
  try: ex.extract(pkt)
  except BaseException as e: print(type(e).__name__, e)  # TimeoutError BUDGET_EXHAUSTED
  ```

### H2 — Ledger settlement UPDATE result unchecked → silent free success
- `upstage_parse.py:251-256`; same pattern in parent `upstage.py:195-199`.
  `UPDATE probe_calls ... WHERE request_id=?` return value is ignored. A
  missing/deleted row yields a success return with no ledger charge.
- Repro:
  ```python
  import sqlite3
  with sqlite3.connect(client.ledger) as db:
      cur = db.execute("UPDATE probe_calls SET committed=?, receipt=? WHERE request_id=?",
                       ("0.01", "{}", "ghost-id"))
      print(cur.rowcount)  # 0 — caller still returns success
  ```

### H3 — Untrusted provider metadata copied into result.json unverified
- `upstage_extraction.py:144-147,166-178` — `provider_model`,
  `response_sha256`, `cost_with_vat_reserve_usd` are filtered by key name only,
  never recomputed or cross-checked (no `canonical_hash(content)` check, no
  model-allowlist check). `result.json` then persists them as provenance.
- Repro: fake probe returns `provider_model="evil-model"`,
  `response_sha256="deadbeef"*8` with `content='{"claims":["hello"]}'` →
  `extract()` succeeds and `result.json` contains both verbatim (verified
  locally 2026-09-12).

### H4 — Usage without mode breakdown accepted; bills on requester's word
- `upstage_parse.py:204-220` — when provider `usage` has neither `standard`
  nor `enhanced` lists, coverage/billing-mode checks are skipped and cost is
  settled from the **requested** mode.
- Repro: stub `_post_parse` → `{"model": PARSE_MODEL_PINNED,
  "usage": {"pages": 1}, ...}`; `parse(pdf, request_id="no-breakdown",
  mode="standard")` succeeds with `cost 0.011` (verified locally).

## MEDIUM

### M1 — Shape-invalid transport output discards the raw bytes
- `upstage_extraction.py:142-143` fails **before**
  `raw_response.json` is written when `result` is not
  `dict`+`str content`. Receipt holds `packet/request/failure` only,
  contradicting the module docstring ("every raw response retained") and
  hindering forensics. JSON-parse failures (line 147+) do retain raw —
  inconsistent. Repro: probe returns `{"no-content": 1}` → receipt dir
  contains `failure.json, packet.json, request.json`, no `raw_response.json`
  (verified locally).

### M2 — Model-content ValueError escapes per-block handling, aborts discovery
- `upstage_extraction.py:238-244` raises `ValueError(MODEL_SPAN_OR_SCHEMA_INVALID)`
  for bad model content, but `claims.py:241-243` catches only
  `(TimeoutError, ConnectionError)` around `extractor.extract`. One bad model
  span aborts the whole `discover_atomic_claims` batch instead of becoming a
  per-block `unknown` exclusion. Existing test
  `test_raw_invalid_responses_retained_with_sanitized_error` covers the
  extractor alone, not the discovery loop.

### M3 — Parse request_id is caller-chosen, binds no tenant/document
- `upstage_parse.py:124-133` accepts any 1–128 char `request_id` with no
  tenant/document/pdf binding (contrast extractor's
  `uuid5(parse_manifest_id, packet_sha)`, `upstage_extraction.py:100`).
  Cross-tenant reuse causes spurious `duplicate request` denial or ledger
  misattribution. `request_hash`/`pdf_sha256` are computed but not used as the
  ledger key.

### M4 — Parse archive files world-readable
- `upstage_parse.py:162-166` writes `parse-responses/*.json` with default
  umask (`0o644` observed) and no `chmod`, vs extractor receipts `0o400`
  (`upstage_extraction.py:226-230`) and ledger `0o600` (`upstage.py:62`).
  Provider output (possibly sensitive source text) is over-exposed.

## LOW / NOTES

- L1 — Receipt "immutability" is file-mode only: receipt files are `0o400`
  but the parent dir is `0o700`, so entries can still be unlinked/added via
  the directory. `upstage_extraction.py:87,102,226-230`.
- L2 — `_validate_pdf` (`upstage_parse.py:60-68`) maps **any** exception,
  including a missing `pypdf` import, to `INVALID_PROBE_REQUEST`, masking a
  dependency/environment fault as a bad request.
- L3 — `COST_PER_PAGE` cost-cap check (`upstage_parse.py:222-224`,
  `cost > 1.00`) is currently unreachable: local pages are bounded 1–10 and
  provider pages must equal local pages, so max cost is 0.33. Defense in
  depth only; no change requested.
- Tests do not cover H1/H2/H3-negative paths above (budget-code exception
  type, ghost-row settlement, forged `response_sha256` rejection, breakdown-less
  usage rejection). Existing budget tests use `OSError` transport failures and
  stay on the covered path.

## Out of scope (not duplicated)
Unicode normalization of model quotes — coordinator is fixing; no findings
or repros on that axis in this report.

## Coordinator disposition (2026-09-12)

This section supersedes severity/interpretation above where noted.
- H1 fixed: budget/price/rate-limit/receipt-uncertainty errors propagate as hard
  stops. Model-content rejection has a specific `ExtractionOutputError` subtype;
  discovery catches only that subtype as block-level unknown (M2 fixed).
- H2 fixed in shared `_settle`: exactly one still-reserved row must transition;
  both text and parser paths use it. Deleting the ledger is outside authorized
  operation and is not repaired into a new budget. Tests simulate lost rows.
- H4 fixed: billing-mode page coverage is required to settle; missing mode keeps
  reservation. This intentionally rejects incomplete provider receipts.
- M1 fixed for allowlisted transport fields: archive before shape/quote checks.
  Arbitrary injected Python objects are not a supported wire response.
- M4 hardened: archive files chmod 0400. Original wording overstated exposure:
  the enclosing directory was already 0700, preventing other-user traversal.
- H3 is not a demonstrated provider-boundary bypass: the injected probe is
  caller-owned trusted code, and real UpstageProbe validates provider model and
  hashes the full native response. Recomputing that hash from content alone is
  incorrect. Added an independent content hash; it is not proof of an approved
  provider/source. Production transport authorization remains a composition gate.
- M3: this is an explicitly single-user, shared-budget evaluation transport with
  caller UUIDs, request PDF hashes and external selection manifests. No multi-
  tenant service claim is made. Real tenant run binding is still required before
  application integration; inventing a tenant from PDF bytes would not fix it.
- L1/L2 remain local-adapter limitations: filesystem ownership is not a tamper-
  proof immutable store; pypdf execution is not resource-isolated here. This
  adapter must not replace the application's quarantine boundary.

Regression checks failed before H1/H2/H4 fixes and passed after. No source-quality,
pricing ceiling, PDF action allowlist, or rule-engine judgment was relaxed.
