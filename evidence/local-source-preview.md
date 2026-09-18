# Local source page preview

`GET /local/sources/{run_id}/{source_id}?ticket=...&preview=page` reuses the
existing private ticket. The ticket remains bound to tenant, user, run, source,
document version, parse manifest, original SHA-256, and five-minute expiry.
The server selects the physical page from the immutable graph candidate; the
client cannot supply a page number. Omitting `preview=page` keeps the existing
byte-identical inline PDF response.

The preview process writes only `source.pdf`, `request.json`, `output.png`, and
`result.json` in a request-local temporary directory. It uses the existing
`OpenDataLoaderParser._execute` process-group watchdog with a 15 second wall
timeout, 512 MiB descendant RSS ceiling, 16 MiB output ceiling, 100 MiB input
ceiling, CPU/file-size child limits, a stripped environment, and PDFium's
forms/annotations disabled. The image has at most 2,000 pixels per side and
4,000,000 pixels total; this is process/resource containment, not a claim of
OS network isolation.

The PNG response has `Cache-Control: no-store, private`, `X-Content-Type-
Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Page-Width-Pt`,
`X-Page-Height-Pt`, and `X-Source-Highlight`. Highlight is `allowed` only for
a located, verified winner with matching canonical geometry and no open parse
conflict; otherwise it is `unavailable` while the page remains readable for
human review. The local synthetic CropBox fixture was rendered through all
four rotations, checked at the canonical red-rectangle pixel, and visually
inspected as a rotated, cropped raster with no outside-CropBox blue rectangle.

Focused verification:

```text
uv run pytest tests/integration/test_source_api.py -q
4 passed
```
