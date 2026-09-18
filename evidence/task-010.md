# TASK-010 — 동일 packet 태깅 3회

Date: 2026-09-09. Scope: FR-010 / AT-010, approved application-function path.
The calling sequence below is superseded by `evidence/task-010-repair.md`: callers
must freeze and persist the complete selected track packet before all replicas.
No commit/push, shared contract/database/DTO/dependency edits, live model calls,
AWS changes or private customer processing were performed.

## Delivered behavior

- `application/tagging/service.py`: `tag_replicates` executes replicas 1/2/3 over
  one immutable `EvidencePacket`, or recovers each exact existing request. It
  reuses TASK-009 TrackCandidate, TASK-011 packet, TASK-012 citations, TASK-013
  binding, TASK-030 durable budget/usage, TASK-033 immutable cache/signatures and
  TASK-039 source-data guard. No second cache or budget implementation was added.
- `TaggingSettings` supplies explicit model/binding/profile/region, system prompt,
  output schema, maximum output, temperature and extraction epoch. The actual
  rendered system prompt includes schema and validated track/category and is
  hashed. The full retrieval element catalog is projected to the validated
  track; the original packet is unchanged and retains its original hash.
- Request signatures include replica, packet, rendered prompt, output schema,
  model/binding/region identity, output limit, temperature and epoch. Per-ensemble
  UUID request IDs are deterministic for same-request recovery; a new ensemble
  gets new IDs and executes new calls. Cache namespaces preserve tenant,
  document version, consent profile and role. Raw envelopes independently check
  request identity, packet, graph, model, prompt and rule pins before reuse.
- The durable usage repository reserves before dispatch and gates duplicate
  concurrent attempts. Budget exhaustion yields explicit partial replica states.
  Failed/indeterminate attempts retain unknown token/cost status and are not
  guessed free. Cache recovery creates no duplicate provider invocation or bill.
- Raw model text, usage/provider response ID, provider response body when
  available, source/graph/model/prompt/rule hashes and guarded tags remain in
  immutable TagRun receipts. Raw bytes and guarded results have separate cache
  records. Guarded keys also include original request, source graph, rulepack,
  role spans, validated classification and guard version; they cannot overwrite
  another ensemble or changed postprocessing revision.
- Before a present vote survives, citations must occur inside permitted packet
  spans and match original bytes/coordinates/hash; the relation role spans must
  pass actual `accept_binding`. An unsupported credited_from, foreign document
  version, unrelated product/period/table source, unresolved quality or open
  source issue cannot become confirmed evidence. The normalized tagged value
  must match a verified literal span (NFC/whitespace normalization only); missing
  numeric/year normalized values stay unresolved rather than hiding differences.
- Model grades/labels, wrong packet/replica, duplicate/missing/unknown element IDs,
  malformed JSON and source-less present fail validation with raw text retained.
  Model absent/N/A candidates become unknown because the retrieval coverage is
  bounded and has no verified absence/applicability attestation. Existing unknown
  and conflict remain unresolved. P4 coverage and P6 computed checks are reserved
  for their dedicated deterministic services and cannot be minted by model votes.
- Rendered document content is a data-only JSON field. Candidate/source and
  document-context allowlists prevent gold/prior-vote metadata leakage; only
  typed omitted/unprocessed source IDs and the explicit unknown absence state
  are projected from search metadata. No model tool/URL capability is enabled.
- `application/tagging/consensus.py`: `form_consensus` rejects duplicate/mixed
  replica, packet, tenant, graph, rule, model/prompt/epoch and request identities.
  Same state/value/attribution has a majority at two votes; 2:1 remains a review
  candidate. Any failed, invalid, pending, unknown/conflict, changed critical
  classification, supplied rule gap or duplicate provider response identity
  requires review. Three unanimously guarded votes produce real existing
  ConfirmedTags/ConfirmedFact values; different valid citations for the same
  fact are unioned. Explicit product attribution is retained as product_variant.
