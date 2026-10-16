# CF6 finals default candidate: DEC-125 + DEC-127

CF6 combines two-of-three verified element agreement and scoped non-observation
in one opt-in policy. It implements the user's DEC-127 decision: after three
completed tagging replicas, an element still unknown because evidence was not
found or linked becomes `absent_in_scope` inside the selected analysis pages.
This is a system result, not an exhaustive-search or full-document absence claim.
The existing Python rule engine determines the grade; LLMs only extract and tag.

## Policy registration

`CF6_V2_POLICY` in `packages/proofops/application/analysis_profile.py` extends the
v27 policy with `integration_profile=cf6_finals_default_candidate_dec127_v2` and
`cf6_confirmation=CF6_V2_CONFIRMATION_POLICY`. The round-1 `CF6_POLICY` entry stays unchanged; v2 is the single current candidate.

- Full policy SHA: `55ba436c920e6a6911bc48ae70e7074eca23d5ba06fad801630e5c78d4380ca8`
- Element/scope policy SHA: `3672d4364836d931d322577503f2b2cca9a5a0ab6d4e240e374a73e61cc11445`
- Three-vote diagnostic reference: `0dad8cf2710a25f209ab770f5ee33b45e6bfc05c619ba583d125d1c1c727010f`
- Unchanged v27 default: `fcd788f4c89034141c8767913f1c1acabdaefa1c8f543cdc5231903f05fa1804`

Use `finals-unattended-v2` with the explicit full policy hash. The hosted operator
key is `analysis_policy_sha256`; the evaluation wrapper option is
`analysis_profile_sha256`, passed to the child as `--analysis-policy-sha256`.
`policy_for`, `publication_policy_for`, and `evaluation/hosted_r108.py::prepare_argv`
register the candidate. `V2_POLICY` and all historical entries remain unchanged.

For the next finals default, the coordinator composes `cf6_confirmation` onto its
new integrated policy, assigns that policy a new identity/hash, appends it to the
three registration points, and includes the hash in hosted table/duplicate
projection sets. Default activation/deployment belongs to the coordinator; this
branch changes no deployed default or configuration.

## Publication contract

1. The worker freezes the selected pages, CF6 policy and full analysis-policy hash
   into the packet before display transformation/request construction. New
   requests have distinct identity from historical work.
2. The adapter validates current responses against the settled broker ledger and
   original raw sidecar: tenant, replica, wire, schema, model, policy, request and
   provider identity must match. Authentication failure retains usage/raw evidence
   but supplies no publication authority. Saved, synthetic, cached or replayed
   responses never gain fresh authority by resealing.
3. All three tagging responses must complete. Track/category remain unanimous
   (3/3). Present requires two verified source references with matching value,
   binding and scope; a third unknown is allowed. Any explicit conflict, verified
   contrary source, or different verified value/binding/scope remains conflict.
4. Remaining unknown elements become `absent_in_scope` under DEC-127, with
   `absence_basis=DEC127_SYSTEM_NON_OBSERVATION`. SC1 inventory completeness is no
   longer an absence prerequisite. This replaces the earlier uncommitted CF6
   design; it does not modify the historical DEC-85 evaluator or its receipts.
5. The new `domain/rules/cf6_scope.py` calls the existing Python ladder with scoped
   facts. Claims with unverified own quotes, unresolved type, grade-blocking GAP,
   incomplete/failed replicas or TIME_BUDGET remain held. Source exceptions use their explicit original-domain branches; estimate and
   retag safety holds remain. GAP-005 preserves a decided E-grade
   with `sublabel=null`, as explicitly required by domain §31; no sublabel mapping
   is invented. All ladder elements must resolve and any conflict blocks publication.
6. Checkpoints add `cf6_receipt` and `cf6_confirmation`; loading recomputes and
   compares the receipt. Public confirmation carries rule-pack, model, prompt,
   analysis/confirmation policy hashes, selected scope and receipt hash.
7. Hosted results add `cf6_status`, `cf6_track`, `cf6_elements` and hold reasons.
   A decided CF6 grade fills `decision`/`confirmed_grade` when no existing decision
   takes priority. The web view says “확정 등급”, displays scoped absence, and
   hides retained provisional diagnostics for CF6 claims. Held CF6 claims remain
   visibly held. Existing human decisions retain priority.

The trust boundary is the controlled adapter and immutable checkpoint reader.
A digest does not protect against application-process/artifact-writer compromise.
Controlled fabricated TagRuns in tests are not production publication authority.

## Saved-run policy evaluation

Evidence is under `outputs/agent-results/R108-redesign/lab/confirm/CF6/` in the main
workspace. The four saved runs contain 711 claims and 1,905 retained tag responses.
These are immutable live-vote counterfactuals, not fresh publication or resealed
receipts. Before is the actual saved public result; after is DEC-125+127 eligibility.

| Report | Original confirmed/provisional/held | Round 1 | Round 2 | Round 2 E0/E1/E2/E3 |
|---|---:|---:|---:|---:|
| E16 LG Chem | 0/122/93 | 123/0/92 | 173/0/42 | 54/107/12/0 |
| E16 Kakao | 0/63/81 | 81/0/63 | 110/0/34 | 47/59/4/0 |
| E16 LG Electronics | 0/36/105 | 57/0/84 | 74/0/67 | 39/31/4/0 |
| E17 LG Chem | 0/120/91 | 124/0/87 | 172/0/39 | 54/105/13/0 |

