# Linux source readers (FX2)

RB1's 85 unverified claims all stopped at `glyph_geometry_unresolved` before
claim OCR. PDFium and pdfminer origins in the LG input differ by about 0.00156pt;
the existing 0.001pt matcher remains unchanged. EV1 separately withheld 464
otherwise eligible evidence paragraphs because Apple Vision is unavailable.

New Linux runs select `upstage-ocr-page-v4`, an additive reader that preserves
the v3 result and adds an independent SV1 native-string/tight-glyph proof with
the EV1 prose-layout veto. It checks source bytes, tenant, version, graph, page,
box and exact quote, rejects clipped/duplicate glyphs and row/column borrowing,
and retains quantity/unit/decimal/sign spacing and annotation/OCG/XFA guards.
It does not promote whole prose blocks, semantic bindings, tags or grades.

The new literal path reads original PDFium pixels with CPU Tesseract (`kor+eng`,
216dpi, PSM6/OEM1, padding 0/6, one OpenMP thread, 30s timeout, 16M pixel limit).
OCR codepoints are never corrected. New `evidence-source-ocr-v1` uses the exact
EV1 prose/table guards with this raster backend and is pinned for v4 runs.
If the pinned CPU runtime is unavailable, v4 uses the existing brokered v3 OCR
reader; budget, tenant, cache and uncertain-cost protections still apply.
EV1 and SV1's original code/policies are untouched. Receipts record the actual
reader, executable/traineddata/source/code hashes and cropped-image hash.

`pypdfium2==5.13.0` and Pillow already exist in `requirements.txt`/`uv.lock`.
The new OS dependency is Tesseract 5.5.0 and `tessdata_fast` Korean/English.
Debian package versions and traineddata hashes are locked in
`contracts/local_raster_reader_lock.json` and the public Dockerfile.
The OS inventory is `deploy/public/local-raster-sbom.json`; the existing
Python/npm-only SBOM and its strict lock-inventory validator are unchanged.
Tesseract and traineddata are Apache-2.0 (installed Debian copyright records,
upstream repositories `tesseract-ocr/tesseract` and `tesseract-ocr/tessdata_fast`).
The existing PDFium renderer was chosen to retain original geometry/pixels;
Tesseract was chosen after a free 30-claim probe recovered 7 literal quotes.
No Python dependency or lockfile changes were needed. Missing or changed
traineddata/version fails closed to the approved, cost-fenced raster reader.

There is no API/DB column or DTO migration. New snapshots/receipts pin the new
policy; old v1/v2/v3 and EV1 policies/receipts retain their byte hashes and exact
dispatch. Rollback sets `default_linux_reader` back to `upstage-ocr-page-v3` for
future runs; retain the v4/CPU reader and locked runtime for saved v4 receipts.
Changing the installed runtime cannot reinterpret a persisted v4 policy.

Free Linux arm64 RB1 replay: source verified 10→33 of 95, needs original
85→62; all 23 new claim quotes were reviewed against the original PDF crops.
Evidence-only replay added 27 spans over all 21 selected evidence pages.
Remaining claims: 27 clipped/ambiguous glyph quotes and 35 literal OCR mismatches.
No new model tagging, numeric grade promotion, paid calls, publication, push,
deployment or cloud test occurred; original RB1 state/ledger bytes are retained.
The saved-input source gate does not establish full pipeline or model accuracy.
