# Geographic coverage is not organizational-boundary approval

2026-09-14 KST. The current execution path was traced before attempting another
note heuristic. Numeric checks live in domain/numeric.py, with no production
worker caller yet. Tagging/service.py forces LLM P6 votes to unknown and
reviews.py rejects a user-created present P6 without prior deterministic evidence.
LocalTagRunner remains synthetic-only. Thus current HTML/table-note evidence
must not be described as an integrated production numeric service.

A proposed exception would have allowed exact `데이터 커버리지 : 국내/해외/글로벌`
when an independently sourced organizational_boundary had the same text. Source,
claim binding, missing-boundary and suffix guards passed, but those guards do
not establish that geographic coverage and organizational boundary are the same
concept. Equal words do not authorize that domain mapping. The original domain
and docs27/28/31 do not supply that equivalence. This is distinct from arithmetic
unit syntax. The proposed exception was therefore removed before commit.

Orca Muse Spark1.3 Free independently identified the semantic gap in
 task_9eb5fabf0a12 / ctx_aa81c35d66c2 / msg_bd0568b723ab. It checked the numeric
source and binding defenses and explicitly left approval to the coordinator.
The coordinator rejected the mapping under the existing domain-freeze instruction;
no domain approval, grade policy or vocabulary was invented. The worker settled,
was released, its exact external terminal closed and delivery acknowledged.

Three fail-first negative regressions now pin this boundary: independently sourced
but equal geographic tokens remain footnote_conditions_unresolved even after the
observation's text-only footnote list is stripped. They failed with consistent
against the proposed exception and pass against the retained original engine.
The final production numeric implementation is unchanged from HEAD at turn start.
Focused numeric/table tests125 pass. No real API/model call or old-artifact rewrite.

The earlier pytest-coverage-final.log tests the rejected experiment and is not
final evidence. Final verification uses pytest-coverage-guard-final.log. Remaining
work is source verification, separately defined condition tags and deterministic
service integration; geographic word equality will not substitute for these.

Source-gate trace: graph_fusion.py always creates unverified/conflicted/unlocated
blocks. evidence/citations.py explicitly requires upstream quality=verified;
it does not create that source attestation. adapters/local/run_artifacts.py
loads a fence-published parser manifest via parser.load_verified: that verifies
artifact integrity, not source-quality approval. A source-quality stage must
therefore pin both its input graph and original PDF plus verification algorithm,
store a new immutable attestation, and replay it in the trusted loader before
numeric/claim consumers. Changing a graph flag or reusing location-proposal
counts is not an implementation of that stage. This is the next concrete
integration dependency, not a request to invent domain approval.

Final retained engine/regressions:1845 passed,2 existing deprecation warnings,
118.84s in `.local/note-review-integration/pytest-coverage-guard-final.log`.
Ruff and mypy162 pass;4 Python packages rebuilt after removing the exception.
Documentation/contracts validator758 passes separately. Diff check passes.