- Compound G/P/M elements retain the complete tagged value and source refs on
  their existing constituent primitives. No string is split to invent an
  unverified year, unit, baseline value or grade. Consensus confirmation concerns
  the requested tag set; the separate rule engine still decides whether its
  complete inputs and rule gates permit an actual grade.

## Agent transport

`apps/agent/src/proofops_agent/tagger.py` retains the existing `validate_tags` API
and adds `BedrockMessagesTagger.invoke`. It explicitly implements the Anthropic
Messages body format through the existing TASK-029 `ModelInvocationPort`/guarded
Bedrock invoker. Composition must select a compatible approved binding; the
adapter chooses no model ID/ARN, SDK client, credentials, alternate endpoint or
fallback. It checks preflight, tenant, binding/role/model/region and output limit,
sends system and user messages separately with no tools, and bounds/closes the
response stream. Truncation, refusal/tool output and malformed response bodies
remain failed/review receipts, preserving raw provider text where decodable.
Cache-specific usage without verified accounting remains unknown.

The provider format was checked against the primary
[AWS request/response documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude-messages-request-response.html).
The tests use the existing explicitly synthetic SDK transport and synthetic
account/consent fixtures to exercise real preflight/body/response handling;
these fixtures do not constitute actual account, rights or human approval.

## Calling contract and persistence ownership

`tag_replicates(packet, *, context, track, original, relation_tags, rulepack,
settings, cache, usage_store, invoke, tenant_id, ensemble_id, consent_profile,
token_counter, now, pricing=None)` returns three TagRun records in replica order.
`context` is TASK-013 ClaimContext; relation_tags maps source IDs to its typed
source-backed role mappings. `invoke` is an authorized callable returning
RawTagResponse; `BedrockMessagesTagger.invoke` implements the provider path.
Tokenizer, pricing and clock are supplied explicitly; tests use marked synthetic
counts/prices and the real local SQLite budget repository.

`form_consensus(runs, *, packet, rulepack, tenant_id, tag_revision, rule_gaps=())`
returns candidate elements, agreement counts, review status, three receipt hashes
and ConfirmedTags only when eligible. Composition stores the returned TagRun and
new TagRevision artifacts and advances heads using its existing CAS/lease flow;
this function does not change the claim GET route, storage schema or prior heads.
The existing cache adapter remains local-contract persistence until its separately
owned durable AWS manifest/fencing implementation is supplied.

## Red/green and important review

All checks invoke production functions, not mocked expected results. Fixtures
explicitly mark synthetic original sources, model responses, SDK transport and
token counts; local SQLite and immutable cache operations execute for real.

- Initial `uv run pytest tests/acceptance/test_tagging.py -q --tb=no`: exit 1,
  **22 failed in 0.14s**, because the assigned modules did not exist.
- First implementation exposed a real integration detail: retrieved claim refs
  are verified projections while the original Claim keeps candidate refs. The
  service now compares independently reverified original spans without mutating
  the claim. New-ensemble testing then exposed a guarded-cache collision; keys
  now include the original request ID. The original 22 tests passed (0.79s).
- Additional failing tests caught invented normalized values, hidden numeric
  differences when normalized_value was null, replayed provider IDs, gold context
  metadata, open parse conflicts despite a verified flag, lost product_variant,
  false disagreement between equivalent citations with different permitted scopes,
  relabelled claim document versions, lost malformed provider bodies, foreign
  credited sources and gold carried in search metadata. Each guard was corrected
  before its test passed; no assertion was weakened or removed.
- Full retrieval-catalog integration initially failed with **1 failed / 37 passed
  in 1.18s**. The service now requests only validated-track elements, preserves the
  same original packet, and hashes the rendered classification prompt; consensus
  uses the same requested track scope. Final acceptance: **38 passed in 1.06s**.
- Other cases cover failed replica review, malformed/source-less/extra-grade
  output, budget exhaustion, exact request recovery, fresh ensemble execution,
  concurrent duplicate dispatch, immutable packet content, real confirmed facts,
  2:1 majority preservation, SDK preflight rejection and truncated response usage.

