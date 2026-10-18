# FXH fresh execution repair

`fxh_finals_fresh_v1` is explicitly selected by the SHA of
`analysis_profile.FXH_POLICY`. I26 composes it into the new v26 default; V23/V24/V25 pins and
historical source readers remain unchanged. Roll back by selecting the previous
analysis pin for new runs, retaining all existing receipts and registered readers.

E15's LG header failures were local `PROBE_REQUEST_TOO_LARGE` failures before
provider dispatch. The new pin admits at most 32,768 serialized request bytes,
within the existing 32,768 input-token reservation. This changes local admission,
not model wire options or the frozen C3 model binding. All broker, lease, retry,
authorization and money ceilings still apply.

SC1 now packs at most 2,000 text bytes / 8 spans per chunk and reserves up to
4,096 output tokens per attempt. A fused block without a canonical bounding box
leaves its page uninspected with `BLOCK_UNLOCATED`; it cannot prove absence.
A settled invalid answer leaves that chunk uninspected while later chunks can
run. Authorization, budget, lease and uncertain transport failures still stop.
The existing 300-call / USD 2 reservation ceiling is unchanged.

The composed source reader applies I21's private policy snapshots and scoped raw
OCR reuse to the I24 chain. Every original source guard and nested full-receipt
comparison still executes. Scope keys include tenant, run, source, geometry and
runtime. The new reader pins its own, execution-helper and raster-helper bytes;
the complete policy is rechecked at each read boundary.
The FXE original-region reader uses the same bounded cache and two-process pool;
its exact original render/OCR function produces each raw read. No source-proof
decision is cached in place of the guard code.

The hosted C3 call retains the run's OCR store context through source preparation.
Its original page numbers map back to the same prepared-page claim allowance;
the original p36 cannot be mistaken for prepared page 36. Evidence-only pages,
unselected pages, the ten-page fallback limit and broker accounting still hold.
The approved tenant, original bytes, rulepack, exact spans and three fresh bound
responses remain mandatory. Historical pre-DEC-127 pins still cannot publish confirmation from unknown tags.
DEC-127 pins may publish only the scoped E0 result described below.

## Offline fresh gate

```sh
uv run python scripts/fresh_e2e_gate.py \
  --manifest /path/to/fresh-manifest.json \
  --image proofops-public:exact-arm64-build \
  --output /path/to/new-output-directory
```

The manifest accepts `lg13` and/or `kakao` (one case per kind). The LG case has
the original LG PDF path and SHA, approved tenant,
E14's fixed 13 selected / 8 claim pages, reporting scope, and baseline. Required
baseline: at least 107 claims; parse/extract/tag/publish seconds
199.32/161.02/228.37/52.55; stage ratio at most 1.5 and total at most 984.6 seconds.
Include `analysis_policy_sha256` to test FXH; omit it for the image's own default.
See `validate_manifest` for exact identity and scope. No saved-response input is
accepted. Keep the manifest and generator identical between baseline/candidate.

I26's Kakao case requires `selection_mode="automatic"` and no supplied page lists.
The real scope-plan API proposes the pages; the harness submits those same lists
with `manual_selection=false` and preserves the proposal and accepted selection.
Page 51 must be a claim page. The fixed E14 timing reference is parse/extract/tag/
publish 450.42/549.58/516.49/184.29 seconds, each at most 1.5x, total at most
2567.7 seconds, and at least 133 claims. E14's executed 30/9-page selection differs
from the current automatic selection, so this is a fixed execution ceiling, not
an equal-scope speed or accuracy claim.

LG requires three current C3 calls. Kakao requires zero C3 calls and
`outside_approved_source`: the frozen C3 tenant/original binding authorizes only
LG. The gate never broadens that authorization to satisfy a call counter.
Both documents require SC1 completion and zero replica/input errors. W18 must
produce exact coordinates via `?w18=true` without changing existing result fields.
Dummy OpenAI, Upstage and OpenRouter files satisfy configuration validation;
no real key or external network is available.

The launcher resolves the image ID and requires Linux arm64. Separate real API
and worker containers run with no network, dummy keys, a fresh volume, server
resource caps and at most four model workers. The real analysis subprocess and
publication FD are observed; cold API restart must preserve result bytes. Only
model transport is replaced: the current PDF generates parse candidates and fake
OCR word/coordinate responses when its newly rendered pixels exactly match the
OCR request. Unmatched images use local Tesseract. This native-geometry simulator
is not independent visual evidence. Current LLM requests generate unknown tags.
No result, source-verification decision or rule evaluation is substituted.
Receipt inspection runs in a separate observer sharing the API's isolated
loopback namespace, so reading large diagnostic DBs does not consume the API's
512 MiB allowance. API and worker resource limits remain unchanged.

The gate requires nonempty verified claims, zero replica/input errors, completed
SC1 calls, three current C3 calls, settled costs and bounded stage/total times.
It records hold reasons against E14. Unknown simulation tags intentionally cannot
match E14's semantic hold rate. This is an execution/performance gate; it does not
measure model accuracy, live provider latency, or establish public confirmation.
Publication time uses a monotonic observation of the real handoff. Clock steps
greater than five seconds fail the gate; do not change lease guards to absorb a
suspended host. On macOS, run the command under `caffeinate -i` for stable timing.
The original E15 SC1 truncation and Kakao geometry failures also need the focused
regression tests: deterministic replies cannot reproduce every provider failure.


## TS1 / DEC-127 simulation confirmation gate

The gate resolves the **executed** `worker-runtime.json` policy hash against the
registered analysis policies. A policy without `cf6_confirmation` retains the
original zero-confirmation check. An unknown policy fails closed; missing policy
identity cannot bypass validation of CF6 results. A reported outcome policy must
agree with the worker runtime pin. This includes v29d and explicitly registered
DEC-127 predecessors, without changing historical policy bytes.

For the unknown-only simulator, each confirmed claim must be E0 with verified
claim source, the complete track element set in `absent_in_scope`, and
`DEC127_SYSTEM_NON_OBSERVATION` as the absence basis. Public decision and CF6
confirmation must agree, with the correct E0 Python rule, selected-scope basis,
analysis/confirmation/scope-rule hashes and nonempty receipt/model/prompt/rulepack
hashes. No present element or E1–E3 confirmation is accepted. Held claims need a
recognized CF6 reason and no confirmed decision; a source-unverified reason
cannot accompany a source-verified claim. The historical provisional projection
is retained and is not mistaken for the final CF6 publication state.

C3's zero-confirmation rule, original PDF/tenant/scope checks, W18, cost settlement,
SC1 completeness, replica/input errors and timing ceilings remain unchanged.
These are offline wiring and consistency checks, not semantic-accuracy evidence.
Run the focused positive/negative controls with:

```sh
uv run pytest -q tests/test_fresh_e2e_gate.py
```
