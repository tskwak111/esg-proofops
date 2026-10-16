# CF6 finals default candidate: DEC-125 + DEC-127

CF6 combines two-of-three verified element agreement and scoped non-observation
in one opt-in policy. It implements the user's DEC-127 decision: after three
completed tagging replicas, an element still unknown because evidence was not
found or linked becomes `absent_in_scope` inside the selected analysis pages.
This is a system result, not an exhaustive-search or full-document absence claim.
The existing Python rule engine determines the grade; LLMs only extract and tag.

## Policy registration

`CF6_POLICY` in `packages/proofops/application/analysis_profile.py` extends the
v27 policy with `integration_profile=cf6_finals_default_candidate_dec127_v1` and
`cf6_confirmation=CF6_CONFIRMATION_POLICY`. There is one new registered policy.

- Full policy SHA: `3aae437cb6468b3822f90efc19307abb487d114af46c515f1f4a78efb744314b`
- Element/scope policy SHA: `38faac3a1694fe070a178a14f29e55b60b8f760ad0418af2ecf0a9a6517b9479`
- Three-vote diagnostic reference: `f628ffcdbc051cfad6f83ee3f54221ed283661d879d51695506cc76c991b565d`
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
   incomplete/failed replicas or TIME_BUDGET remain held. Existing exception,
   estimate and retag safety holds remain. GAP-005 preserves a decided E-grade
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

| Report | Before confirmed/provisional/held | After confirmed/provisional/held | After E0/E1/E2/E3 |
|---|---:|---:|---:|
| E16 LG Chem | 0/122/93 | 123/0/92 | 4/107/12/0 |
| E16 Kakao | 0/63/81 | 81/0/63 | 19/58/4/0 |
| E16 LG Electronics | 0/36/105 | 57/0/84 | 22/31/4/0 |
| E17 LG Chem | 0/120/91 | 124/0/87 | 6/105/13/0 |

R20 has 43 newly confirmable claims among 174 audited claims. The audit establishes
**at least 25 lower-than-source-supported grades** (LG 4, Kakao 11, LGE 10).
The audit supplies minimum-grade evidence, not exhaustive gold grades. Sixteen
other confirmations have no demonstrated grade increase, one is a mixed claim
without a single true-grade label, and one (Kakao index 71) has a known audit
conflict that was not captured in the saved votes. The latter remains a semantic
risk, not proof that the policy detects every conflict in the document.

Three fresh tool-free Codex CLI replicas, concurrency at most two, tested 38 R10/R11
contexts. Literal quotes plus the Python engine still produce **two false E3
candidates among 26 negative cases** under both thresholds; 12/12 positive controls
reach E3. DEC-127 additionally decides two negative contexts at E2; the old corpus's
“hold” labels are not silently relabeled as correct. Simulated public confirmations
remain zero because production freshness/source/binding gates are not bypassed.
R16/R16b PDF replay keeps all 11 hidden/clipped cases unverified, with six visible
controls and three Kakao p55 spans verified. These checks do not establish model
accuracy or zero-error production behavior.

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
