# Source ownership revisions and revalidation

The existing source-review revisions API now accepts bounded factual ownership
proposals, preserving each proposal separately from its server-derived assessment.
Only a confirmed canonical footnote with a retained explicit footnote_of relation,
matching target geometry/table ancestry and verified original evidence can be accepted.
Native note marker/proximity/model proposals do not establish ownership.

A transient canonical view uses whole, confirmed citations for the existing selected
candidate only. It does not select another candidate, repair source conflicts, create
native canonical blocks, clear issues, or publish a graph to downstream consumers.
Withdrawing a citation reconstructs that view and reevaluates every ownership proposal,
including omitted entries. Old revisions and cached responses remain immutable.

Orca implementation task task_80fc01b4c653 / ctx_4df05ba7ff4e contributed the pure
validator and its tests; its 73 focused checks passed and it was released/acknowledged.
Coordinator review added regressions rejecting nonexistent fragment IDs even for
unknown/conflict submissions, and refusing to retype a canonical cell as a footnote.
The four new cases failed first and passed after correction. The HTTP test covers
unknown proposal persistence, forbidden client accepted state, exact retries,
historical GET, candidate-specific source verification and withdrawal. Confirming an
unselected candidate does not verify the selected candidate. Focused suite: 33 passed,
2 dependency warnings in 3.63s. Read-only review task task_3bbcf8d66778 /
ctx_a4884b91335d reproduced two P2 findings: unbounded accumulated ownership and
missing implementation provenance. Both were fixed by the coordinator after red tests:
new IDs above 256 return 413 without publishing, existing entries at the cap remain
editable, and assessments record a server-computed hash covering ownership validation,
reviewed-view construction and citation verification. The HTTP regression fills the
actual cap and checks unchanged history/head after rejection. The transport body limit
also rejects a large annotation body; this is distinct from the accumulated count cap.

The reviewer also found nondeterministic test selection of a same-text singleton;
the fixture now explicitly selects the multi-candidate table cell for the losing-source
regression. Product admission rules were not loosened. Review artifacts are in
`.local/ownership-review/`; the reviewer settled and was released/acknowledged before
the coordinator's final regression runs. It did not independently rerun the final fixes.
Final full suite: **1999 passed, 2 warnings in 146.68s**;
log `.local/note-review-integration/ownership-full-final.log`. Document/contract
validation passed 784 checks (49 operations); it is not an app accuracy metric.

Full local API checks used real committed report checkpoints with synthetic local
reviewer sessions, not independent human/domain-expert approval:

| Report/page | Result | New revision |
|---|---|---|
| LG Chem/97 | Native biomass note has a candidate table, but no supported ownership proof; unknown | 3 |
| Samsung Electronics/72 | No canonical table target exists on that page; empty unknown ownership retained | 3 |

Both exact retries matched, previous revisions stayed identical, original issues and
unknown coverage were preserved, and no numeric receipt was emitted. LG revision hash:
`1dca879db2898b18805cf0bc20160b4f4153fe8dca7114edeba98a0a16c87b22`;
Samsung: `88b32cc0839935979c3456b9cf31944017ae2ba14b3a86757a071fc4e36cdbda`.
Private requests/responses: `.local/note-review-integration/source-ownership-api-v1/`.
The Samsung harness initially stopped before writing because no table existed; it then
recorded unknown with no invented target. No external model calls or ledger changes.

This does not close the service-path audit. Native explicit ownership proofs/derived
source views, condition interpretation writes, original-backed table role inputs,
coverage completeness, actual numeric receipts and shared downstream consumers remain
outstanding. Canonical positive ownership currently has synthetic fixture evidence;
these real reports demonstrate conservative holds, not successful numeric comparisons.

Final-code real-report revalidation appended revision 4 with code provenance; revision
3 and all earlier revisions remain unchanged. Both ownership assessments still unknown,
coverage unknown, no numeric receipts, exact retries identical. Revision hashes:
LG Chem `13ef1a827009712e3b9fd249ca3998df74a44e4dbf835b819c856026fff56e5f`;
Samsung `067e25ef5b1335ae9bd228b18083ac35001538ea1fd671012d6962bb9d09e867`.
Both policy hashes: `3575b9679d7fa9af6dfbeca73d7964c43a500759263660db56cb763148560dee`.
Private requests/responses: `.local/note-review-integration/source-ownership-api-v2/`.
Ruff lint/format (289 files), CI mypy (171 files), architecture validation and all four
Python package builds passed. Installed-wheel replay reopened all 18 actual checkpoints
with unchanged graph hashes and zero model calls. These are compatibility and hold
checks, not real-report positive ownership accuracy or deployed throughput evidence.
