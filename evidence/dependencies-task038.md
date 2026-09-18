# TASK-038 parser dependency

Reviewed 2026-09-09 KST. Real PDF structure, page count and encryption inspection
need a PDF parser; stdlib and the installed application dependencies do not supply
one. `pypdf==6.18.0` is pinned in the optional `proofops[parsing]` extra, enabled
by `proofops-worker`. Domain code still imports only stdlib and Domain modules.

Official [PyPI metadata](https://pypi.org/pypi/pypdf/6.18.0/json) identifies
BSD-3-Clause, Python >=3.9 and no base transitive dependencies on Python 3.12.
The [official error-handling documentation](https://pypdf.readthedocs.io/en/stable/user/suppress-warnings.html)
describes strict parsing and explicit exception handling. No crypto, OCR or image
extras are installed. OpenDataLoader remains a separate TASK-003 dependency.

- `uv add --package proofops --optional parsing 'pypdf==6.18.0'` and
  `uv add --package proofops-worker 'proofops[parsing]'`: exit 0; 63 packages resolved.
- A real in-memory blank PDF was written with `PdfWriter`, then read with
  `PdfReader(..., strict=True)`; page count and MediaBox assertions passed.
- `uv run --no-sync python scripts/check_licenses.py --generate-sbom --env ENABLE_LEGACY_PYMUPDF=false`:
  exit 0; lock inventory and SBOM refreshed, gate passed.
- Fresh locked requirements exported, followed by
  `uv run --no-sync pip-audit --strict --no-deps --disable-pip -r /tmp/proofops-audit.txt`:
  exit 0; no known vulnerabilities found.

This dependency check does not establish upload safety. Resource isolation,
rejection behavior and actual parser tests belong to TASK-038. No customer PDF,
external link, embedded action or AWS operation was processed.
