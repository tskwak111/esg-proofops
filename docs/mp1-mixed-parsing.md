# MP1 opt-in mixed parsing

`--parser mixed-v1 --pages <union> --claim-pages <claims>` on the local pilot,
or `scripts/analyze_report.py --mixed-parser --scope-plan <AS1 JSON>`, freezes
at most ten claim pages and thirty selected pages including claims. Defaults
and old single-mode invocation/config hashes remain unchanged. No public API,
DB schema or dependency migration is introduced.

Claim pages use the existing Upstage standard/enhanced/native-grounding path.
Evidence-only pages retain ODL 2.5.7 candidates (and configured local table
auxiliary candidates). Native and ODL text must each contain >=20 Latin/Hangul
letters without `(cid:` text and with <=1% replacement/NUL characters. This is
only a routing heuristic, never evidence verification or domain approval.
`--mixed-ocr-max-pages N` allows at most N rejected evidence pages to use paid
Upstage; default zero. Shared provider/task ledgers gate dispatch. Budget
rejection removes evidence OCR from the call; those pages remain unreadable.
No-text output remains unreadable even after OCR. There is no full-document
fallback or conversion of unreadable/unknown/conflict to evidence absence.

`page-routing.json` pins the version and page assignment. Manifest and worker
checkpoint retain per-page role, route, parser names/run IDs and confirmation
state; graph blocks retain parser-run/native geometry and, in mixed mode only,
parser names/versions. Manifest/artifact hashes and checkpoint comparison bind
these to the same tenant/version/original source. Replay rejects changed route,
selection, parser identities, provenance or source bytes. Native glyph/render
receipts and table verification remain mandatory for source admission; ODL
headings, unsupported geometry, failed glyph/OCR or unresolved tables remain
unverified candidates needing original confirmation. Retrieval can discover
both sources but does not grant `present` solely from a parser result.

New mixed manifests use fusion v5: parser provenance metadata is excluded from
region/context matching, preserving ODL/auxiliary numeric conflict detection.
Historical v1-v4 fusion behavior stays unchanged, including the first MP1
experimental Samsung v4 artifact. Non-mixed manifests cannot select v5.
Rollback disables new mixed assignments and keeps a reader for stored mixed
artifacts; unsupported older readers reject the new parser profile. Stored
artifacts/revisions/reports must never be rewritten.

DEC-22 hosted integration values are run USD1.00 and day/event USD7.00.
This task does not edit `.local/r108-public` or deploy. In this checkout,
`api/live-report.py:MAX_REQUEST_USD` is 0.123 and `api/_limits.py` defaults
`LIVE_DAILY_LUNA_USD` to 0.50. The latter polls only the OpenRouter key's daily
usage, excludes Upstage costs and provides no atomic event-wide reservation.
Integration must wire total parser+model accounting and day/event reservations
before claiming the requested combined USD7 guard. Constants alone do not do it.
