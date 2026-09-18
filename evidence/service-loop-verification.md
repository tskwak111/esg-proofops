# Sentence and table-context service loop — 2026-09-13 KST

Not service-ready. This wave fixes concrete extraction/context failures and repeats
actual table-role tagging, without asserting independent semantic accuracy or
verified element attribution. Full receipts/hashes are indexed in
`service-loop-results.json`.

## Changes

1. New Upstage extraction profiles reject claim spans overlapping unclosed paired
   source quotations (`‘’`, `“”`). This reproduced two Doosan paragraphs split in
   the middle of a quoted KPI description. English intraword apostrophes are
   exempt. This is a conservative source-fragment check, not a grammar model.
   A stray closing quote marks the preceding prefix unresolved; it can also reject
   otherwise usable text in that prefix. One invalid span still rejects the whole
   extraction response, so good sibling sentences can require re-extraction.
2. The guard is explicit opt-in on `validate_extraction_response`, enabled by the
   new Upstage profile and quote evaluation entrypoint. The core default retains
   legacy behavior, so existing stored-response replay does not change old claims.
   New rule hashes require new extractor runs. Original outputs are never repaired.
3. Table context retains row/column spans. A header must cover the complete value
   column interval; partial overlap is rejected. Querying a known table cell now
   selects its own row instead of other rows with identical text such as `tCO2e`.
4. One canonical source retains one short model-facing ID across rows. Distinct
   cells with repeated text remain distinct. Rows use physical-page/table/row
   order instead of UUID order. Allowed header IDs are supplied explicitly and
   independently validated. The prompt now explicitly excludes context-header
   entries from output targets.

Table tags remain `model_proposed`, source quality unverified/unlocated and binding
`undetermined`. Nothing here assigns evidence grades, approves evidence, changes
API/DB shape, or enables real element-tagging service composition.

## Actual replay and API comparisons

Stored-response quotation replay covered381 records from five companies and152
unique source IDs, including repeated development variants and new-page samples.
374 remained accepted by the copying guard, one stayed rejected by the existing
word-boundary guard, and six responses over the two cut Doosan paragraphs became
unknown under the new gate. This is diagnostic replay, not152 independent human
labels or an accuracy estimate. All originals remained unchanged.

Four deliberately different table-input configurations ran on the same five tables
from Kia45, KB30 and NAVER84. All20 real Pro4 calls settled; no automatic retries.
The final inputs target64 cells after excluding the first row. Multi-level headers
can still appear among targets, so these are not64 independently adjudicated data cells.

| Configuration | Structurally valid tables | Observation |
|---|---:|---|
| Preserved spans and own-row selection |3/5| Duplicated header IDs and cross-column citations caused rejection. |
| Stable source IDs and explicit allowed headers |5/5| All target IDs and header bindings passed. |
| Source row ordering |3/5| Model also output context-header IDs, which were rejected. |
| Explicit target-only prompt |5/5| All64 target cells returned and validated. |

These results are not semantic accuracy and the calls are not independent votes.
Roles changed across runs: numeric target/actual columns were sometimes unknown,
and NAVER's achieved/in-progress mixed cell could receive a coarse reported-result
role. Do not promote a whole mixed cell to a complete achieved claim. The transient
5/5 result in the second configuration was explicitly not treated as release proof.

All20 calls added an estimated USD0.018253950 including the configured VAT reserve.
The existing USD10 ledger now records1171 calls and USD6.1627026950 committed or
reserved: settled estimates USD1.1627026950 plus five unresolved USD1 reservations.
No reservation was refunded, no new ledger was used and no cloud changes occurred.

The first table trial constructed an in-memory SourceArtifact with temporary
`document_id`/`object_version_id`; CandidateBatch does not carry those fields.
Original tenant/document-version/source-byte/page/request/response hashes matched.
The correct original manifest identities are appended in
`.local/service-loop/table-roles/provenance-correction.json`; paid packets/results
were preserved. Later trials use original manifest identities directly. This
correction is not concealed or described as an immutable original artifact.

## Orchestration outcomes

Orca `run_b5fe34ddbe68`, OpenCode Muse Spark1.3/1.2 Free:
- `task_bb80e29e2808`: sentence audit succeeded; identified cut source quotations,
  label admission and omitted assertions. The quotation case was fixed; general
  assertion quality remains open. Omitted ranges already remain unknown downstream.
- `task_8d73aaeac6ef`: tagging-path audit completed; confirms Upstage service mode
  currently blocks actual element tagging. Coordinator rejected its suggestion to
  continue paid siblings after an unresolved transport failure, and its proposed
  synthetic source/consensus test as proof of real readiness. A second accounting
  store is not authorized as a replacement for the existing USD10 authority.
- `task_082687739510`: final code review found no blocking regressions and ran51
  focused tests. Conservative stray-quote handling and cross-page table limits
  remain documented. The final target-only prompt wording followed this review.

All three dispatches settled, were released and terminals closed; reclaimable
worker query returned none. Reports remain under `.local/service-loop/`.

## Verification

- Failing-first regressions reproduced missing merged spans, wrong-row fan-out,
  repeated header aliases, UUID-dependent row order and cut-quotation admission.
- `uv run pytest -q`:1639 passed, two dependency warnings,112.85s. Includes unit,
  integration, contract, backend E2E and security tests. The final prompt wording
  was subsequently checked by five real calls and focused tests.
- `uv run ruff check apps packages tests evaluation`: passed.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`:
 153 source files passed, three existing untyped-body notes.
- `uv build --all-packages --out-dir .local/service-loop/dist`: four packages built.
- `uv run python scripts/verify_architecture.py`: passed.
- `uv run python scripts/validate_package.py`:741/741 passed; documents/contracts
  only, not an app benchmark.
- Final focused extraction/table-context checks:57 passed.
- Web code/dependencies unchanged: prior web build/dependency audit not rerun.
- New browser E2E, actual element tagging/consensus service, human gold, deployment:
 not_run. Actual table-role model calls above are a separate evaluation path.

The next integration must connect an explicitly bound Upstage tagger and the single
budget authority to frozen evidence packets while preserving source-quality and
attribution gates. This is engineering work still missing, distinct from approval
of unresolved domain rules. Labels/glossary entries and complete predicate/context
preservation also need an independently reviewed benchmark before release claims.
