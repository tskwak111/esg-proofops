# TASK-024 — 광고 검토 별도 모드

Status: implemented and locally verified at the approved pure-function boundary; real advertising processing remains gated.

## Delivered behavior

- Only `packages/proofops/application/mode_gate.py`, `tests/acceptance/test_advertising.py` and this evidence file were created. No shared engine, API, DTO, configuration, dependency/lockfile or DB changes; no commit/push.
- Read/reused AGENTS, Master, original v2 domain (especially §3.5/§8), priority docs 26/27/28/31/19, TASK-024/FR-024/AT-024, actual advertising/ISO templates, TASK-025 snapshots/approval/demo behavior and TASK-014 evaluator. AT-024 explicitly permits calling the task's pure function instead of the HTTP endpoint.
- Public function: `select_mode_rulepack(mode, rulepack, *, tenant_id, local_synthetic=False) -> RulePackSnapshot`. Inputs must be a **server-resolved, previously validated immutable snapshot**, not caller-supplied approval metadata or raw DTO dictionaries. Existing `RulePackSnapshot` retains/self-checks content hashes; selection returns that exact snapshot without filtering files, rewriting hashes, activating a pack or modifying existing runs/revisions.
- Supported modes remain `disclosure` and `advertising`; bool/unknown/malformed mode selectors fail closed. Missing and cross-tenant snapshots both raise `LookupError("rule pack not found")` without revealing the other pack's details. Mode mismatch has no fallback. The synthetic flag must be an actual Boolean.
- Normal new-run selection requires an active snapshot with nonblank recorded approver and approval time. Only disclosure allows the existing explicit local synthetic draft/validated demo distinction; the flag never enables unapproved advertising or retired packs. No actual human approval was created.
- Disclosure grading snapshots reject `advertising/` files, `standards/iso_14021.yaml`, and nested explicit ISO 14021/advertising-mode/separate-advertising-gate metadata. Renaming a marked policy file or placing its metadata inside a ladder branch cannot bypass the gate. Advertising reference material remains available in source/config for a separate expression-recommendation path; this function refuses mixed grading snapshots instead of silently stripping and rehashing them.
- Advertising snapshots use the existing dedicated `advertising/` namespace or ISO 14021 standard file; general disclosure ladder files cannot be reused there. Empty packs, disabled files, empty clauses, unverified or blank verification records, and explicit pending license review fail `ADVERTISING_RULEPACK_NOT_READY`. The repository's actual advertising/ISO files remain disabled/empty/unverified and cannot become usable just by setting manifest approval fields.
- This is rulepack selection, not an advertising grader, legal applicability decision, rights grant or content-language classifier. The trusted rulepack validator/approval workflow must supply valid schemas and approved policy semantics; arbitrary unmarked prose is not automatically classified as law. Existing disclosure evaluation still independently rejects advertising contexts/packs. No LLM labels, evidence-state conversions or source facts are introduced.

## Coordinator boundary and integration handoff

Orca guidance `msg_416faa49ad54` confirmed ownership of only mode_gate/test/evidence and instructed: “Do not wire POST/v1/runs yet: authcriticalrepair ownsAPI, runservicecomeslater.” No shared-file permission was needed or requested.

The future run service should resolve the authenticated tenant's validated/pinned snapshot, call this selector before persisting a new run or scheduling work, retain the returned pack ID/hash, and route advertising to its separately approved evaluator. Do not pass request-body approval metadata or add advertising references to the disclosure snapshot. Existing public RunCreate's two mode values are unchanged; HTTP gate-error mapping belongs to that integration owner. The local synthetic flag must come from the established execution profile, not an untrusted production request override.

## Test-first and review evidence

