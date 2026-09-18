# Report section candidate study — 2026-09-09

User-approved scope: E narrative supplies claim candidates; E narrative plus **all**
ESG DATA and APPENDIX supplies evidence-search candidates. A candidate search page
does not establish that any particular claim has evidence there. Existing citation,
binding, numeric/year and source-quality checks still apply.

Implementation: `evaluation/report_sections.py`. Local JSON only; no production
API/DB changes, no new dependencies, no model calls. It uses PDF outline paths,
semantic named destinations, then a conservative large-heading fallback. Native
navigation, physical pages, source hash, parser versions, policy hash and map hash
are recorded. Heading rectangles are explicitly pdfplumber top-left point coordinates,
not approved canonical SourceRefs. Unknown/conflict and other candidate pages remain
explicit. JSON output uses exclusive creation; earlier maps are not overwritten.
Rollback is to stop using this evaluation command; existing graph/revision artifacts
and full claim discovery remain unchanged.

## Five real PDFs

Ranges are physical, 1-based and include chapter dividers. These are checked
development cases, **not independent gold or measured precision/recall**.

| Report | Automatic E candidates | Additional evidence candidates | Observed limitation |
|---|---|---|---|
| LG Chem, 119p | 16–49 | DATA 97–110; APPENDIX 111–119 | Named destinations retain all four E subtopics and data/glossary children; front pages 1–2 unknown |
| Hanwha Aerospace, 114p | 21–35 | FACTBOOK 87–100; APPENDIX 101–114 | TCFD 21–26 is included before Environmental 27–35; 11 front/overview pages unknown |
| Samsung SDI, 139p | 31–48 | APPENDIX 111–139 | Opaque destination IDs; large chapter headings work; data lives inside Appendix; 1–3 unknown |
| Samsung Electronics, 87p | 10–33 | Facts & Figures 61–74; APPENDIX 75–87 | Initial detector missed Planet/Facts & Figures; aliases added after page inspection; 1–2 and 5–9 unknown |
| KB Financial KSSB, 112p | none | none | All 112 pages unknown: large-heading fallback cannot recover small topic headings / Investor headlines |

Exact PDF hashes, parser versions and final map hashes are in `section-map-results.json`.
Full local map artifacts: `.local/section-map-study/reviewed/{lgchem,hanwha,sdi,sec,kb}.json`.
Old trial artifacts are preserved in sibling directories. The summary hashes refer
to the full map payload with `map_sha256` removed; they do not hash the shortened summary.

Coordinator rendered and inspected boundary contact sheets using installed pypdfium2:
LG 16/49/50/78/97/111; Hanwha 21/26/27/35/36/87/101; SDI 31/48/49/111;
Samsung Electronics 10/34/61/75; KB 17/18/64/65/89. Text/navigation were separately read.
These checks validate sampled headings and layout transitions, not every cell or page.
Chapter divider text stays eligible for later claim/non-claim extraction. EOF ranges
may include blank/image back pages; no blank-text page is approved as readable evidence.

Worker text review finds KB climate p17–64 and Appendix p89–111, with inline Scope/PCAF
tables. It remains a review observation rather than an automatically accepted scope.
Next bounded improvement: resolve TOC-link destinations and small section headings
for that case, preserving ambiguity, then connect reviewed scopes to existing batches.
Neither the new map nor worker notes change source_quality to verified.

## Orca provenance and review decisions

Run `run_81088e9c6905`:

- `task_117f88e12fe4`, report review: Kiro dispatch `ctx_3957e172bd40` failed at
  `dispatch_input/agent_prompt_stalled`; terminal reported Session ended. This is
  not evidence of exhausted credits. Released/closed, then retried using OpenCode
  `opencode/muse-spark-1.3-contributor-free`, dispatch `ctx_4c2d3a15355f` completed.
- `task_f39cc6fa82de`, code review: same OpenCode model, dispatch `ctx_c3ff3b1b813a`
  completed. Both custom terminals were retained by worker-release as external,
  then explicitly closed because this coordinator had created them for these tasks.
- Report review initially put LG Governance at p80; coordinator directly checked
  p77–80 and corrected the boundary to p78. TEXT-OBSERVED means text/navigation
  observation, never canonical verification. Missing glossary headings remain unknown.
- Code review fixes: preserve unfamiliar semantic destination/large-heading anchors
  as unknown boundaries; expose other pages explicitly; record coordinate metadata
  and parser versions; hash thresholds and document map-hash self-exclusion.
- Rejected review suggestion to remove S/G/financial ESG DATA pages: it conflicts
  with the user's explicit whole-DATA search scope. No evidence binding is granted.
- Added real generated-PDF destination regression alongside conflict/data hierarchy
  checks. Unknown-boundary and alternative-title assertions were observed failing
  before their fixes; both regression tests then passed.

## Validation

- `uv run --no-sync ruff check .`: passed.
- `uv run --no-sync ruff format --check .`: 224 files formatted.
- Workspace mypy including evaluation: passed, 142 source files.
- `uv build --all-packages --out-dir .local/section-map-study/dist`: all four wheels
  and source distributions built.
- `uv run --no-sync python scripts/verify_architecture.py`: passed.
- Supply-chain/secret gate initially failed because the tracked SBOM held an old
  uv.lock hash. `scripts/check_licenses.py --generate-sbom --env ENABLE_LEGACY_PYMUPDF=false`
  refreshed that one hash and passed. No dependency/lock version changed.
- `uv run --no-sync python scripts/validate_package.py`: 706/706 passed;
  documentation/contracts only, not application tests.
- `PROOFOPS_TEST_JAVA=/opt/homebrew/opt/openjdk@21/bin/java uv run --no-sync pytest -q`:
  **1420 passed, 2 existing Starlette/AnyIO deprecation warnings, 128.96s**. Includes
  unit, integration, acceptance, contract, local E2E and security suites. Log:
  `.local/section-map-study/pytest.log`.
- Product Upstage, vision, AWS, deployment, live product E2E: **not_run** in this study.
  No new product inference charge; cumulative $10 budget ledger was not reset or altered.

Known ceiling: ranges end at the next detected anchor. Undetected boundaries can
overextend them; dispersed environmental content outside chapter titles may be missed.
Consequently every map remains `candidate_only`, `coverage=unvalidated`, and cannot
silently replace full discovery or filter production evidence search.
