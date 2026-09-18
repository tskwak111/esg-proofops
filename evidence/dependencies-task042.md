# TASK-042 audit tooling dependency

Reviewed 2026-09-09 KST. `pip-audit==2.10.1` is a development dependency for
the vulnerability check required by docs/18. Neither stdlib nor the installed
tools supplied the advisory database audit. This adds no application runtime
dependency and does not change Domain imports.

Version and Python compatibility were read from the official
[PyPI metadata](https://pypi.org/pypi/pip-audit/2.10.1/json). The project's
[licensing statement](https://pypi.org/project/pip-audit/#licensing) identifies
Apache-2.0, with ISC-licensed reused examples. Installed metadata for the 24 new
packages was checked: MIT, Apache-2.0, BSD-2-Clause or PSF licenses; exact
transitive versions and artifact hashes are recorded in `uv.lock`.

`uv add --dev 'pip-audit==2.10.1'` resolved 61 packages and installed 24.
A TOML comparison with the preceding committed lock confirmed that no existing
package version changed. `uv run --no-sync pip-audit --version` returned 2.10.1.
Actual vulnerability findings belong to the TASK-042 report; installing the tool
does not establish a clean audit.

The [official CLI documentation](https://pypi.org/project/pip-audit/#usage)
distinguishes installed-environment and requirements-file scans. `--locked .`
currently supports `pylock.*.toml`, so CI must not assume it audits `uv.lock`.
No ignore-vulnerability list or successful fallback is introduced.

## Vulnerability remediation

The actual locked-requirements audit failed with nine advisories affecting
pytest 8.4.2 and Starlette 0.48.0. The coordinator updated FastAPI to 0.141.1
(MIT), Starlette to 1.6.0 (BSD-3-Clause), and pytest to 9.1.1 (MIT).
FastAPI's additional dependency annotated-doc 0.0.5 is MIT. Installed metadata
confirms all four support Python 3.12; exact versions and hashes are locked.

Reviewed the official [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/#01370),
[Starlette release notes](https://starlette.dev/release-notes/), and
[pytest changelog](https://docs.pytest.org/en/stable/changelog.html).
FastAPI's router-internals change does not affect the current API, which uses
public router registration. No removed Starlette lifecycle APIs are used.
The existing pytest INI-style TOML configuration remains supported.

- `uv add --package proofops-api 'fastapi==0.141.1' --upgrade-package starlette`
  and `uv add --dev 'pytest>=9.1.1,<10'`: exit 0, 62 packages resolved.
- `uv run --no-sync pytest tests/acceptance/test_auth.py tests/contracts/test_package_contracts.py tests/unit/test_legacy_characterization.py -q`:
  exit 0, 62 passed. TestClient emits existing/deprecation warnings for httpx
  and AnyIO; no new client dependency is needed for working tests.
- `uv export --locked --no-emit-workspace --format requirements-txt --output-file /tmp/proofops-audit.txt`,
  then `uv run --no-sync pip-audit --strict --no-deps --disable-pip -r /tmp/proofops-audit.txt`:
  exit 0, no known vulnerabilities found. No advisory was ignored.

Rollback is the paired manifest/lock change; reverting to the vulnerable versions
would fail the release audit. These local checks do not establish deployed safety.