| Exact command | Result |
|---|---|
| `uv run pytest tests/acceptance/test_advertising.py -q --tb=short` before implementation | exit 1; 36 failed in 0.76s because `proofops.application.mode_gate` did not exist. |
| `uv run pytest tests/acceptance/test_advertising.py -q` after initial implementation | exit 0; 36 passed in 0.44s. |
| `uv run --no-sync pytest tests/acceptance/test_advertising.py -q --tb=short` after adding review regressions | exit 1; 5 failed, 36 passed in 0.55s: empty ad pack, two nested advertising markers, and blank verification actor/time bypassed the initial gate. |
| `uv run --no-sync ruff format packages/proofops/application/mode_gate.py tests/acceptance/test_advertising.py` | exit 0; 2 files reformatted. |
| `uv run --no-sync pytest tests/acceptance/test_advertising.py -q` after fixes | exit 0; 41 passed in 0.54s. |
| `uv run pytest tests/acceptance/test_advertising.py -q` | exit 0; 41 passed in 0.53s. |
| `uv run --no-sync pytest tests/acceptance/test_advertising.py -q` after adding explicit True/False selector coverage requested by coordinator | exit 0; 43 passed in 0.56s. |

Fixed the review findings at the shared selector: refuse empty packs, inspect nested explicit policy markers and require nonblank verification metadata. No tests were deleted, weakened or replaced by mocks. Tests load real YAML, use actual snapshot hashing/validation and run the real disclosure evaluator; synthetic advertising clauses and approval metadata are explicitly labelled fixture-only and neither approve nor modify repository templates.

## Final checks

| Exact command | Result |
|---|---|
| `uv run --no-sync ruff check packages/proofops/application/mode_gate.py tests/acceptance/test_advertising.py` | exit 0; All checks passed, including after the final two selector cases. |
| `uv run --no-sync ruff format --check packages/proofops/application/mode_gate.py tests/acceptance/test_advertising.py` | exit 0; 2 files already formatted. |
| `uv run --no-sync mypy packages/proofops/application/mode_gate.py` | exit 0; no issues in 1 source file. |
| `uv run --no-sync pytest tests/acceptance/test_advertising.py tests/acceptance/test_rulepacks.py tests/acceptance/test_rules.py tests/acceptance/test_exceptions.py tests/contracts/test_package_contracts.py tests/unit -q -rs` | exit 0; 218 passed, 2 warnings in 3.84s (before adding the final two Boolean-selector cases; final focused suite is 43 passed). |
| `uv build --package proofops --wheel --out-dir /tmp/proofops-task024-dist` | exit 0; built `proofops-0.0.0-py3-none-any.whl`. |
| `git diff --check -- packages/proofops/application/mode_gate.py tests/acceptance/test_advertising.py` | exit 0. |

Built-wheel import check — exit 0, `Built wheel imports mode gate without adapters or network clients`:

```sh
uv run --no-sync python -I -c 'import sys; sys.path.insert(0, "/tmp/proofops-task024-dist/proofops-0.0.0-py3-none-any.whl"); from proofops.application.mode_gate import select_mode_rulepack; assert not any(n.startswith(("proofops.adapters", "boto3", "httpx", "scripts", "legacy")) for n in sys.modules); print("Built wheel imports mode gate without adapters or network clients")'
```

Integration verifies actual YAML → validated frozen snapshot → mode gate → pure disclosure evaluator and that the latter refuses a selected advertising pack. Security checks cover cross-tenant non-disclosure, approval and demo bypasses, malformed selectors, mixed/renamed/nested policies and preservation of immutable content/hash. Broader unit/contract warnings are existing Starlette TestClient httpx/AnyIO deprecations. No unrelated worker changes were repaired or overwritten.

## Remaining gates

No remaining critical/important issue identified inside the selection boundary described above.

- `blocked`: actual dedicated advertising policy/clauses, basis and rights approvals; repository templates remain unchanged and non-executable. No legal/effectivity or compliance claim is made.
- `not_run`: POST `/v1/runs` integration (explicit coordinator boundary), browser E2E, live advertising evaluator, real model/PDF/AWS tests, deployment security tests and private/customer data processing. All remain separate work/approval scopes.
- `not_run`: separate `python scripts/validate_package.py` run because it writes coordinator-owned shared evidence and is documentation/contract validation; executable contract/unit checks above did run.
- No migration is required. Removing the selector before its future HTTP integration reverts this isolated addition without rewriting stored snapshots or revisions.
