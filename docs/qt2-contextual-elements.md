# QT2 contextual element admission

QT2 adds the opt-in `QT2_ELEMENTS_POLICY` on top of the unchanged v23 default.
Select its canonical hash through the existing pinned-policy path. Removing that
pin restores v23; no migration, persisted revision rewrite, API field rename or
hosted default change is involved. Historical policy objects remain unchanged.

The frozen packet contains `qt2_contextual_elements_policy`. Its hash includes
prompt guidance and negative-admission patterns. Worker, tag service and wire
adapter validate the same policy. Raw model receipts remain immutable; only
source-verified selections can survive admission, and Python still computes grades.

- P2 accepts a model-selected comparison value and its year header from the same
  attested row. A saved comparison alone never creates a vote. A selected year
  can identify the comparison only when the value is also cited. Current-year-only
  citations and missing/unverified headers remain held.
- M2/M4 candidates may include at most two neighboring sentences on either side,
  inside the same canonical paragraph. Each proposed span verifies independently.
  Admission needs explicit activity/actor continuity, matching literal years and
  every supplied site/scope/other dimension. Unresolved supplied qualifiers block
  neighboring evidence. Proximity alone cannot fill a dimension.
- A concrete M4 action within the identical verified atomic claim may use literal
  attribution without inventing a missing actor, date or reduction amount. Supplied
  roles still verify and match. The three semantic votes must independently select
  that action; generic intentions, regulator-only boundaries, actor-only management
  roles and aspirational scope labels receive negative checks.
- No document-wide search or new cross-page exception is added. Existing explicit
  source-reference guards continue to handle those cases. Raw `unknown`, `conflict`
  and `unreadable` states never become `absent`.

## SC1 integration

`qt2_inventory.link_inventory(context, inventory, graph, run_id=..., tenant_id=...,
rulepack=...)` consumes `element-evidence-inventory-sc1-v1`. Merge SC1's
`element_inventory.py` before calling this entry point. It calls SC1's
`replay_inventory` to verify the three immutable raw receipts and full inventory
hash; a caller-supplied hash alone is insufficient. It matches subject/entity,
metric/metric, site/facility and period/reporting_period using exact NFC, whitespace
and casefold normalization. All four must have verified, non-null spans. Additional
qualifiers, including unresolved supplied axes, are conservatively held because
SC1's four-axis schema cannot prove them. M2/M4 attributes must be inside the cited
span. Same-paragraph/table constraints still apply to document-level candidates.

The additive `qt2-inventory-links-v1` result contains candidate IDs, three replica
IDs, element refs, the SC1 inventory hash and the QT2 policy hash. `grade_credit`
is always false: the integration owner must retain existing evidence/ensemble and
rule-engine gates when attaching this artifact. There are no new model calls.
SC1's scope-absence engine and QT1/FXE extraction/source repair are separate work.

## Offline R17 evaluation

`evaluation/qt2_replay.py` reads stored E14 parser snapshots, source attestations,
frozen packets and raw responses. Use `--mode prepare` to export gold-free simulator
inputs, then `--mode replay` or `--mode sim` to measure the fixed R17 audit sample.
`--root`, `--audit` and `--out` identify the stored inputs and artifact directory.
Simulation mode consumes three independent `sim-1.json` through `sim-3.json` files.
It invokes the real tag admission service through an offline transport only.

The reported comparison isolates QT2: unrelated saved element states are retained;
target states are replaced when their replay admission changes (or new simulation
votes are supplied). `raw_replay_before/after` retain the stricter reconstructed
local-path results separately. This is not a complete reproduction of the historical
global relation store or a fresh PDF source attestation. Current graph checks still
reject incompatible saved source spans. Claims without tag calls stay in the fixed
denominator. Simulator output is frozen before final guard tuning, so these are
development-sample diagnostic results, not held-out or live model accuracy.

The task artifact directory records per-element deltas, initial failed simulations,
final guard results, source hashes, Linux ARM64 tests, full-suite status and
the exact SC1 module hash used in the synthetic compatibility test. Rollout remains
opt-in and local; no deployment or paid model invocation is part of this change.
Per the coordinator's final instruction: full pytest deferred to I24 integration.
