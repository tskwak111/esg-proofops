# TASK-001 multipart dependency

Reviewed 2026-09-09 KST. The existing upload ticket contract returns a POST URL
and form fields. The installed Starlette form API needs `python-multipart` to
parse that transport; the standard library has no maintained multipart parser.
`python-multipart==0.0.32` is pinned for `proofops-api`, without optional extras.

Primary sources: [PyPI version metadata](https://pypi.org/project/python-multipart/0.0.32/)
and [upstream releases](https://github.com/Kludex/python-multipart/releases).
License: Apache-2.0; Python >=3.10; no runtime dependencies.
The upstream [filename-write advisory](https://github.com/Kludex/python-multipart/security/advisories/GHSA-wp53-j4wj-2cfg)
affects versions through 0.0.21 and is fixed from 0.0.22. This application uses
server-generated object paths and does not configure filename-based disk writes.

- Wheel SHA-256: `ff6d3f776f16878c894e52e107296ffc890e913c611b1a4ec6c44e2821fe2e23`.
- Source SHA-256: `be54b7f3fa167bb83e4fcd936b887b708f4e57fe75911c02aebf53efaf8d938e`.
- `uv add --package proofops-api 'python-multipart==0.0.32'`: exit 0,
  65 packages resolved; API manifest and lock updated.
- Actual temporary FastAPI/TestClient POST using `request.form(max_files=1,
  max_fields=1)` read the expected synthetic file bytes. Sending two files
  returned HTTP 400. No network service or customer document was used.
- `uv run --no-sync python scripts/check_licenses.py --generate-sbom --env ENABLE_LEGACY_PYMUPDF=false`:
  exit 0; refreshed SBOM and supply-chain gate passed.
- Exported locked requirements and ran
  `uv run --no-sync pip-audit --strict --no-deps --disable-pip -r /tmp/proofops-audit.txt`:
  exit 0, no known vulnerabilities found.

These checks establish dependency selection and parser integration only. Upload
byte limits, ticket binding, quarantine verification and immutable promotion are
verified separately in `evidence/task-001.md`.
