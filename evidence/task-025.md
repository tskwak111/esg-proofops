# TASK-025 · 규칙팩 검증·활성화 — Evidence (FR-025 / AT-025)

## Coordinator acceptance — 2026-09-09 KST

The pure validation/activation foundation is accepted for dependent implementation.
HTTP activation and durable persistence remain integration work; this is not an
acceptance claim for the endpoint or production deployment.

Coordinator regression tests reproduced five additional failures: null required
hash/list values, mutation through nested snapshot pairs, and CLI traversal reading
outside the configured directory before rejection. A further check reproduced
mutable active-pointer entries. Validation now fails closed, snapshots copy nested
pairs, and the CLI checks relative paths and resolved containment before reading.

Fresh checks: `uv run --no-sync pytest tests/acceptance/test_rulepacks.py
tests/contracts/test_package_contracts.py -q --tb=short` — **67 passed** (38 rulepack,
29 package contract), one upstream deprecation warning. The repository's nine real
configuration files are checked through the CLI with temporary synthetic identities;
the result remains `draft` and `activatable:false`, without fabricated approval.
Focused Ruff passes; Mypy passes for both rulepack modules. Earlier worker counts
below are historical; unrelated in-progress tests are not acceptance evidence.

- Contract: `validate_rulepack / activate_rulepack :: YAML+source metadata+gap registry → validated pack/status`
- Operation: `POST /v1/rule-packs/{rule_pack_id}/activate` (role=admin, idempotent)
- Acceptance: 활성화는 새 run 기본값만 바꾸며 실행 중인 규칙 스냅샷은 바꾸지 않는다.
- Files owned: `packages/proofops/application/rulepacks.py`, `scripts/verify_rulepack.py`,
  `tests/acceptance/test_rulepacks.py` (new), plus repair addition
  `packages/proofops/domain/rulepacks.py` (new module inside the already-listed
  `proofops.domain` package — no packaging change needed). No shared files touched;
  no commit/push.

## Failing-first

Wrote `tests/acceptance/test_rulepacks.py` (16 tests) before implementation.
First run failed at collection as required:

- `uv run pytest tests/acceptance/test_rulepacks.py -q` → `ModuleNotFoundError:
  No module named 'proofops.application.rulepacks'` (1 collection error).

## Implementation (minimal, pure)

`packages/proofops/application/rulepacks.py` — stdlib + domain errors only
(hashlib/json/dataclasses/datetime/uuid). No AWS SDK, network, file, env,
scripts, or legacy imports. Behavior:

- `compute_pack_sha256`: canonical hash over sorted (path, canonical-JSON) pairs.
- `validate_rulepack`: required fields, version/effective_date/mode/ontology/source-hash
  shape; every listed file present with version+effective_date; declared sha256 must
  equal computed content hash (tamper → reject); unresolved_gap_ids ⊆ gap registry;
  GAP-008 verified-clause claims without verified_by/verified_at rejected;
  GAP-001 non-null safe-harbor grade/reasonable-basis mapping rejected;
  GAP-009 automatic legal applicability rejected.
- `activate_rulepack`: only `status=validated` + approver (approved_by/at) packs;
  draft → "validate first", retired → reject, cross-tenant → uniform
  `LookupError("rule pack not found")` (no leak); moves only the (tenant, mode)
  default pointer for NEW runs; existing `RunSnapshot` tuples carried over untouched;
  previous active pack retired (preserved, never overwritten); re-activation idempotent.
- `scripts/verify_rulepack.py --pack <pack.json> [--config-dir config]
  [--gaps contracts/domain_gaps.json]`: file I/O boundary, JSON report, exit 0/1,
  no network/AWS/model calls.

## Verification (exact commands, run 2026-09-09 UTC, repo root)

- `uv run pytest tests/acceptance/test_rulepacks.py -q` → **16 passed**
- `uv run pytest tests/acceptance/test_rulepacks.py tests/unit tests/contracts -q`
  → **45 passed**, 1 unrelated warning (docs URL)
- `uv run ruff check packages/proofops/application/rulepacks.py
  scripts/verify_rulepack.py tests/acceptance/test_rulepacks.py` → **All checks passed**
- `uv run ruff format --check ...` (same 3 files) → **3 files already formatted**
- `uv run mypy packages/proofops/application/rulepacks.py`
  → **Success: no issues found in 1 source file**
- `uv run python scripts/verify_rulepack.py --pack /tmp/synth_pack_task025.json`
  (synthetic local-only descriptor over the real `config/*.yaml` + gap registry)
  → `{"ok": true, "errors": [], "pack_status": "draft", "activatable": false}`,
  exit 0 (structural validation passes; draft + no approver honestly not activatable)
- Tampered-sha256 variant → `sha256 mismatch ... refusing to validate a tampered pack`,
  exit 1
- `uv run python scripts/validate_package.py` → **Status: passed,
  692 checks, 0 failed** (docs/contract checker; not an app test)

## Prohibitions honored

