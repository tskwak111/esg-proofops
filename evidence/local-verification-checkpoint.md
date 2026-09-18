# Local implementation checkpoint — 2026-09-09 KST

This is a local synthetic checkpoint, not a staging or production release.
The active report/accessibility implementation was excluded from the broad
acceptance run and still needs its own acceptance and final integration.

| Executed command | Result |
| --- | --- |
| `uv run --no-sync pytest tests/unit tests/contracts tests/integration tests/security -q --tb=short` | 225 passed, 2 upstream warnings, 49.81 s |
| `uv run --no-sync pytest tests/acceptance --ignore=tests/acceptance/test_report.py --ignore=tests/acceptance/test_accessibility.py -q --tb=short` | 1032 passed, 2 upstream warnings, 25.36 s |
| `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest tests/acceptance/test_parsing.py::test_actual_opendataloader_text_and_tables_keep_physical_pages_and_artifacts tests/integration/test_local_parser_runner.py tests/acceptance/test_supply_chain.py -q --tb=short` | 64 passed, 2 upstream warnings, 8.77 s |
| `uv run --no-sync ruff check tests/acceptance/test_parsing.py tests/integration/test_run_lifecycle.py` | passed |

CI inspection found that the parser and run fixtures hard-coded a macOS Java
path, and the step named acceptance/integration executed only acceptance tests.
An explicit Java selection assertion first failed, then passed after both
fixtures used the same `PROOFOPS_TEST_JAVA` override. Actual parser integration
was rerun with that override. CI now includes integration/security and checks
the preinstalled Java 21 executable; no extra action or dependency was added.
The official [Ubuntu 24.04 runner inventory](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md#java)
lists `JAVA_HOME_21_X64` separately from its Java 17 default. The remote CI job
itself has not run; no push was made.

At this checkpoint 39 of 45 canonical API operations have matching mounted
operation IDs. Export, comparison and deletion-request operations remain in
progress. Customer PDFs, independent real gold evaluation, product-model calls,
AWS mutations and deployed recovery/performance checks remain `not_run`.
