# TASK-017 · 산업 적용·결측 — Evidence (FR-017 / AT-017)

Coordinator acceptance: the CompanyContext wire schema permits `industry_code:null`.
Two regression cases initially failed because IndustryIdentity rejected that valid
missing state. Its code is now nullable and missing/unknown identity resolves to
`undetermined`. Fresh `uv run --no-sync pytest tests/acceptance/test_industry.py
tests/contracts/test_package_contracts.py -q` passes **35 tests** (6 industry,
29 package contract). Focused Ruff and Mypy pass after import formatting.
The pure resolver is accepted; summary endpoint composition remains downstream work.

## Scope

Implemented the pure `resolve_industry_applicability` domain function in
`packages/proofops/domain/applicability.py` and its local synthetic acceptance
fixtures in `tests/acceptance/test_industry.py`. The module has no network,
file, environment, AWS, model, application, or adapter imports.

GAP-010 remains unresolved: no real GICS-to-SASB/topic mapping was added or
claimed. Only an exact entry from a versioned mapping with
`verification_status="verified"` can yield `applicable` or `N_A`; missing
industry/topic coverage, no mapping, and unverified mappings yield
`undetermined`, so they cannot be used to remove an item from a denominator.
`mandatory` remains a separate `bool | None`: an applicable topic may be
optional, while `N_A` and `undetermined` never fabricate a mandatory result.

## Failing first

Before production code existed:

```text
uv run --no-sync pytest tests/acceptance/test_industry.py -q
```

Result: collection failed with
`ModuleNotFoundError: No module named 'proofops.domain.applicability'`.

The tests are real pure-domain calls using explicitly synthetic, local-only
mapping fixtures. They cover an applicable optional topic, an explicit `N_A`,
an unknown industry that must remain `undetermined`, and an unverified mapping
that must not remove a topic from the denominator.

## Fresh verification (2026-09-09 KST)

```text
uv run --no-sync pytest tests/acceptance/test_industry.py -q
```

Result: `4 passed in 0.01s`.

```text
uv run --no-sync ruff check packages/proofops/domain/applicability.py tests/acceptance/test_industry.py
uv run --no-sync ruff format --check packages/proofops/domain/applicability.py tests/acceptance/test_industry.py
uv run --no-sync mypy packages/proofops/domain/applicability.py
```

Results: `All checks passed!`; `2 files already formatted`; `Success: no issues
found in 1 source file`.

```text
uv run --no-sync pytest tests/acceptance/test_industry.py tests/contracts/test_package_contracts.py -q
```

Result: `33 passed, 1 warning in 0.46s`; the warning is the existing Starlette
`BlockingPortal` deprecation in `test_run_create_real_http_post`.

```text
uv run --no-sync python scripts/validate_package.py
```

Result: `Status: passed`, `695` checks passed, `0` failed. This is a
documentation/contract check, not an application test.

## Not run / intentionally blocked

No summary endpoint integration exists in this task's owned files, so API and
end-to-end integration are `not_run`. No real model, AWS, customer data,
industry mapping approval, legal/rights review, or rule-pack activation was
performed; those remain human/domain gates.
