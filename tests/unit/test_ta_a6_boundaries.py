"""WP-A6 pre-refactor behavior pins; real synthetic PDFs and isolated child execution."""

import json
import subprocess
import sys
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from proofops.application import uploads_security
from proofops.application.uploads_security import (
    HOSTED_NULL_NAVIGATION_PROFILE,
    LocalUploadVault,
    PdfLimits,
    UploadRejected,
    verify_pdf_file,
    verify_quarantined_pdf,
)
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

from tests.acceptance.test_upload_display_security import assert_display_safe
from tests.acceptance.test_upload_security import pdf, source

PROFILES = ("strict-v1", HOSTED_NULL_NAVIGATION_PROFILE, "display-v2")
CASES = ("plain", "javascript", "null_navigation", "owner_only", "password", "compressed")
# Full verdict/security/derived-byte identities captured from 09ebf426.
# Only OS peak-RSS telemetry is excluded; policy limits and original hashes stay pinned.
GOLDENS = {
    ("plain", "strict-v1"): (
        "verified",
        "205646ea68eb7092aea729e6e061f55329acb2df305c4289660c3cec2aa16fba",
    ),
    ("plain", "hosted-null-navigation-hx2-v1"): (
        "verified",
        "b53777aa1ec1b2c73e765d06917c155cded4fd946ed17eba04ee9b00694e51b5",
    ),
    ("plain", "display-v2"): (
        "verified",
        "a2c068c67b32a509745e132352cdc11a239d2b0c706a0469f0f61c04e8c4dd96",
    ),
    ("javascript", "strict-v1"): (
        "PDF_INVALID",
        "fe5c422df2b47685c19f28353b0d1c0a9923e168d7fcd82b59ad0ce7dce082e2",
    ),
    ("javascript", "hosted-null-navigation-hx2-v1"): (
        "PDF_INVALID",
        "fe5c422df2b47685c19f28353b0d1c0a9923e168d7fcd82b59ad0ce7dce082e2",
    ),
    ("javascript", "display-v2"): (
        "verified",
        "e79d6e1f8b26b5460d6d16a588791ab18135dcae4d5d29c14d8628a5fec82e9b",
    ),
    ("null_navigation", "strict-v1"): (
        "PDF_INVALID",
        "fe5c422df2b47685c19f28353b0d1c0a9923e168d7fcd82b59ad0ce7dce082e2",
    ),
    ("null_navigation", "hosted-null-navigation-hx2-v1"): (
        "verified",
        "97b6a457e850f9d0d91bb8f1815d845de225f54e21848852321122bf22fc4311",
    ),
    ("null_navigation", "display-v2"): (
        "verified",
        "3b2316e0f550c82827ad22da11e72b3a3ce0e026703fc4e28a03a583eef39f8d",
    ),
    ("owner_only", "strict-v1"): (
        "verified",
        "0d07beea09aca3c9b1121f286dab4d5d23c372afc98d47c1defecf6b68c5800f",
    ),
    ("owner_only", "hosted-null-navigation-hx2-v1"): (
        "verified",
        "d94c0ed639944f8b204ef31e8c046f849d5ea6417a1dcb1363c6f0e58012bcd6",
    ),
    ("owner_only", "display-v2"): (
        "verified",
        "6361b0aaf857dd8980c66d9bae69c7c6c87c59f8fed8fe2f07f27999d8d5ea10",
    ),
    ("password", "strict-v1"): (
        "PDF_PASSWORD_REQUIRED",
        "e453d34f046b58296dc8b27af42b9a4ef5a5a5001c92fda8e8cc5f534702b09f",
    ),
    ("password", "hosted-null-navigation-hx2-v1"): (
        "PDF_PASSWORD_REQUIRED",
        "e453d34f046b58296dc8b27af42b9a4ef5a5a5001c92fda8e8cc5f534702b09f",
    ),
    ("password", "display-v2"): (
        "PDF_PASSWORD_REQUIRED",
        "e453d34f046b58296dc8b27af42b9a4ef5a5a5001c92fda8e8cc5f534702b09f",
    ),
    ("compressed", "strict-v1"): (
        "UPLOAD_LIMIT_EXCEEDED",
        "0ea001cc7a8e67f3ec5d82782bb4f21221549584ea0af17cc4b2f518963e837d",
    ),
    ("compressed", "hosted-null-navigation-hx2-v1"): (
        "UPLOAD_LIMIT_EXCEEDED",
        "0ea001cc7a8e67f3ec5d82782bb4f21221549584ea0af17cc4b2f518963e837d",
    ),
    ("compressed", "display-v2"): (
        "UPLOAD_LIMIT_EXCEEDED",
        "0ea001cc7a8e67f3ec5d82782bb4f21221549584ea0af17cc4b2f518963e837d",
    ),
}


def case_pdf(case):
    if case == "null_navigation":
        writer = PdfWriter()
        writer.add_blank_page(600, 800)
        writer.root_object[NameObject("/OpenAction")] = DictionaryObject(
            {
                NameObject("/S"): NameObject("/GoTo"),
                NameObject("/D"): ArrayObject([IndirectObject(0, 0, writer), NameObject("/Fit")]),
            }
        )
        buffer = BytesIO()
        writer.write(buffer)
        return buffer.getvalue()
    return pdf(
        action=("/JavaScript", "/JS", "app.alert('never executed')")
        if case == "javascript"
        else None,
        password="" if case == "owner_only" else "secret" if case == "password" else None,
        bomb=case == "compressed",
    )


