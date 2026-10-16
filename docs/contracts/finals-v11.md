# Finals v11 local integration

New runs select `finals-20261013-v11`: Q1 structural/prompt/activity extraction,
E05 HTTP diagnostics, E06 native scope recovery and bounded free OCR discovery.
S18/S14 reductions and E02/C2 confirmed-path changes are excluded. C24 execution
ceilings remain readable; the I10 measured setting is 16 workers/8 RPS.

The existing v1 API and database schema remain unchanged; no migration is needed.
The E05 local HTTP/2 regression requires dev-only `h2==4.4.1` (MIT), with
transitive hpack/hyperframe captured in `uv.lock`. Production transports do not
depend on it; the existing E05 experiment lock uses the same reviewed pin.
Scope discovery remains unverified, tenant/source bound and resource limited.
It cannot admit evidence, confirm reporting periods or synthesize absent values.
Hosted proposals preserve the existing 10 claim/30 union page caps. Existing
stored proposals and revisions are read unchanged, with all historical analysis
pins including v10, Q1 and E05 explicitly retained for publication and replay.

Rollback stops assigning v11 to new runs and pins v10; the v11/E06 reader must
remain available for stored v11 runs/proposals. Never rewrite past artifacts.
I10 authorizes local commits and USD0.80 of API probes under the shared USD35
ledger; it does not authorize push, deployment or live configuration changes.

After the coordinator redeploys, reset `compose.env` values `WORKER_CPUS=6.0`
and `WORKER_MEMORY=12g`. Local Docker cgroup limits do not establish physical
12GiB capacity on a smaller Docker VM or performance on actual EC2.

The reported bdbe050 hosted projection failure was reproduced using the root
checkout's virtual environment with worktree paths added only to PYTHONPATH.
Its isolated parser child (`-I`) imported the older root `proofops` package and
failed to import `proofops.adapters.parsing.windows_isolation`. Install and use
the locked worktree environment (`uv sync --locked`, then `uv run --no-sync
pytest ...`), preserving child isolation and the original completed/projection
expectations. The baseline passes in the correctly installed worktree runtime.
