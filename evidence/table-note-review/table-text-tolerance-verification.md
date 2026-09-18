# Explicit table text tolerance verification — 2026-09-14

Problem: the POSCO Future M 2025 report, physical p139, contains a total label with
raised `2)`. Default pdfplumber extraction emits `2)\n합계`; explicit y tolerance 4
emits `합계2)`. Changing text-flow alone did not resolve it. Table geometry remains
unchanged. This correction is an opt-in parser profile, not a service-grade ownership
or completeness claim.

Original SHA256: `65070d88297d4faf631a9545e6aa49b56ccae71531dda0248f69a3887ab779a8`.
Actual OpenDataLoader + auxiliary subprocess parsed a new immutable invocation
`14e2b3a6-0191-4ed1-8a11-3e6e7ddefdb8` and successfully reloaded it. Native cell
`p139-t2-r0-c0` contains `합계2)`. Graph SHA256:
`8abb9051cdb10b9d7069194b461f8cda5bcee40366ffd166ae82d7727a216d0a`.
Private artifact: `.local/note-review-integration/table-text-tolerance-real/result.json`.
Zero model calls; existing source review and published graph unchanged.

TDD: 10 tests initially failed on missing profile capability; after implementation,
corrected two test-fixture assertions (actual NativeSource field and literal spacing).
Focused parser suite: 37 passed, 2 dependency deprecation warnings. Synthetic original
PDF demonstrates default reversed lines and explicitly tuned order through the actual
subprocess, rejects mismatched replay settings, and preserves default configuration hash.
Additional custom-profile HTTP upload/run/worker replay and zero/fractional acceptance
checks run separately after the full-suite command started; production code unchanged.

Orca independent read-only review: task `task_f018c27836cb`, dispatch
`ctx_cf58bde500d0`. Identified full-invocation hash compatibility in addition to config
hashes; all parser and checkpoint serialization sites now share invocation_snapshot.
Worker released and delivery acknowledged. No dependency added.

Final checks:
- `uv run pytest -q`: 2116 passed, 2 dependency deprecation warnings, 148.05s.
  Log: `.local/note-review-integration/table-text-tolerance-full.log`.
- Additional selected tests: 12 passed, 26 deselected, 2 warnings, 3.54s;
  includes both default and custom-profile HTTP/worker/reopen paths.
- Ruff lint and format: passed, 294 files. Mypy: 173 source files passed.
- Architecture checker: passed. All four workspace distributions built.
- Installed-wheel replay: 20 existing actual report checkpoints reopened with
  identical published graph hashes; zero model calls. Log:
  `.local/note-review-integration/table-text-tolerance-wheel-replay.json`.
- Documentation validator: 790 checks passed, 50 API operations; not an accuracy test.
- Browser UI, live model, AWS and deployment: not_run. No grading or ownership
  acceptance was changed. Full-service readiness remains unproven.
