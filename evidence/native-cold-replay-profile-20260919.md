# Cold v5 replay profile — 2026-09-19

`uv run python -m cProfile` measured two provider-forbidden reads of the saved
Doosan v5 run at code 7ab0d3b (one cold, one warm). Total profiled time was
52.920s. `replay_native_sources` ran twice, consuming 51.892s cumulatively;
114 `_rendered_text` calls consumed 46.963s. The checkpoint computes a native
baseline, then `corroborate_native_visibility` independently computes it again.
The cumulative times overlap and must not be added.

This confirms a concrete remaining cold-read bottleneck. Reuse the existing
successful native-replay cache if that path is changed; retain all source,
tenant, graph, receipt, policy and reader-version checks. Both helpers are pinned
by frozen raster policy: changing them must address old checkpoint readability
explicitly rather than editing stored hashes or weakening version checks.

A separate temporary `swiftc` build of the unchanged native reader took 5.018s.
Three runs per mode on the same original CHRO crop produced identical JSON.
Median script execution was 0.5391s; compiled execution was 0.2611s, including a
slower first compiled invocation in the three-run sample. This is one-image
exploratory evidence, not a system latency estimate. No executable was installed
and the service still uses its original pinned reader. Compiler/runtime identity,
packaging, safe artifact ownership and wider output parity must precede rollout.

The paired JSON preserves exact source/image hashes, measurements and sample
counts. No model calls or budget changes occurred in either profiling experiment.
