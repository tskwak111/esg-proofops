# PDF gesture compatibility and Upstage response preservation — 2026-09-13

Baseline: f5467e7. Orca run_0f610cda0697. This checkpoint improves ingestion
compatibility and failure diagnosis; it does not activate real worker/API tagging.

## Reproduction and fix

Hyundai Steel's original SHA256 is
`6e865aa68ddc11b7c1e4768b90626e906e79444f3d47cffdc72f7047e6348ea9`.
The prior indexed-action scan found144 Named Print actions, but did not establish
which events invoked them. A direct-gesture-only Print fix passed8 regression
cases yet the actual file still failed. Exception-frame inspection then found
`/Type /Annot`, `/Subtype /Widget`, `/AA /D` Print; after recognizing that event,
a second rejection identified URI under the same Widget click event.

The shared validator now distinguishes Widget mouse-down/up from automatic events.
Existing gesture action validation applies to Widget AA D/U, and Named Print is
allowed only in gesture context. PDF 32000-1 Table194 defines D/U as mouse button
press/release inside the annotation's active area. Source:
[Adobe-hosted PDF 32000-1](https://opensource.adobe.com/dc-acrobat-sdk-docs/standards/pdfstandards/pdf/PDF32000_2008.pdf).

OpenAction, document AA, Widget focus/page-open, malformed actions, JavaScript and
other forbidden subtypes remain rejected. Each shared reference is rechecked in
its trigger context, with bounded Next-chain traversal unchanged. No PDF action
was executed or source PDF rewritten. API/DB schemas are unchanged; rollback
limitations are recorded in docs/11_AUTH_SECURITY.md.

Failing-first checks reproduced direct Print rejection, then Widget D/U Print
rejection, then Widget D/U URI rejection. The final36-case matrix covers both
subtypes, both xref orders, direct and Widget gestures, automatic events, shared
AA dictionaries and dangerous Next chains. Existing security tests were preserved.

## Real reports and model call

All original hashes were checked before/after parsing. Each new parse has fresh
manifest/document identity; earlier failed attempts and artifacts remain intact.
The pages are physical PDF pages and were previously selected using report TOCs.

| Report | Selected E body/data/appendix pages | Blocks | Quality counts |
|---|---|---:|---|
| Hyundai Steel |17,113,138|316|274 unverified,42 unlocated|
| Samsung Life |23,24,121,138|1219|1085 unverified,80 conflicted,54 unlocated|
| KEPCO |75,76,205,259|424|419 unverified,2 conflicted,3 unlocated|

Samsung Life/KEPCO were replayed during the intermediate Widget-Print fix; Hyundai
Steel succeeded after the final Widget-URI fix. This is selected-page ingestion,
not a full-report parsing benchmark, table accuracy score or independent gold set.
No source became verified. No grade/label was produced.
Observed wall times were149.42s/80.05s/76.12s respectively during concurrent test
activity; these are diagnostic timings, not an isolated throughput benchmark.

One new actual solar-pro4 extraction used a226-code-point Hyundai Steel paragraph
on p17. It returned3 nonoverlapping claim spans exactly matching the parsed text.
This checks quote preservation, not human-gold semantic accuracy or exhaustiveness.
The actual provider model was solar-pro4-260806.

## Provider response preservation and budget

The sole cumulative budget authority remains `.local/upstage/budget.sqlite3`.
New decoded HTTP-200 JSON is archived before validation in the private adjacent
`budget.sqlite3.responses` directory. Hash-based filenames cannot traverse paths;
create-only0600 files under0700 directories preserve failed completion evidence.
File contents are flushed/fsynced. No headers or credentials are copied. Unknown
reservations and transport-stop/retry behavior are unchanged. This is decoded JSON,
not an HTTP-byte archive; invalid JSON, HTTP errors and oversized bodies remain
unarchived. No old unknown reservation was reconstructed, reset or refunded.

For the real new call, archived provider JSON matched the settled receipt's
response_sha256 and file permissions were0600. Fake-HTTP/real-SQLite tests also
covered truncated responses, restart/duplicate preservation and archive failure.

Before:1236 calls,6 unsettled,USD7.2388412850 committed/reserved.
After:1237 calls,6 unsettled,USD7.2391452150 committed/reserved.
New settled cost:USD0.0003039300. User budget:USD10; no other monetary ledger.

## Review and validation

Kiro's first task could not start: monthly request limit reached (reset10/01).
The assignment was abandoned and its terminal closed. Antigravity's prior failed
readiness circuit was not retried. OpenCode Muse Spark1.3 contributor-free took
the retry and completed a read-only45-test baseline review. Its report supported
the direct-gesture distinction but lacked actual trigger-location evidence; the
coordinator subsequently established Widget D/U semantics and tested the final
change. That later change is not presented as independently reviewed by Muse.
Muse was released and both task terminals were closed; no Codex worker fallback was used.

Logs/private artifacts: `.local/pdf-print-retest/`; reviewer report:
`.local/pdf-print-review.md`. Final command results are recorded below.

Still open: real worker/API tagging composition, model-specific token accounting,
source-quality validation, table attribution accuracy and independent human gold.
The official [Pro3 tokenizer](https://huggingface.co/upstage/solar-pro3-tokenizer)
was found, but it was not assumed to be a validated Pro4 tokenizer. No synthetic
counter or fixture authorization was promoted to a real runtime. Browser/staging/
deployment tests for this checkpoint remain not_run.

Validation results:
- `uv run pytest -q`:1693 passed,2 existing dependency warnings in1350.51s
  (`.local/pdf-print-retest/pytest.log`).
  This run collected before the final URI matrix expansion; the final changed
  security module is also validated separately below.
- `uv run pytest tests/acceptance/test_upload_security.py -q`:81 passed in75.05s
  on the final code (including36 new gesture/automatic/shared-chain cases).
- `uv run pytest tests/integration/test_upstage_probe.py tests/integration/test_upstage_tagging.py tests/integration/test_upstage_extraction.py -q`:
 67 passed in11.35s; transport/ledger, extraction and tagging composition regressions.
- `uv run ruff check apps packages tests evaluation`:passed.
- `uv run mypy packages/proofops apps/api/src apps/worker/src apps/agent/src evaluation tests/load infra/cdk/staging_gate.py`:
 155 files passed,3 existing untyped-body notes.
- `uv run python scripts/verify_architecture.py`:passed.
- `uv build --all-packages --out-dir .local/pdf-print-retest/dist-final`:
 four packages built, both sdists and wheels.
- `uv run python scripts/validate_package.py`:743/743 documentation/contract checks
 passed; this is not an app/model benchmark.