## Verification

| Command | Actual result |
|---|---|
| `uv run pytest tests/acceptance/test_tagging.py -q` | exit 0, 38 passed in 1.06s |
| `uv run ruff check packages/proofops/application/tagging/service.py packages/proofops/application/tagging/consensus.py apps/agent/src/proofops_agent/tagger.py tests/acceptance/test_tagging.py` | exit 0, All checks passed |
| `uv run ruff format --check packages/proofops/application/tagging/service.py packages/proofops/application/tagging/consensus.py apps/agent/src/proofops_agent/tagger.py tests/acceptance/test_tagging.py` | exit 0, 4 files already formatted |
| `uv run mypy packages/proofops/application/tagging/service.py packages/proofops/application/tagging/consensus.py apps/agent/src/proofops_agent/tagger.py` | exit 0, no issues in 3 source files |
| `uv run python scripts/verify_architecture.py` | exit 0, all architecture/DTO/ports/composition checks passed |
| `uv build --package proofops --out-dir /tmp/proofops-task-010-dist` | exit 0, sdist and wheel built after final changes |
| `uv build --package proofops-agent --out-dir /tmp/proofops-task-010-dist` | exit 0, sdist and wheel built after final changes |
| `git diff --check -- packages/proofops/application/tagging/service.py packages/proofops/application/tagging/consensus.py apps/agent/src/proofops_agent/tagger.py tests/acceptance/test_tagging.py` | exit 0; Ruff also inspected untracked files |

Final related unit/contract/integration/security command:

```sh
uv run pytest tests/acceptance/test_tagging.py tests/acceptance/test_binding.py tests/acceptance/test_retrieval.py tests/acceptance/test_citations.py tests/acceptance/test_tracks.py tests/acceptance/test_rules.py tests/acceptance/test_preflight.py tests/acceptance/test_cost.py tests/acceptance/test_reproducibility.py tests/acceptance/test_provenance.py tests/unit tests/contracts tests/integration tests/security -q
```

Exit 0: **481 passed, 2 warnings in 38.52s** after final production changes.
The warnings are existing Starlette/httpx and AnyIO deprecations; no regression
failure was observed. Both built wheels were also opened with stdlib ZipFile
and confirmed to contain the assigned service/consensus/agent modules.

Earlier runs of the same scope passed 478 tests before the last provenance cases,
and 480 tests before the full retrieval-catalog correction. Initial Ruff import
and line-length findings were fixed within assigned files. One newly added test
initially missed an import removed by Ruff when unused; the import was restored
and the production failure was then observed before implementing its guard.

## Remaining gates / explicit limitations

- **not_run**: real product-model/Bedrock calls, real AWS/IAM/search/cache services,
  private customer data, approved model tokenizer/price measurements, production
  accuracy or statistical independence claims. Three receipts prove distinct
  attempted invocations, not independent model accuracy.
- **blocked/not_run**: human data/rights/legal/domain/model approval gates, actual
  vision profiles and domain-gap release. They were not synthesized or bypassed.
- **not_run**: browser/product E2E and API/worker persistence composition. AT-010
  explicitly permits the application-function path exercised here. No new task
  status/API/storage contract was introduced and no existing revision was changed.
- No automatic schema-repair/model fallback is attempted. A failed or uncertain
  call requires review/recovery; a new ensemble explicitly starts fresh requests.
  An in-flight/settled request with no recoverable raw response stays pending
  rather than dispatching a duplicate. Durable cross-process cache publication
  and cloud fencing remain with the cache/storage owners.
- Bounded search cannot attest absence/N/A; P4/P6 require their dedicated service
  outputs, and nonliteral normalization needs an approved normalization contract.
  These candidates remain reviewable, not false present/absent facts. This task
  does not claim the whole PDF→grade→review→export product is complete.
- **not_run by this worker**: top-level `python scripts/validate_package.py`, which
  writes coordinator-owned evidence. Existing unit/package-contract tests ran;
  document validation is not represented as application verification.
