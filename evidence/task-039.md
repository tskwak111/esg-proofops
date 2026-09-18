# TASK-039 — external communication and prompt injection guard

Date: 2026-09-09. Scope: SEC-003 / AT-039 pure application boundary.
Assigned implementation and local acceptance/security verification completed.
No commits, pushes, shared contracts, API routes, parser helpers, dependencies,
lockfiles, AWS changes, product model calls or customer documents were involved.

## Implemented boundary

`guard_untrusted_packet(text, server_metadata: PacketMetadata, *, original:
CanonicalDocumentGraph, tenant_id: str) -> GuardedPacket` handles one verified
evidence snippet. Larger windows and packet construction remain packet-builder
responsibilities; no competing full EvidencePacket DTO was introduced.

- Server metadata is a frozen typed value with a detached model/tool allowlist,
  run/claim/tenant scope, source pointer, selected model binding, system template
  and byte limits. Unknown constructor fields such as label/holdout_gold fail.
  Composition must resolve these values from trusted server state, not request,
  PDF or model output. The original graph must be loaded under an authorized run.
- TASK-012 verifies the original rich graph's tenant/version/manifest/artifact/
  source/page/bbox/hash/offset chain. Packet text must equal that literal verified
  source span. Unverified/conflicted/unreadable/unlocated evidence is not upgraded.
- Original text and SourceRef are serialized only inside `untrusted_document_data`.
  Role delimiters, JSON-looking strings, URLs, NULs, multilingual commands and
  label instructions remain literal source data. They never alter system_prompt,
  server metadata or tool arguments. The guard does not claim that escaping text
  alone prevents a language model from following malicious semantic instructions.
- `authorize_tool("read_source", {"source_id": ...})` resolves only the already
  verified packet source and only if this tool was enabled by the server. Extra
  arguments, alternate IDs, tenant/run/document filters, query DSL, URL and label
  requests fail. This returns the bounded immutable source directly, without a
  generic database query, callback or network read.
- `authorize_model(binding)` requires the exact selected allowlisted binding,
  including role and synthetic status. No model fallback is inferred from text.
- P0 evidence tools have an **empty URL allowlist**. `authorize_url` rejects every
  target, including private/link-local/file URLs and the provider URL itself.
  Authorized provider communication is a separate TASK-029 Bedrock path with its
  own account/region/endpoint/model/consent checks; the PDF has no URL capability.
- UTF-8 input and rendered packet byte budgets are enforced. Overflow fails
  without truncating evidence. Larger packet selection and provider token budgets
  remain existing packet-builder/tagging responsibilities; byte counts are not
  presented as model token counts.
- Packet content and server policy are canonically hashed. Input source pointers,
  metadata and previous packets are unchanged. Existing tagging/provenance code
  retains replica/model/prompt/rule receipts; this function grants no grade or
  label authority and never converts unknown/conflict into absent.

No adapter was added. All source and approval examples are explicitly synthetic.
The integration test uses the existing in-process SyntheticBedrockClient to record
real attempts through BedrockInvoker and preflight; it does not mock either guard
or make AWS/model/network requests. It verifies selected binding identity, fixed
model dispatch, preservation of hostile text as data and denial when trusted
consent is unapproved despite the PDF claiming approval.

## Failing tests and implementation

```sh
uv run pytest tests/acceptance/test_injection.py tests/security/test_prompt_injection.py -q --tb=short
```

Before implementation: exit 1, **28 failed in 0.14s**, all because
`proofops.application.evidence.packet_guard` did not exist.

```sh
uv run pytest tests/acceptance/test_injection.py tests/security/test_prompt_injection.py -q
```

After minimal implementation: exit 0, **28 passed in 0.07s**. Additional review
checks for detached mutable allowlists, sanitized errors/repr, invalid Unicode,
unknown/conflict preservation and source-less present brought the suite to
**31 passed in 0.08s**, exit 0. No tests or acceptance assertions were removed or
weakened. Initial import-order/line-length findings were fixed with scoped Ruff
sorting and formatting.

## Final verification

```sh
uv run pytest tests/acceptance/test_injection.py -q
```

Exit 0: **21 passed in 0.09s**.

```sh
uv run --no-sync pytest tests/security/test_prompt_injection.py tests/acceptance/test_citations.py tests/acceptance/test_preflight.py tests/acceptance/test_auth.py tests/acceptance/test_upload_security.py tests/unit tests/contracts tests/integration/test_local_api_composition.py tests/integration/test_run_lifecycle.py -q
```

Exit 0: **251 passed, 2 warnings in 17.42s**. Includes the 10 prompt-injection
security cases, citation and preflight dependencies, auth/upload security,
unit/package contracts and stable local API/run lifecycle integration. Existing
Starlette/httpx and AnyIO deprecation warnings remain. Active WIP integration files
owned by other workers were not included. Unit document-validator checks operate
in temporary copies; they do not replace application tests or modify shared evidence.

```sh
uv run --no-sync ruff check packages/proofops/application/evidence/packet_guard.py tests/acceptance/test_injection.py tests/security/test_prompt_injection.py
uv run --no-sync ruff format --check packages/proofops/application/evidence/packet_guard.py tests/acceptance/test_injection.py tests/security/test_prompt_injection.py
uv run --no-sync mypy packages/proofops/application/evidence/packet_guard.py
uv run --no-sync python scripts/verify_architecture.py
```

All exit 0: `All checks passed!`, `3 files already formatted`,
`Success: no issues found in 1 source file`, and architecture gates all passed.

```sh
uv build --package proofops --out-dir /tmp/task039-build-proofops
uv run --no-sync python -c 'import zipfile; from pathlib import Path; p = next(Path("/tmp/task039-build-proofops").glob("*.whl")); assert "proofops/application/evidence/packet_guard.py" in zipfile.ZipFile(p).namelist(); print("PASS: packet_guard included in wheel")'
git diff --check -- packages/proofops/application/evidence/packet_guard.py tests/acceptance/test_injection.py tests/security/test_prompt_injection.py
```

All exit 0. Sdist/wheel built outside the repository and the guard is included.
Git diff does not inspect new untracked files; Ruff inspected all new Python files.

## Critical/important review and handoff

No unresolved critical/important issue found in this tested pure boundary. These
are code-enforced capability checks, not an injection-detection keyword classifier
and not a claimed model-security benchmark.

Coordinator-owned agent/worker composition must call the guard and enforce its
tool/model authorizers on every generated request, keep system/user messages
separate, then use TASK-029 preflight/BedrockInvoker and strict LLM output parsing.
This dispatch changes no live agent loop or `POST /v1/preflight` API; AT-039 permits
the pure-function acceptance path. Existing output-contract tests reject injected
grade/label/sublabel fields and source-less present, preserving unknown/conflict.

Real product-model adversarial evaluation, cloud network/egress enforcement, AWS
integration, approved runtime/vision profiles, private-data/rights/legal approvals,
and browser/product E2E remain **not_run / externally blocked**. Source-quality
approval is upstream; arbitrary PDF extraction before that approval does not use
this verified-evidence function. No production-ready or universal prompt-injection
resistance claim is made.
