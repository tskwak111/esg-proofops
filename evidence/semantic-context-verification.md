# Paired real-report context experiment — 2026-09-10

Reused two LG Chem p24 source targets: the baseline-level emissions goal and the
reported energy-project savings. For each, compared its original whole sentence
with a shorter contiguous original span. Source IDs, normalized offsets, exact
SourceRefs, document version, manifest and PDF hash remain pinned. The shorter
spans are diagnostic inputs, not new approved atomic-claim revisions.

| Target | Whole length | Short length | Whole metric | Short metric |
|---|---:|---:|---|---|
| Baseline-level goal | 154 characters | 109 characters | null | null |
| Project savings | 87 characters | 50 characters | null | null |

Four fresh single-claim calls used the same SEMANTIC_SYSTEM, solar-pro3,
temperature 0, JSON mode on, and 2,048 maximum output tokens. Each returned valid
schema/source-checkable JSON but all entity/metric/boundary fields were null.
Schema validation passing is not semantic extraction success. The explicit
metric was not extracted in either context condition; no source or binding was
approved and no numerical comparison or grade was calculated.

Shortening removed surrounding wording, not only token count, so this is a
context-ablation experiment rather than an isolated causal test of length.
One call per condition cannot measure variance. The result supports only that
this particular truncation did not remedy these two observed omissions.

Cases/results: `evidence/semantic-context-cases.json` and
`evidence/semantic-context-results.json`. Four source-bound packets and call
receipts preserve request/model/prompt/rule/packet/wire identities and replica.
Full requests are under `.local/semantic-context/`; runner is `run.py` there.
The results are development evidence, not human-adjudicated corpus gold.

Four paired calls added $0.000467610, reaching 97 calls and $2.039438795
committed/reserved of $10 (two earlier unsettled calls included), before the
separate few-shot follow-up below. No automatic retries, Bedrock/AWS calls or
credential output.

## Verification

`PYTHONPATH=. uv run --no-sync python evidence/semantic-context-replay.py` passed:
four distinct pinned requests, shared prompt/rule hashes, source-parent containment,
packet/wire integrity and exact source quotes for non-null accepted outputs.
All-null semantic output is reported explicitly above, not hidden by the replay.
Ruff lint/format passed for the replay. No application code changed, so application
build, full E2E and cloud checks were not rerun for these evaluation artifacts.

## Separate few-shot follow-up

A fifth call kept the performance-short packet/wire identical, adding two existing
synthetic development examples (capability cases q1/q5) to the system prompt.
Those examples are not corpus gold or current-document labels. Model, temperature,
JSON mode and output limit stayed the same. The original four-condition results
and their prompts remain unchanged.

This response proposed metric `약 3만 톤의 온실가스`, with entity/boundary null.
The selected phrase exists exactly within the original claim and contains the
metric mention, but includes approximation, quantity and unit. This is a partial
recovery of a metric-containing source span, not precise metric normalization or
an accepted evidence binding. One observed prompt variant does not establish a
reliable improvement; source quality and bindings remain unresolved.

`evidence/semantic-context-fewshot.json` preserves the response, prompt/example/
packet/wire/model hashes and budget. The shared validator rule hash was attached
in a separate post-call validation receipt, explicitly marked as recorded after
the call; the original `.local/semantic-context/fewshot/result.json` is unchanged.
The offline replay also checks identical input hashes, changed prompt hash, exact
returned phrase and undetermined binding for this follow-up.

The fifth call added $0.000124740; all five added $0.000592350. Final shared ledger:
98 calls, $2.039563535 committed/reserved of $10 including two earlier unsettled
calls. Next: validate precise metric-span selection on several explicit examples
before considering production integration. No live-model accuracy claim or
automatic numeric comparison follows from this result.

Final `uv run --no-sync python scripts/validate_package.py`: 720/720 documentation
and contract checks passed; this is not an application or model accuracy test.
