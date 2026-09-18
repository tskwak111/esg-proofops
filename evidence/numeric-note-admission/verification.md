# Numeric checks must retain unresolved footnote conditions — 2026-09-14

Baseline409b094. The previous goal turn made concrete progress (crop-external
context retention and production scoped-unit normalization), but semantic note
ownership remains unproven. This checkpoint closes a downstream safety hole;
it does not fulfill the full service-readiness objective.

## Reproduced behavior and fix

Using the real graph/normalizer/citation/numeric-check pipeline with explicitly
synthetic source confirmation, a value carrying '해외 사업장 제외' or the Kia-like
EV3/EV6/EV9 restriction returned `consistent`. Source verification alone never
established that those qualifications matched the claim dimensions.

Numeric admission now looks up required footnote_of edges from the immutable
original table ancestry and numeric source cell. Qualified or unsupported note
text returns `not_computable`, reason `footnote_conditions_unresolved`, preserving
observation/source refs. Plain supported unit notes can still pass, provided the
literal equals the observation unit and its complete source reference verifies.
The unit-note grammar is shared with the normalizer rather than duplicated.

No new label, grade, applicability threshold or inferred condition is introduced.
An unresolved note is not evidence absence. General footnote prose currently has
no accepted semantic-condition contract, so it remains blocked; even harmless
prose may require future interpretation. This is a known coverage limitation,
not a declaration that every footnote materially changes every value.

Two further fail-first regressions closed bypasses: changing table_id cannot
hide immutable table ancestors; changing parent_relations source roots cannot
hide a cell-linked note. Roots must identify one source block with a verified
numeric quote and matching row/column. Removing the observation's footnote text
or citation list does not remove required original edges.

## Contract / compatibility

Pure Domain imports no application, adapter, filesystem, environment or network
module. Internal NumericSnapshot/NumericObservation protocols now require their
existing concrete graph edges and table/row/column attributes. Public v1 API/DB
schemas are unchanged. CheckResult uses its existing unresolved status/reason
fields; changed behavior applies to newly executed checks, never old reports.
Rollback restores prior checker behavior; retain new results rather than editing
historical results. No migration or dependency was added.

## Orca review

Run run_bd4f467aede6, task task_c0873a389b13, Muse Spark1.3 Free dispatch
ctx_97591933a9c2. Read-only review verified the table-id fix and plain-unit path,
and reproduced the parent_relations source-root bypass (msg_415a972c5bf8).
Coordinator reproduced it and added the root/source/coordinates guard. Reviewer
made no edits or paid API calls. Accepted completion was released; release said
external_terminal and the exact coordinator-created terminal was closed with
ptyKilled=true. Delivery acknowledged after disposition.

## Verification and limitations

Focused table/explicit-binding/numeric suite123 passed after final logic fixes.
No paid model calls; previous committed/reserved budget remains USD7.68289506 /10.
No new real-report accuracy result is claimed: source-note examples here are
synthetic regression tests. The54-table context retention experiment in the prior
checkpoint does not validate semantic note ownership. Goal remains active for
note association, exact condition extraction and cross-report original-image QA.

Additional coordinator regression: supported units supplied only by a note failed
numeric admission on prefix case/colon whitespace. Numeric unit proof now uses the
same bounded parser too. Three fail-first cases now pass, without relaxing source
verification or accepting prose. Final focused suite126 passed.

Execution-path audit: `rg check_numeric_consistency apps packages evaluation` finds
the Domain definition but no direct application caller. These changes secure the
numeric library's admission contract, not a demonstrated running service integration.
The goal must include connecting this check to the actual note-aware execution flow;
no end-to-end service claim can be based on these unit/integration tests alone.

Final checks:
- `uv run pytest -q`:1,806 passed,2 existing dependency warnings,143.18s;
  log `.local/numeric-note-admission/pytest-final-v2.log`.
- Focused numeric/table/binding suite126 passed,9.13s.
- Ruff passed; mypy161 files passed; four Python packages built from final code.
- Documentation/contracts validator756 passed; not an application accuracy test.
- `git diff --check` passed. No new live API/model, AWS, deployment or web trial.