The revised 3/3 and 2/3 policies both confirm 529 candidates, but 2/3 improves
48 grades relative to 3/3 (LG E16 14, Kakao 13, LGE 5, LG E17 16). The full
before/after grade distributions, including original provisional grades, are
in `round2-summary.json`. Two-of-three totals are E0/E1/E2/E3 = 194/302/33/0.

R20 has 69 confirmable claims among 174 audited claims, versus 43 in round 1.
The audit establishes **at least 48 lower-than-source-supported grades**
(LG 15, Kakao 19, LGE 14), versus 25 in round 1. The 23 newly counted E0 cases
have conservatively supported E1 minima: named means/current implementation,
without assuming organizational scope or assurance. Kakao index 0 is excluded
because the audit flags a 2025/2026 period-binding ambiguity. Other exclusions:
18 have no demonstrated increase, one is a mixed claim, and one (Kakao index 71)
has a known p51/p134 assurance-level conflict not captured in the saved votes.
These are minimum-grade comparisons, not complete gold grades or accuracy rates.

Three fresh tool-free Codex CLI replicas, concurrency at most two, tested 38 R10/R11
contexts. Literal quotes plus the Python engine still produce **two false E3
candidates among 26 negative cases** under both thresholds; 12/12 positive controls
reach E3. Round 2 reuses those same saved extractions: DEC-127 also decides two negative
contexts at E2 and three at E0. Thus 7/26 old hold labels now receive a grade
(2 E3, 2 E2, 3 E0); the old gold labels are retained. The E0 changes follow the
new absence rule and do not establish that the extraction errors are fixed. Simulated public confirmations
remain zero because production freshness/source/binding gates are not bypassed.
R16/R16b PDF replay keeps all 11 hidden/clipped cases unverified, with six visible
controls and three Kakao p55 spans verified. These checks do not establish model
accuracy or zero-error production behavior.

## Round 2 root causes and exact gaps

Of the previous 187 `blocked_evidence` cases, 181 are management and six are
performance. Only 140 have *all* mapped elements absent in scope; the others
include partial positives, conflicts, failed replicas and source exceptions.
The engine already translated scoped absence for ladder primitives. The main
missing link was the untagged `willingness_only` branch fact: with M1 absent,
its unknown value produced `{E0, no matching branch}`, hence `blocked_evidence`.

V2 uses `MGMT_NO_MEANS_IN_SCOPE_E0` when M1 is absent. Original §4.3 defines E0
as effectively absent substantiation, and §4.4 requires named means or concrete
implementation for E1. Applying DEC-127 to that evidence threshold gives E0;
no willingness quote or positive fact is fabricated. This is isolated to v2;
the original rubric files, general evaluator, DEC-85 and round-1 CF6 keep their
old behavior. `missing_elements` still lists absent evidence: it is not itself
a publication block.

Source exceptions ran before the ladder's scoped-state translation. V2 now
consumes scoped absence there too. After three completed replicas, unobserved
comparison/product operands become scoped absence. A superlative header still
needs its literal verified claim quote; product names retain the original E1
cap. Unknown applicability triggers are not fabricated as false. GAP-003 does
not occur in these saved runs: their pinned pack explicitly makes additional
elements report-only. Frozen older packs without that policy retain GAP-003.

The engine fixes yield 144 additional confirmed candidates and 26 additional
decided-but-held candidates whose own quotes remain unverified. The original
29 decided-but-held cases are also all unverified quotes and correctly stay held.
The 17 remaining evidence blocks are conflicts or incomplete/header-inconsistent
replicas. The 34 rule gaps are all unmapped §4.6 safe-harbor paths: forward-looking
28, third-party information 5, emissions estimate 1. Per-claim exact branches,
operands and pinned rubric branches are in `round2-rule-gaps.json`.

Resolved combinations that truly lack a source branch remain GAP-007: goal year
present but metric absent; performance value present but unit absent; and a
product's directly bound ratio/target present with undefined generic-boundary
interaction. Exhaustive 88 element-ladder combinations plus primitive/exception
checks verify these boundaries. The current receipt adds `rule_gap_details` and
`auxiliary_facts` for inspection; old receipts keep their byte structure.

All 76 `no_three_replica_packet` cases are `PRELIMINARY_TAGS_UNRESOLVED`, with no
frozen element packet and zero element replicas (LG E16 25, Kakao 13, LGE 16,
LG E17 22). Claim source is verified for 69 and unverified for seven. The thin
saved export lacks preliminary raw votes, so schema errors cannot be separated
from genuine type disagreement. This is a CF3/CF5 handoff, not an assertion
that three element requests failed; no recovery or source promotion was made.

## Integration and rollback

- I28: combine the registry, hosted allowlist, worker and API changes while retaining
  RB4 streaming and RB1/RB3 safeguards; activate only the new composed policy.
- CF1: inventory recovery can improve linked present evidence; its old exhaustive
  search coverage no longer gates DEC-127 non-observation. Keep SC1 replay intact.
- CF3: retain CF6 packet scope/policy pins after recovery and before model requests.
- CF4: verified source recovery remains upstream; no source thresholds are lowered.
- CF5: preserve three-vote type agreement; element 2/3 is not type 2/3.
- CF7/W20: reconcile expanded-page identity and public confirmation/element display.

Remove the operator pin to stop new CF6 runs. Keep the CF6 reader and policy entry
for already-created checkpoints; historical result bytes remain unchanged. No push,
deployment, server mutation or real OpenAI API call was made for this task.
