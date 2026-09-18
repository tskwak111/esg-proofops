# Table-role tagging pilot — 2026-09-09

Implemented `evaluation.table_role_pilot` using existing same-page table-row context,
source refs, candidate identity validation and the shared Upstage budget adapter.
No production API/DB, parser graph, source quality, binding or grade was changed.

Three deduplicated LG Chem p24-t2 rows (raw rows 4/3/2) supply nine cells and their
first-row context. Short request-local IDs map back to complete original refs;
parser/table/row identifiers, tenant/version/manifest and original hash are retained.
The model returns each cell once with one proposed role and candidate header IDs.
Roles are category, activity_description, expected_effect, reported_result, unknown.
Activity description is explicitly NOT proof an action occurred. Unknown remains
unknown; expected benefits must not be treated as already achieved results.

The validator rejects missing/duplicate cells, extra grade fields, invented IDs,
unsupported roles and headers from another column or row context. Non-unknown
roles need a same-column header candidate. Unsupported merged/header arrangements
stay unknown rather than inheriting roles. This validates output structure and
source attribution, not semantic correctness. Invalid replies retain unresolved
cell IDs and the raw response; no repair or automatic retry occurs.

## Actual trial

One Upstage call returned nine tags: category 3, activity_description 3,
expected_effect 3, reported_result 0. The three expected effects concern electricity/
steam use or greenhouse-gas reduction. Their referenced column heading is 기대 효과;
all three activity descriptions reference 주요 활동. Coordinator inspected the
returned quotes/header refs; this agrees with the earlier p24 visual inspection.
This small development example is not a measured precision/recall benchmark.

Live artifacts are immutable in `.local/table-role-pilot/first/` (packet, request,
raw response, result, budget). The call used tagging contract v1; after adding the
same-column guard (v2), its raw response was revalidated offline and all nine tags
passed. `evidence/table-role-results.json` retains the new validator hash, original
request/prompt/model/response hashes, source refs and proposed tags. The original
v1 receipt was not relabeled. Explicit model hash fields for future requests were
also added after this call; derived actual model hashes are in the evidence record.

All nine source qualities remain unverified and bindings undetermined. No company,
period, achieved quantity, unit or source approval was inferred. Earlier sentence
candidates/revisions were not rewritten into new roles; this is an opt-in local
semantic tagging pilot, not a production filter or completed scoring pipeline.

Additional settled estimate $0.000389070. Cumulative ledger: 82 calls,
$2.035578950 committed/reserved of $10, including two earlier unsettled calls.
No Bedrock or AWS calls. Live mode is explicit; default is an offline packet preview.

Reproduce with `uv run --no-sync python -m evaluation.table_role_pilot --pdf PDF
--manifest MANIFEST --candidates .local/section-pipeline/live-two-packets/result.json
--output NEW_DIR`; add --live only for an authorized new call.

## Verification

Failing-first tests cover all-cell coverage, duplicate/omitted decisions, invented
IDs, unsupported roles, prohibited grades, and wrong-column headers. The stricter
header regression and archived real-response revalidation pass. Full suite:
`PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`:
1,431 passed in 107.08s, two existing Starlette/AnyIO warnings. Ruff lint/format,
mypy (145 sources), four Python package builds, architecture and supply-chain gates
pass. Deployed production E2E/AWS remain not_run. Documentation checks below are
separate from application tests.

Next: use these proposed roles as context for claim review across more E subsections;
then source-bound metric/year/Scope/unit/entity tagging and existing binding guards.
No expected-effect-to-performance conversion is authorized by this experiment.
