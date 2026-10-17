HF5 offline regression input, collected read-only from hosted run
`36133471-26c4-4865-aca6-ec645ed0042a` (850fdbc, 2026-10-17).
`hyundai-preliminary-retry.json` retains one preliminary request, its wire input,
and two saved provider responses: 1024 output tokens (`length`) then 94 (`stop`).
The source request file SHA-256 and immutable analysis policy hash are included.
No credentials or authorization grants are included; tests replace HTTP entirely.
The relation variant reuses this usage shape to exercise the shared accounting path;
the 178-claim workload is synthetic accounting coverage, not a model-quality replay.