def normalized_security(metadata):
    return {key: value for key, value in metadata.items() if key != "peak_rss_bytes"}


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("case", CASES)
def test_verdict_original_and_derived_hashes(tmp_path, case, profile):
    data = case_pdf(case)
    item = source(data)
    limits = (
        PdfLimits(policy_profile=profile, max_decoded_bytes=1024)
        if case == "compressed"
        else PdfLimits(policy_profile=profile)
    )
    vault = LocalUploadVault(tmp_path / "vault")
    try:
        result = vault.verify_and_promote(item, limits, tenant_id=item.tenant_id)
    except UploadRejected as error:
        observed = dict(code=str(error), security=normalized_security(error.security_metadata))
        assert not list((tmp_path / "vault").rglob("*.pdf"))
    else:
        observed = dict(
            code="verified",
            pages=result.page_count,
            security=result.security_metadata,
            display_sha256=sha256(result.display_content).hexdigest()
            if result.display_content is not None
            else None,
            analysis_sha256=sha256(result.analysis_content).hexdigest()
            if result.analysis_content is not None
            else None,
        )
        original = vault.original_path(result)
        assert original.read_bytes() == data == result.source.content
        assert observed["security"]["source_sha256"] == sha256(data).hexdigest()
        for suffix, content, key in (
            (".display-v2.pdf", result.display_content, "display_sha256"),
            (".decrypted.pdf", result.analysis_content, "analysis_sha256"),
        ):
            if content is not None:
                assert original.with_suffix(suffix).read_bytes() == content
                assert observed[key] == observed["security"][key]
        if result.display_content is not None:
            assert_display_safe(result.display_content)
    # The strict file path must agree with the memory path without rewriting its input.
    if profile != "display-v2":
        path = tmp_path / "input.pdf"
        path.write_bytes(data)
        metadata = {}
        try:
            pages = verify_pdf_file(
                path,
                limits,
                expected_size=len(data),
                expected_sha256=item.expected_sha256,
                derived_path=tmp_path / "analysis.pdf",
                security_metadata=metadata,
            )
        except UploadRejected as error:
            assert str(error) == observed["code"]
        else:
            assert observed["code"] == "verified" and pages == observed["pages"]
            assert normalized_security(metadata) == observed["security"]
            if observed["analysis_sha256"]:
                assert (
                    sha256((tmp_path / "analysis.pdf").read_bytes()).hexdigest()
                    == observed["analysis_sha256"]
                )
        assert path.read_bytes() == data
    digest = sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert (observed["code"], digest) == GOLDENS[(case, profile)]


@pytest.mark.parametrize("profile", PROFILES)
def test_direct_file_cli_works_under_isolated_python_from_another_directory(tmp_path, profile):
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf())
    output = tmp_path / "derived.pdf"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            uploads_security.__file__,
            str(path),
            json.dumps(asdict(PdfLimits(policy_profile=profile))),
            str(output),
        ],
        cwd=tmp_path,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        check=True,
        timeout=10,
    )
    payload = json.loads(result.stdout)
    assert payload["code"] == "verified" and payload["pages"] == 1
    assert payload["security"]["policy_profile"] == profile
    assert payload["security"]["source_sha256"] == sha256(path.read_bytes()).hexdigest()
    if profile == "display-v2":
        assert sha256(output.read_bytes()).hexdigest() == payload["security"]["display_sha256"]
    else:
        assert not output.exists()


@pytest.mark.parametrize("mode", ["memory", "file"])
@pytest.mark.parametrize(
    "fault", ["timeout", "rss", "signal", "exit", "malformed", "rejected", "verified"]
)
def test_parent_always_reaps_and_keeps_failure_codes(tmp_path, monkeypatch, mode, fault):
    if fault == "rss" and sys.platform != "darwin":
        pytest.skip("The parent RSS watchdog is macOS-specific")
    item = source(pdf())
    path = tmp_path / "source.pdf"
    path.write_bytes(item.content)
    calls = []

    class Process:
        pid = 12345
        returncode = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def communicate(self, *, timeout):
            if fault in ("timeout", "rss"):
                raise subprocess.TimeoutExpired("synthetic-inspector", timeout)
            self.returncode = -9 if fault == "signal" else 2 if fault == "exit" else 0
            if fault == "malformed":
                return b"not JSON", None
            return json.dumps(
                dict(
                    code="PDF_INVALID" if fault == "rejected" else "verified",
                    pages=1,
                    security=dict(source_sha256=item.expected_sha256),
                )
            ).encode(), None

        def poll(self):
            return self.returncode

        def kill(self):
            calls.append("kill")
            self.returncode = -9

        def wait(self):
            calls.append("wait")
            return self.returncode

    def launch(command, **kwargs):
        assert command[:2] == [sys.executable, "-I"]
        assert Path(command[2]).resolve() == Path(uploads_security.__file__).resolve()
        assert kwargs.get("shell", False) is False
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert kwargs["start_new_session"] is True
        assert kwargs["env"] == {"PYTHONDONTWRITEBYTECODE": "1"}
        return Process()

    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=b"999999999" if fault == "rss" else b"1"),
    )
    limits = PdfLimits(timeout_seconds=0.01 if fault == "timeout" else 1)

    def verify():
        if mode == "memory":
            return verify_quarantined_pdf(item, limits, tenant_id=item.tenant_id)
        return verify_pdf_file(
            path, limits, expected_size=len(item.content), expected_sha256=item.expected_sha256
        )

    if fault == "verified":
        verify()
    elif fault == "malformed":
        with pytest.raises(json.JSONDecodeError):
            verify()
    else:
        with pytest.raises(UploadRejected) as rejected:
            verify()
        assert str(rejected.value) == (
            "UPLOAD_LIMIT_EXCEEDED" if fault in ("timeout", "rss", "signal") else "PDF_INVALID"
        )
    assert calls == (["kill", "wait"] if fault in ("timeout", "rss") else ["wait"])
