# TASK-012 — citation existence and normalization verification

Date: 2026-09-09. Scope: FR-012 / AT-012 pure-function acceptance path.
Outcome: assigned implementation and acceptance complete; broader shared parser-runner
regression has one reported failure. No commit, push, API/DB/contract, dependency,
lockfile, parser helper, or other worker's file was changed by this dispatch.

## Behavior and trust boundary

`verify_source_ref(ref: SourceRef, original: CanonicalDocumentGraph, *, tenant_id: str)
-> SourceRef` returns a new verified/rejected reference. Invalid input types and tenant
mismatch raise `DomainValidationError` without exposing source text.

- Reuses existing rich graph, native source, geometry and fixed v1 SourceRef. The
  source snapshot must be loaded from trusted internal storage under an authorized
  run; request-provided graph dictionaries are rejected. The function does not
  replace storage artifact authentication or run-level authorization.
- Checks tenant, document version, manifest, unique source ID, physical page,
  printed-page label, exact canonical bbox, full raw-block SHA-256, and nonempty
  end-exclusive raw Unicode-code-point offsets. The selected candidate must occur
  in the snapshot's matching tenant/version/manifest/artifact/parser batch.
- Requires upstream `source_quality=verified`, selected winner and location.
  Unverified/conflicted/unreadable/unlocated sources remain unchanged and cannot
  become verified merely because a supplied reference says verified. Native or
  vision source approval remains the upstream gate's responsibility.
- Compares only the exact pinned raw span after NFC, explicit text-ligature
  replacements (`ﬀ`, `ﬁ`, `ﬂ`, `ﬃ`, `ﬄ`, `ﬆ`) and whitespace normalization.
  No fuzzy search, relocation, punctuation deletion, case folding or NFKC occurs.
  Numbers, signs, years and units cannot be silently repaired by these transforms.
- Returns the literal raw quote with original raw offsets/hash. That pinned raw
  span supplies the normalization back-map; normalized-offset callers first use
  the existing geometry mapper. Neither the input reference nor snapshot changes.
- Citation existence does not accept claim binding, award present, compute grades,
  or convert rejection/unknown/conflict/unreadable into absent. Model/prompt/rule
  hashes and replicas stay in their existing caller-owned envelopes; no revision
  or report is overwritten.

All acceptance inputs are synthetic, explicitly marked in CandidateBatch. One test
creates actual local PDF bytes and runs the installed OpenDataLoader Java parser,
then verifies the resulting rich graph. The test explicitly supplies synthetic
human-confirmed source quality; a plain parser candidate first fails verification.
No model output, parser output, or citation outcome is mocked.

## Red/green evidence

Command: `uv run pytest tests/acceptance/test_citations.py -q`.

1. Before implementation: exit 1, **40 failed in 0.26s** because
   `proofops.application.evidence` did not exist.
2. Minimal implementation: exit 0, **40 passed in 0.19s**.
3. Additional local-parser integration: exit 1, **1 failed, 43 passed in 1.75s**.
   Reused PDF fixture text at `720 Td` was removed as a running header, leaving no
   paragraph candidate. The existing claim integration already demonstrates the
   body-text fixture at `400 Td`; this test now makes that local fixture adjustment.
   No parser, helper or assertion was weakened; an exact expected source-text
   assertion was added.
4. Final acceptance command: exit 0, **44 passed in 1.84s**.

Cases include fabricated values/years/quotes and forged verified flags, wrong
offsets/page/bbox/source/version/manifest/hash, quote-hash versus full-block hash,
Unicode emoji/Jamo/combining marks/ligatures/whitespace, meaningful normalization
differences, unselected parser candidates, unresolved source quality, missing
location/winner, duplicate source IDs, missing candidate provenance, altered
artifact chain, tenant denial, immutable results, fixed v1 schema validation and
actual parser integration.

## Verification commands and results

