# TASK-000 dependency license / lock record

Date: 2026-09-09 (UTC). Python 3.12 (`/opt/homebrew/bin/python3.12`), uv 0.12.7, pnpm 10.34.5, node v24.

## Decision

New runtime dependencies are limited to the stack already chosen in
`docs/04_TECH_STACK.md`. No AWS SDK, no parser, no model SDK, no PyMuPDF
(license gate is TASK-042), no new paid service. Build/lint/test tools only.

## Python — locked in `uv.lock` (workspace root)

| Package | Locked version | License (installed metadata) | Use |
|---|---|---|---|
| fastapi | 0.119.1 | MIT | API service (`apps/api`) |
| pydantic | 2.13.5 | MIT | API DTO boundary (`proofops_api/dto.py`, strict/frozen) |
| uvicorn | 0.34.3 | BSD-3-Clause | API entrypoint |
| starlette | 0.48.0 | BSD-3-Clause | fastapi transitive |
| httpx | 0.28.1 | BSD-3-Clause | TestClient (contract tests) |
| pytest | 8.4.2 | MIT | contract tests |
| ruff | 0.8.6 | MIT | lint/format |
| mypy | 1.20.2 | MIT | type check |
| jsonschema | 4.26.0 | MIT | fixed-schema cross-checks (tests, verify script) |
| pyyaml | 6.0.3 | MIT | (sibling validator dep; reused, not new) |

Build backend: hatchling (MIT, build-time only) for all four members.
The flat `proofops` member uses ordinary file selection with a `proofops` path
prefix and an explicit editable parent path. This includes new subpackages
without a manual package list. The interim setuptools backend was removed;
no additional dependency or custom build hook is introduced by this correction.

The `proofops` domain package itself has zero third-party runtime
dependencies (verified by `scripts/verify_architecture.py` purity scan).

## JavaScript — locked in `pnpm-lock.yaml` (workspace root, `apps/web`)

| Package | Locked version | License (node_modules metadata) | Use |
|---|---|---|---|
| react / react-dom | 19.2.8 | MIT | web baseline |
| react-router | 7.18.3 | MIT | web baseline routing |
| vite | 6.4.3 | MIT | dev/build |
| typescript | 5.9.3 | Apache-2.0 | typecheck |
| @vitejs/plugin-react | 4.7.0 | MIT | vite react plugin (v6 line rejected: it requires vite 8) |

## Not introduced (deferred to owning tasks)

boto3/botocore (TASK-028/029+), opendataloader/pdfplumber/pypdf (TASK-003/043),
strands-agents/bedrock-agentcore (TASK-010/029), PyMuPDF (license gate TASK-042),
playwright/vitest (later UI behavior tasks). No live Bedrock/product model
calls, no AWS mutation, no secrets added.
