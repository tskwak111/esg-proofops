# TASK-002 evidence — 페이지·좌표·원문 위치 (P0)

Date: 2026-09-09. No commit (coordinator owns Git). No AWS/model calls, no
GitHub push, no secrets. Only owned files touched:
`packages/proofops/domain/documents.py`,
`packages/proofops/application/ingest/geometry.py` (+ its `__init__.py`),
`tests/acceptance/test_provenance.py`, and `packages/proofops/domain/__init__.py`
(local re-export list, not a shared contract/DTO). No edits to
contracts/, config/, docs/, or other workers' files
(`domain/regulatory.py`, `application/authorization.py`,
`application/supply_chain.py`, `apps/api/**`, etc. were read-only or untouched).

## Contract implemented

`canonicalize_source_ref :: NativeSource + PageGeometry -> SourceRef`
(docs/20_TASK_BREAKDOWN.md TASK-002; docs/07_API_SPEC.md;
docs/27_PARSING_AND_PROVENANCE.md §3-4; docs/02_REQUIREMENTS.md FR-002;
docs/21_ACCEPTANCE_CRITERIA.md AT-002).

- `domain/documents.py` (pure, stdlib-only): `PageGeometry` (width_pt,
  height_pt, rotation ∈ {0,90,180,270}, crop_box) with
  `to_canonical_affine()`; `NativeSource` (document/parse/parser identifiers,
  physical_page [1-based, required], printed_page_label [independent, free
  string], native_bbox [nullable, never zero], native_coordinate_system
  [restricted to a supported set], raw_text, raw char offsets).
- `application/ingest/geometry.py`: `canonicalize_source_ref` projects a
  `NativeSource` + `PageGeometry` into the existing, unmodified
  `proofops.domain.values.SourceRef` (reused per coordinator guidance,
  not duplicated). Helpers: `affine_apply`, `invert_affine`,
  `canonical_bbox_from_native`, NFC-normalized-offset-to-raw-offset mapping
  with fail-closed re-verification.

Per coordinator steering, this keeps the richer docs/27 provenance fields
(native_bbox, native_coordinate_system, affine) internal to
`NativeSource`/`PageGeometry` and projects only the fixed `SourceRef` fields
outward -- no new shared/public DTO surface, no contracts/ changes.

## Key correctness decisions (post-review fixes)

1. **Canonical bbox**: rotation- and CropBox-aware affine
   (translate crop origin -> rotate clockwise -> flip to top-left display
   origin), verified against an *independent* reference calculation (not
   the implementation under test) for all four rotations with CropBox
   origin shifted away from (0,0) and width/height swapped for 90/270
   (`TestRotationAndCropBoxRoundTrip.test_canonical_bbox_matches_independent_reference`).
   A separate round-trip test (invert the same matrix) checks the inverse
   independently.
2. **PageGeometry validation**: rejects bool `rotation` (Python
   `bool` is an `int` subclass), and rejects `width_pt`/`height_pt` that are
   inconsistent with `crop_box` once rotation is applied (a caller passing
   the unrotated size for a 90/270 page is a silent-corruption bug, now
   rejected at construction).
3. **native_coordinate_system allowlist**: only
   `pdf_bottom_left_points` is accepted; any other value is rejected rather
   than having the bottom-left affine silently applied to coordinates it
   was never derived for (docs/27 §2 warns OpenDataLoader's
   `[left,bottom,right,top]` must not be mixed with other native systems).
4. **Out-of-bounds canonical bbox rejected**: a canonical bbox
   falling outside `[0,width_pt] x [0,height_pt]` (beyond float tolerance)
   raises rather than being silently accepted or clipped.
5. **UUID fields**: `document_version_id`/`parse_manifest_id`/
   `parser_run_id` are validated with the existing canonical-UUID checker
   from `domain/values.py` (`_require_uuid`), not a new "non-empty string"
   check.