```sh
uv run --no-sync ruff check packages/proofops/application/evidence/citations.py tests/acceptance/test_citations.py
uv run --no-sync ruff format --check packages/proofops/application/evidence/citations.py tests/acceptance/test_citations.py
uv run --no-sync mypy packages/proofops/application/evidence/citations.py
```

All exit 0: `All checks passed!`, `2 files already formatted`,
`Success: no issues found in 1 source file`. Initial import-order and long-line
findings were fixed with scoped Ruff import sorting/formatting. No production
logic changed after the acceptance pass.

```sh
uv run --no-sync pytest tests/acceptance/test_citations.py tests/acceptance/test_provenance.py tests/acceptance/test_claims.py tests/acceptance/test_assurance.py tests/acceptance/test_parsing.py tests/acceptance/test_auth.py tests/acceptance/test_rules.py tests/unit tests/contracts tests/integration -q
```

Exit 1: **1 failed, 294 passed, 2 warnings in 18.21s**. Failure:
`tests/integration/test_local_parser_runner.py::test_http_upload_create_actual_parse_reopen_replay`
at line 97, expected `Page 2 emissions` in graph blocks. That shared fixture uses
the generated PDF with header-positioned text. This failure was reported to the
coordinator in `msg_a0b1f8c4ff70`; ownership remains with its existing worker.
The failing test was not deleted, weakened or edited.

```sh
uv run --no-sync pytest tests/acceptance/test_citations.py tests/acceptance/test_provenance.py tests/acceptance/test_claims.py tests/acceptance/test_assurance.py tests/acceptance/test_parsing.py tests/acceptance/test_auth.py tests/acceptance/test_rules.py tests/unit tests/contracts tests/integration/test_local_api_composition.py tests/integration/test_run_lifecycle.py -q
```

Exit 0: **291 passed, 2 warnings in 17.08s**. This explicitly bounded regression
includes all assigned acceptance cases, source/claim/assurance/rule tests, tenant
and authorization checks, unit/package contracts, actual local parsing, and local
API/run lifecycle integration. It does not erase the broader regression failure.
Warnings are existing Starlette/httpx and AnyIO deprecations.

```sh
uv run --no-sync python scripts/verify_architecture.py
uv build --package proofops --out-dir /tmp/task012-build-proofops
uv run --no-sync python -c 'import zipfile; from pathlib import Path; p = next(Path("/tmp/task012-build-proofops").glob("*.whl")); z = zipfile.ZipFile(p); assert "proofops/application/evidence/citations.py" in z.namelist(); print("PASS: citation module included in built wheel")'
git diff --check -- packages/proofops/application/evidence/citations.py tests/acceptance/test_citations.py
```

All exit 0. Architecture gates pass; sdist and wheel built outside the repository;
the wheel includes the citation module. Git's diff check does not inspect newly
untracked content; Ruff lint and format checks do inspect both new Python files.
Unit tests run the document/package validator in isolated temporary copies, not
as a substitute for application tests and without changing shared evidence files.

## Important review and remaining work

- Critical/important self-review: no unresolved issue in the tested pure-function
  scope. Raw original provenance is checked, not public `.to_dict()` projection;
  supplied verified flags cannot approve themselves; normalization remains pinned
  to the original span and immutable source record.
- `GET /v1/runs/{run_id}/sources/{source_id}`, persistence and worker composition
  are coordinator-owned integration work. AT-012 explicitly permits this tested
  pure-function route. Existing assurance verification was inspected, not rewritten.
- Product-model calls, AWS integration/mutations, private customer processing,
  rights/legal/data approvals, approved vision profiles, browser/product E2E and
  production accuracy: **not_run / externally blocked**. Actual local synthetic
  PDF parsing is tested; no whole-product production-readiness claim is made.
- No new dependencies or security-sensitive I/O were introduced. Relevant security
  validation consists of tenant/trust-boundary acceptance, auth/contract regression,
  and architecture gates; no new network dependency audit was run.
