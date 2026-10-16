# Finals v26 integration

`finals-20261016-v26` is the new unpinned `finals-unattended-v2` default.
Its SHA256 is `ac9eb6466f3bdbc2653b140507a2ae2447ce008b4ec1dbb4de78cfb4e7d746fe`.
Explicit old pins, policy dictionaries, readers and immutable revisions remain readable.

Promotion is **not recommended**: the required automatic Kakao fresh execution
hit the unchanged 1800-second analysis timeout during tagging. The subsequent
observer also hit its expired session (HTTP 401), so final Kakao counters are
unavailable. Preserve the fixed gate limits and rerun after resolving these
failures; passing unit tests or smoke cannot substitute for the fresh gate.

V26 is V25 plus `fxh_finals_fresh_v1`, OPS2 provider fallback and adaptive page
rendering. V25's V1/V2/V3 semantic policies, frozen domain rules and DEC-85/92/93
remain unchanged. CH1 is merged as an opt-in evaluation tool with no default wiring.
QT3 is excluded: its report records new false-present cases and a failed fresh gate.

Ordinary model roles share a run-local OPS2 failover state: billing inactivity and
network failures switch immediately; three consecutive actual HTTP 429/403 errors
switch to OpenRouter `openai/gpt-6-luna`. Provider/model receipts and independent
replicas remain mandatory. Uncertain OpenAI costs stay reserved; fallback calls use
the same hosted run/day/event broker and a separate immutable adapter ledger.
Run status distinguishes failures recovered by a schema-valid fallback for the
same logical request from unresolved failures. Raw scheduler errors, deferred
requests and original reservations remain intact; unrelated failures still block.
The existing OpenRouter request/output/price bounds remain enforced, including
the 16 KiB wire limit. Large fallback requests can therefore remain blocked;
activation does not establish full-report provider quality or capacity equivalence.

QT1 candidate routing now sends known invalid table-grid errors to the existing
pinned source-local input-failure handler. Such a table stays unknown before any
paid model dispatch; healthy sources continue. Identity/replay errors still abort,
and neither table validation nor historical policy dictionaries are relaxed.

C3 keeps a separate OpenAI factory, its approved LG original/tenant/rulepack scope,
the shared physical-attempt scheduler, and authenticated three-current-response
contract. A fallback receipt never
authorizes C3 confirmation. Generated unknown tags in offline gates cannot confirm.

Live configuration for v26 requires the existing `openrouter_key_file` in addition
to OpenAI and Upstage paths. Validate those files before assigning the new pin.
Do not print key values. No operational configuration is changed by this integration.

W18 remains a read-time `?w18=true` API option. Its new fields add exact source
coordinates and failure reasons; default result fields and stored snapshots remain
unchanged. Adaptive rendering reads the persisted run policy, including composed
v26, rather than applying today's default to older runs.

OPS2 adds the idempotent `ops2_provider_observations` table. Existing tables and
schema version remain intact; older code can ignore the added table. Rollback
new assignments to v24/server commit `6c6241f` after drain/idle. Preserve v26
artifacts on a compatible reader; never restore money ledgers to erase charges.

Required local release evidence is in `lab/perf/I26`: the exact arm64 image's
fresh LG and automatic Kakao executions, hosted smoke, W18 source checks, frozen
DL4/holdout scoring, R10/R11/R16/R16b/SC1 guards, static checks and the serialized
full pytest run. Simulated transport evidence measures execution and guards,
not fresh semantic accuracy or live provider speed.
