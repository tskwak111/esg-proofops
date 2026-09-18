# TASK-003 auxiliary parser dependencies

Reviewed 2026-09-09 KST. The fixed parser plan requires a separate table candidate
source. The installed OpenDataLoader primary parser and pypdf structural verifier
do not replace that cross-check. `pdfplumber==0.11.10` is pinned in the existing
`proofops[parsing]` extra used by the worker.

Primary sources: [pdfplumber](https://github.com/jsvine/pdfplumber),
[pinned release](https://pypi.org/project/pdfplumber/0.11.10/), and
[pypdfium2 licensing](https://pypdfium2.readthedocs.io/en/stable/readme.html#licensing).
The resolved packages are pdfplumber 0.11.10 (MIT), pdfminer.six 20260107 (MIT),
Pillow 12.3.0 (MIT-CMU), and pypdfium2 5.13.0 (Apache-2.0/BSD-3-Clause plus bundled
dependency notices). Existing cryptography 50.0.1 is reused. Locked artifacts
retain their exact hashes.

`evidence/parser_dependency_notices.json` records the actual installed macOS arm64
license/notice files and their hashes. PDFium binary redistribution must retain its
bundled notices; documentation/examples also carry CC-BY-4.0. No upstream example
or customer PDF was copied. The inventory is specific to these installed wheels;
it is not a scan of a deployed Linux image or the PDFium native vulnerability set.

- `uv add --package proofops --optional parsing 'pdfplumber==0.11.10'`: exit 0;
  73 packages resolved.
- An initial handcrafted PDF used a direct content stream and pdfplumber found
  no pages. Correcting the synthetic fixture to use indirect font/content objects
  produced one page in both pypdf and pdfplumber. Real table extraction returned
  exactly `[["Metric", "Value"], ["Scope1", "123.4"]]` and the assertion passed.
  No parser implementation was patched or test result fabricated.
- `uv run --no-sync python scripts/check_licenses.py --generate-sbom --env ENABLE_LEGACY_PYMUPDF=false`:
  exit 0; refreshed SBOM, supply-chain gate passed.
- Fresh locked requirements exported, then
  `uv run --no-sync pip-audit --strict --no-deps --disable-pip -r /tmp/proofops-audit.txt`:
  exit 0, no known vulnerabilities found.

Runtime packaging also declares the already-installed httpx 0.28.1 under
`proofops[auth]`, and pypdf 6.18.0 under `proofops[verification]`, enabled by the
API. This makes API-only installs include their actual runtime requirements without
requiring Java, OpenDataLoader or table extraction dependencies. These declarations
add no new resolved package versions. Full parsing behavior is verified separately
by TASK-003; model-based table vision remains not_run without approved bindings.
