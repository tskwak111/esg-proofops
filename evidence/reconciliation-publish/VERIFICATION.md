# Developer B publication verification — 2026-09-21

This change delivers C1–C4 rules, original-source verification, blocked outcomes
for unresolved policy, DART collection/preparation, CLI tools and a local
authenticated review API/SQLite/React workflow. C5 remains disabled and the
existing G/P/M grading rules are unchanged.

## Local validation

Windows, Python 3.12, Java 21; Korean fixtures require `PYTHONUTF8=1`.

- `scripts/verify_reconciliation.py`: all 15 release gates passed, including
  677 tests and eight synthetic CLI scenarios. This run preceded the final
  Unicode download regression test and a platform-guard refactor.
- Actual Java parsing and local tagging: 32 passed; the three previous Windows
  failures are resolved by pre-execution Job Object containment and a host-correct
  child environment.
- Final Windows parser containment tests: 27 passed. Final HTTP tests: 38 passed,
  including a Korean document filename download and original-byte digest check.
- Existing unit/contract/staging checks: 185 passed, seven optional legacy skips.
- Final Linux-target mypy: 205 source files passed.
- Exact staged-source export: Ruff lint and formatting passed; supply-chain
  license/secret gate passed; documentation/contract validator passed 871 checks.
  The local DART key was checked against staged blobs without printing it.
- Earlier delivery checks passed web typecheck/build, composed API/SQLite browser
  flow and 16 isolated UI boundary checks. Browser evidence is local; this does
  not claim a deployed production test.

The initial whole-workspace formatting failure concerned an unpublished local
ZIP-building script. The published tree passes formatting independently. The
initial Linux-target type errors in Windows-only initialization were fixed and
rechecked. A focused HTTP run without UTF-8 mode failed during fixture loading;
the documented UTF-8 invocation passed. Failed/intermediate logs remain local.

## Review boundaries

Claude Opus handled the Windows parser lane under Orca supervision. Master
review found and corrected suspended-child cleanup, failure injection, child-only
resource limits, post-exit output enforcement and Linux-target typing issues.
Windows uses a strict configured memory cap; a kernel-denied allocation can
surface as `PARSER_FAILED`, not necessarily `PARSER_MEMORY_LIMIT`. This is process
resource containment, not a complete filesystem/network sandbox.

An authenticated Samsung FY2024 DART collection and original hashes were checked
locally. The real-company draft remains blocked pending human source review and
policy approval. C3 thresholds/account mapping, open domain decisions, held-out
accuracy evaluation and production deployment are not completed by this PR.

CI runs the offline release checks and actual Java parser regression on Ubuntu,
Windows and macOS 15 (Apple Silicon and Intel). Java 21 is installed for the
runner's architecture. The PR checks and linked Actions runs are the authoritative
remote result for each commit; this document records local evidence only.

No API key, local environment file, raw company report, generated delivery ZIP,
or historical audit directory belongs to this publication.