No source-less present / unknown-to-absent / LLM grades logic added (grading stays
rules-engine-only per docs/28); no tenant data in cross-tenant errors; no revision
overwrites (immutable registry, retired-not-deleted); no invented clause numbers,
legal effect, model ARNs, or performance figures; synthetic fixtures are local-only
(`/tmp`, test helpers) and explicitly non-production. No real model/AWS calls.

## Left / blocked (not_run, human gates)

- Real `POST /v1/rule-packs/{id}/activate` API wiring + admin auth (needs TASK-037)
  and DynamoDB RulePack persistence — later tasks own those files.
- Clause/legal approval (GAP-008/009), approved safe-harbor mapping (GAP-001),
  industry/timeline approvals — domain-owner gates, remain blocked by design.

## Amendment — coordinator acceptance repair (2026-09-09 UTC)

Prior implementation failed important acceptance review. Fixed with focused failing
tests first (new names initially failed at collection with
`ImportError: cannot import name 'grant_demo_use'`), then minimal implementation.
No full bootstrap research repeated; docs/28, docs/31, and
evidence/contract_review_resolution.md finding 3 (content validation vs
administrative activation vs domain/basis approval) drove the split.

1. **Registry identity keyed by (tenant_id, rule_pack_id).** `with_pack` previously
   dropped any same ID across tenants. Now: identical replay returns the same
   registry object (idempotent); a changed record under an existing tenant+ID raises
   `ValueError` (immutable IDs cannot be overwritten). `RulePackRegistry` and
   `RulePackRecord` freeze nested inputs in `__post_init__` (tuple copies).
2. **Manifest-bound semantic hash.** `compute_pack_sha256(pack, files_content)` now
   delegates to pure-domain `pack_content_hash`, binding version, ontology,
   source hash, mode, effective date, sorted file set, and sorted gaps with every
   file payload under deterministic no-NaN canonical JSON (`allow_nan=False`).
   Validation additionally rejects: file set differing from manifest (extra paths
   named), duplicate entries, unsafe paths (absolute/dot-dot/backslash), malformed
   payloads (hash uncomputable, no crash), file version mismatch against the pack,
   and file source-identity mismatch. Verified against real `config/*.yaml`: all 9
   manifest files share version `proofops-domain-v2.0-impl1` and the manifest source
   hash, so coherence holds on the genuine tree.
3. **Immutable pure-domain snapshot.** New `packages/proofops/domain/rulepacks.py`
   (stdlib + `proofops.domain.errors` only; AST test asserts no
   `proofops.application` import) provides `RulePackSnapshot`, which retains the
   verified configuration content as canonical-JSON payloads — never a mutable
   external pointer — with fresh-copy `file_content()` accessors and a
   self-verifying `__post_init__` (path-set equality + sha recomputation) for
   TASK-014's rules engine.
4. **Local validated-draft demo without invented approval.** New `grant_demo_use`
   permits draft/validated packs for explicit-ladder demos with fixed `DEMO_LIMITS`
   (per-claim gates retained, unverified basis stays unverified, no legal-effect
   claim, local-only, never customer activation), records `approved_by=None`
   honestly, and never touches registry activation state. Draft activation via
   `activate_rulepack` remains rejected. No gap approval or legal verification
   is claimed anywhere.
5. **Hygiene.** Status transitions in `activate_rulepack` use `dataclasses.replace`
   instead of repeated record boilerplate. No public DTO/contract/config/lockfile
   edits; no real model/AWS calls; endpoint integration left to the auth worker.

## Amendment verification (exact commands, `uv run --no-sync`, repo root)

- `pytest tests/acceptance/test_rulepacks.py -q` → **32 passed** (16 original + 16 repair)
- `pytest tests/acceptance/test_rulepacks.py tests/unit tests/contracts -q`
  → **81 passed** (one earlier combined run showed 6 failures in TASK-043's
  in-progress `tests/unit/test_legacy_characterization.py` while that untracked file
  was being edited by its owner; immediate re-run green, unrelated to this task)
- `ruff check` (4 owned files) → **All checks passed**;
  `ruff format --check` → clean after one reformat
- `mypy packages/proofops/domain/rulepacks.py
  packages/proofops/application/rulepacks.py` → **no issues in 2 files**
- `python scripts/verify_rulepack.py --pack /tmp/synth_pack_task025.json`
  (synthetic local-only descriptor, regenerated for the new hash scheme, over real
  config + gap registry) → `ok:true, pack_status:draft, activatable:false`, exit 0
- `python scripts/validate_package.py` → **694/694 passed** (docs/contract checker)

## Still unresolved / not_run after repair

- `POST /v1/rule-packs/{rule_pack_id}/activate` endpoint integration (auth worker owns
  API main; follows TASK-037) — no live endpoint check performed.
- DynamoDB persistence, S3 artifact refs, real Bedrock/model bindings, AWS staging —
  not run, no credentials touched.
- GAP-001–GAP-010 domain approvals (clause numbers, safe-harbor mapping, legal
  effect, industry mapping) — still blocked by design; demo grant explicitly
  excludes them.