6. **NFC/NFD offset mapping (FX-LOC-003)**: normalized (composed)
   offsets, as an LLM/UI would report them, are mapped back to raw
   code-point offsets by finding a raw split index `i` such that
   `NFC(raw[:i]) == normalized[:n]` **and** `NFC(raw[i:]) == normalized[n:]`
   -- verified against Hangul NFD (jamo carry Unicode combining class 0, so
   a combining-class heuristic is insufficient and was replaced) and
   Latin combining-mark (`café` -> `cafe´`) cases. `canonicalize_source_ref`
   re-verifies `NFC(raw_text[start:end]) == requested normalized substring`
   and fails closed (raises) rather than citing a mis-mapped span.
7. **Missing geometry**: `native_bbox=None` always yields
   `SourceRef.bbox=None` and `location_quality="unlocated"`, never a zero
   bbox (FX-LOC-001).
8. **raw_text_sha256`** is always computed over the raw (pre-normalization)
   bytes so provenance hashing is never silently rewritten by normalization.

## Test file

`tests/acceptance/test_provenance.py`, 21 tests, all real assertions (no
mocks, no weakened contracts):

- Baseline unrotated/uncropped formula check against docs/27's documented
  `[left, H-top, right, H-bottom]`.
- 4 rotation cases x 2 assertions (explicit independent-reference canonical
  bbox + affine round trip), CropBox origin shifted, width/height correctly
  swapped for 90/270.
- `PageGeometry` rejects width/height inconsistent with rotated crop, bool
  rotation.
- `NativeSource` rejects unsupported `native_coordinate_system`.
- Out-of-bounds canonical bbox rejected.
- Korean NFD round trip (quote + hash), NFD offset-not-conflated-with-raw
  case, Latin combining-mark case.
- Missing geometry -> `None` bbox + `unlocated` (never zero bbox).
- physical_page vs printed_page_label independence; physical_page < 1
  rejected.
- Inverted / non-finite native bbox rejected.

## Commands run (exact, this session)

```
uv run --no-sync pytest tests/acceptance/test_provenance.py -q
```
Result: initially failed collection (`ModuleNotFoundError:
proofops.application.ingest`, no implementation yet) -> after implementation,
1 failure (NFD offset mapping bug caught by the Hangul test) -> fixed ->
**21 passed**.

```
uv run --no-sync ruff check packages/proofops/domain/documents.py \
  packages/proofops/application/ingest/geometry.py \
  packages/proofops/application/ingest/__init__.py \
  tests/acceptance/test_provenance.py
```
Result: **All checks passed** (after auto-fixing one import-sort issue and
removing one unused local variable).

```
uv run --no-sync mypy packages/proofops
```
Result: **Success: no issues found in 27 source files.**

```
uv run --no-sync python scripts/verify_architecture.py
```
Result: **all checks passed**, including
`PASS purity:packages/proofops/domain/documents.py` (stdlib-only, no banned
imports) and all composition/port/contract checks.

```
uv run --no-sync pytest -q
```
Result: **275 passed** (full suite, including concurrently-developed files
from other in-flight workers in this batch: `test_regulatory.py`,
`test_auth.py`, `test_supply_chain.py`, `test_legacy_characterization.py`).
One transient failure was observed mid-session in
`tests/acceptance/test_regulatory.py::test_resolver_reads_the_hash_verified_rulepack_timeline_snapshot`
(`AttributeError: 'RulePackSnapshot' object has no attribute 'is_approved'`)
while another worker's `domain/regulatory.py` (not an owned TASK-002 file)
was mid-edit; it passed on the final run after that worker's concurrent
changes landed. Not caused by, or fixed by, any TASK-002 file.

## Limitations / not_run

- No real PDF/OpenDataLoader parsing was run; `NativeSource`/`PageGeometry`
  are pure domain values fed by fixtures/tests, not by TASK-003's parser
  adapter (not yet implemented; that is TASK-003's owned scope).
- No live model or AWS calls; none were needed for this task.
- API wiring for `GET /v1/runs/{run_id}/sources/{source_id}` is out of
  scope for this task's owned files (storage/route wiring belongs to later
  tasks per docs/20); this task delivers the pure canonicalization function
  the route will call.
- `docs/22_EDGE_CASES.md` FX-LOC-001/002/003 are covered by dedicated tests;
  the remaining FX-* fixtures (graph fusion, tables, numeric, etc.) belong
  to other tasks (TASK-003/004/005) and are out of scope here.
