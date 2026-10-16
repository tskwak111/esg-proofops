# V3 DEC-92/93 opt-in contract

Authority: `v25-V3.md`, R19-T04/T06/T08, and DEC-92/93 in the R108 redesign
lab. This additive profile starts at `6c6241f` (v24). It does not change frozen
regulatory/rubric files, historical prompt constants, or the v24 default.

Select `finals-unattended-v2` with the exact `canonical_hash(V3_POLICY)` via
`--analysis-policy-sha256`. The integration identifier is
`v3_finals_dec92_v1`; its tagging prompt profile is
`v3_dec92_categories_means_v1`. `policy_for` and `publication_policy_for`
both accept the new hash. Creation, preflight, reload and resume require the
corresponding exact preliminary prompt. Omitting the pin selects v24. To revert,
create a new run with v24; never rewrite a persisted run's policy or responses.

## Category and display

The model still selects the main-predicate track and safe-harbor category from
source-bound evidence. Simple company goals, net-zero and RE100 declarations
are `forward_looking` category candidates, including short goal table cells.
Current membership, management processes, achieved results, national targets,
and purpose clauses are not converted into goals. Existing Q1 explicit financial
forecast detection is retained even if a response mislabels the track.

The new validator rejects missing/inconsistent categories for retagging; it
does not repair old model responses or turn them into three fresh votes.
Explicit forecasts remain forecasts even when calculation terms also occur.
Estimates require the existing verified estimate-marker contract. Source,
scope, actor, numeric and consensus protections remain in force.

`provisional_grade.v3_safe_harbor` is an additive display record. Estimate keys
are `identified_as_estimate`, `estimation_method`, `uncertainty`; forecast keys
are `assumptions`, `scenario_or_premises`. The current tagging wire collects no
independent checklist facts, so these entries remain `unknown`, with
`checklist_status=retag_required`. Missing facts are never `absent` or `true`.
`reasonable_basis_documented`, grade mapping, E and label stay null. Legal
effect stays `not_determined`. Existing engine GAP-001 already enforces this
even when all ordinary ladder facts are present; no domain-rule change is needed.

## M1 and inferred performance

Only M1 can additionally use a complete verified immediately preceding sentence
in the same paragraph. It must name an existing review procedure and explicitly
repeat the actor and activity. The implementation conservatively requires the
literal actor at the sentence start, matching years and all asserted dimensions.
Unknown facility/scope/product/material/boundary, foreign relations, future or
negated means, intervening text, bullets and unverified sources reject admission.
The catalog is a candidate set; source verification and independent model
selection still apply. Unknown/conflict votes are never promoted by this policy.

A future review promise stays goal and receives no M1 catalog. The existing
Hyundai current review/approval case remains valid. M1 does not imply M4 or P1.
POSCO's formation date and carbon-reduction purpose create no reduction amount,
achievement or performance year. A separate literal achievement can be evaluated
on its own. The unanswered POSCO M4/M5 gold and AP-05 NAVER conflict remain excluded.

## Validation and integration

New tests: `test_v3_dec92.py`, `test_r19_source_semantics.py`,
`test_v3_pipeline.py`. Existing DEC24/Q1/QT2/SC1/safe-harbor tests remain intact.
The task's external V3 result directory contains host/arm64 logs, static checks,
row-level source review, measurement JSON and the final 20-line Korean report.
The full pytest suite is deferred to I25 as instructed.

`python -m evaluation.v3_replay --lab <lab> --output <V3-output>` reads retained
R17, DL4 and holdout artifacts with network disabled and source hashes checked.
It projects category holds/negative guards only. It does not rerun the current
model, recover new M1 votes, or establish live model accuracy. DL4 unmatched
atoms remain explicitly unmeasured. New M1 admission is demonstrated by synthetic
three-replica integration fixtures, not claimed as a real-cohort recall gain.

Likely integration conflicts are the shared policy registries, prompt allowlists
and renderers, preliminary validator, evidence admission and hold display dispatch.
Merge their additive branches without rewriting the frozen v24 constants or
silently composing V3 with another worker's policy. No database migration,
deployment or remote action is part of V3.
