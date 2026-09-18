# OIDC cryptography dependencies

Reviewed 2026-09-09 KST. Signature verification requires maintained cryptographic
primitives absent from the existing runtime. `PyJWT[crypto]==2.13.0` is pinned in
`proofops[auth]`, enabled by `proofops-api`; Domain stays independent of these imports.
No bespoke JWT or RSA implementation was added.

Primary sources: [PyJWT release](https://pypi.org/project/PyJWT/2.13.0/),
[PyJWT verification documentation](https://pyjwt.readthedocs.io/en/stable/usage.html),
and [cryptography licensing](https://cryptography.io/en/latest/faq/#what-is-the-license).
Installed distribution metadata and the lock identify:

| Package | Version | License |
|---|---|---|
| PyJWT | 2.13.0 | MIT |
| cryptography | 50.0.1 | Apache-2.0 OR BSD-3-Clause |
| cffi | 2.1.1 | MIT-0 |
| pycparser | 3.0 | BSD-3-Clause |

Source SHA-256: PyJWT `41571c89ca91598c79e8ef18a2d07367d4810fbbd6f637794879baf1b7703423`;
cryptography `5dd9bda1c12b4162f6ff568eeb5e0ff956c28d14406e875cfe8a63a2d414ff20`.
All resolved wheel/source hashes are retained in `uv.lock`.

- Both `uv add` operations exited 0; 69 packages resolved.
- Generated an ephemeral 2048-bit RSA key, signed a synthetic RS256 JWT, verified
  its signature/issuer/audience, and confirmed a wrong audience raises
  `InvalidAudienceError`. No key or token was printed or retained.
- `uv run --no-sync python scripts/check_licenses.py --generate-sbom --env ENABLE_LEGACY_PYMUPDF=false`:
  exit 0; refreshed SBOM, gate passed.
- Exported locked requirements, then ran
  `uv run --no-sync pip-audit --strict --no-deps --disable-pip -r /tmp/proofops-audit.txt`:
  exit 0, no known vulnerabilities found.

Actual OIDC lifecycle checks belong to `evidence/task-037-oidc.md`. Cognito,
KMS-backed refresh storage and account MFA policy have not been exercised.
