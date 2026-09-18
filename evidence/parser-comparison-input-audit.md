# Parser-comparison input audit — hanwha sample.pdf PDF_INVALID

Read-only code investigation. Only this file written. No originals, code, credentials, APIs, or source-quality approvals touched.
Date (UTC): 2026-09-12. Coordinator owns integration/fixes.

## 1. Inputs (from `.local/parser-comparison/selection.json`)

| name | original_path | original_sha256 match | pages | subset_sha256 match | sample.pdf bytes |
|---|---|---|---|---|---|
| lgchem | `기업보고서/배터리 에너지/LGChem_Sustainability_Report_2025_KOR.pdf` | (not rechecked here) | 25,97,99 | `5b0038a4…` matches | 267270 |
| hanwha | `기업보고서/배터리 에너지/Hanwha_Aerospace_Sustainability_Report_2025.pdf` | `ddd08581…9610c` matches actual file | 28,90,110 | `aeb791b0…` matches | 535456 |
| sdi | `기업보고서/배터리 에너지/Samsung_SDI_Sustainability_Report_2025_KR_fn.pdf` | (not rechecked here) | 35,115,126 | `ed2a9997…` matches | 401548 |

All three `local-result.json` were produced by `.local/parser-comparison/run_local.py` (builds `SourceArtifact(..., synthetic=False)` + `ParserProfile`, calls `OpenDataLoaderParser(...).parse`).

## 2. Results

- lgchem: `parsed`, 345 blocks, 211 table cells (graph recount; runner incorrectly counted kind `cell`).
- sdi: `parsed`, 843 blocks, 363 table cells (same runner counter correction).
- hanwha: `failed`, reason `PDF_INVALID`, elapsed 0.13 s (fails before any Java/parser subprocess work).

## 3. Exact failure chain (no security weakened to observe it)

1. `run_local.py:10` → `packages/proofops/adapters/parsing/opendataloader.py:283-294 OpenDataLoaderParser.parse` → `verify_quarantined_pdf(...)`.
2. `packages/proofops/application/uploads_security.py:104-155 verify_quarantined_pdf` spawns the resource-limited child (`_inspect`, line 195).
3. Child walks every indexed object. The hanwha subset's page-1 form button (`/T` = `단추 603`, `/FT` = `/Btn`) carries an **`/AA` additional-actions table with a `/D` trigger pointing at a `/Type /Action /S /URI` dict** (object 19,0): `https://www.hanwhaaerospace.com/kor/esg/ehs/introduce.do`.
4. Call-site rule `uploads_security.py:438-446` validates each `/AA` trigger with the strict allowlist `{/Named, /GoTo}` (`reject_dangerous_action_chain`, line 315-321; `/URI` deliberately excluded for auto-fire contexts per comments at lines 277-283 and 382-391). `/URI` ∉ allowlist → line 358-359 raises `UploadRejected("PDF_INVALID")`.
5. Child prints `{"code": "PDF_INVALID"}`; parent re-raises (lines 144-150); `parse` propagates it; `run_local.py:12` records `failed/PDF_INVALID`.

Direct child-inspector reproduction confirms isolation: hanwha subset → `PDF_INVALID`; lgchem/sdi subsets → `verified, 3 pages`; **the hanwha original itself → `PDF_INVALID`** (sha matches selection.json).

## 4. Annotation comparison (why the others pass)

| file | annots | `/AA` triggers |
|---|---|---|
| hanwha sample | 46 × `/Widget` | 33 × `/GoTo` (string dests, accepted as Dests-tree names), 12 × `/Named` (`/PrevPage`/`/NextPage`, accepted), **1 × `/URI` via `/AA` (rejected)** |
| sdi sample | 46 × `/Link` + 9 × `/Widget` | 9 × `/Named` only (accepted); 46 × `/GoTo` via gesture-gated direct `/A` (accepted) |
| lgchem sample | 0 | none |

Single-cause proof: an in-memory clone of the hanwha subset with only that one `/AA /D → /URI` entry removed (written to outside-workspace temp, originals untouched) returns `{"code": "verified", "pages": 3}` from the unmodified child inspector. All 103 content streams decode cleanly; no password, filter, `/EmbeddedFile`, or object-limit issue exists.

## 5. Verdict on the pypdf-subset hypothesis

**The subset's internal navigation is not broken, and pypdf subsetting is not the cause.** The original fails identically; the subset faithfully preserves the document's AcroForm actions. The accepted `/GoTo` string destinations (`(KOR)한화에어로스페이스_웹용.indd:책갈피 …`, InDesign bookmark leftovers) and `/Named` page-turn actions are inert navigation and pass by design. The `/D` trigger is mouse-down, not document-open. The current checker conservatively rejects URI actions under all `/AA` triggers. This finding does not prove automatic execution on opening; the existing security policy remains unchanged.

## 6. Proposals (bounded, security-preserving)

A. **Safe comparable input construction (recommended for parser comparison only):** build a content-only comparison input from the hanwha pages (text + geometry, no AcroForm `/AA`/`/A` actions) held next to, never replacing, the original; record its sha256 + construction method in `selection.json`-style metadata; keep `source_quality: unverified` and do not treat comparison output as verified evidence. Alternatives: compare via the already-extracted `original-28/90/110.txt` text, or re-export pages through a real renderer. None of these imply source-quality approval.
B. **Minimal root fix — reporting only, no allowlist change:** surface the rejecting trigger (annot `/T`, page, `/S`, trigger key) in quarantine failure telemetry so humans can triage without re-running forensics. Do NOT add `/URI` to the `/AA` allowlist and do NOT strip actions inside `verify_quarantined_pdf`/`parse`; silent sanitization would convert a security decision into invisible data loss.
C. **Policy decision (human/security owner, out of scope here):** whether a per-document exception workflow for vendor-URL form buttons should exist at all, who approves it, and how it is audited. Until then hanwha input stays `PDF_INVALID` and any comparison uses construction A.

## 7. Runnable reproduction (read-only; uses repo venv)

```sh
.venv/bin/python -I packages/proofops/application/uploads_security.py .local/parser-comparison/hanwha/sample.pdf '{"max_bytes": 104857600, "max_pages": 300, "max_objects": 100000, "max_decoded_bytes": 75000000, "timeout_seconds": 30, "memory_bytes": 536870912, "cpu_seconds": 20}'
# → {"code": "PDF_INVALID"}  (lgchem/sdi samples → {"code": "verified", "pages": 3})
.venv/bin/python -I packages/proofops/application/uploads_security.py "기업보고서/배터리 에너지/Hanwha_Aerospace_Sustainability_Report_2025.pdf" '{"max_bytes": 104857600, "max_pages": 300, "max_objects": 100000, "max_decoded_bytes": 75000000, "timeout_seconds": 30, "memory_bytes": 536870912, "cpu_seconds": 20}'
# → {"code": "PDF_INVALID"} (proves subset is not the cause)
```

## 8. Left for coordinator / humans

Security-owner ruling on any exception workflow; comparison construction A was performed by the coordinator under the authorized evaluation scope, with a separate derivative, parent hashes and identical rendered pixels on all three pages; source-quality approval remains ungranted; no grade/label/production implication from this audit.
