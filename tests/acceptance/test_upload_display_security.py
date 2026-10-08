"""Display-v2 accepts inertly parsed originals and delivers only stripped derivatives."""

import json
import socket
import subprocess
import sys
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from proofops.application.uploads_security import (
    LocalUploadVault,
    PdfLimits,
    UploadRejected,
    verify_quarantined_pdf,
)
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject

from tests.acceptance.test_upload import TENANT, setup_upload
from tests.acceptance.test_upload_security import pdf, source


def write(writer):
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def assert_display_safe(content):
    reader = PdfReader(BytesIO(content), strict=True)
    assert not reader.is_encrypted
    forbidden = {
        "/AA",
        "/OpenAction",
        "/JS",
        "/JavaScript",
        "/Launch",
        "/SubmitForm",
        "/EmbeddedFiles",
        "/EmbeddedFile",
        "/XFA",
        "/RichMedia",
        "/RichMediaContent",
        "/GoToR",
        "/GoToE",
        "/ImportData",
        "/URI",
        "/AcroForm",
        "/Annots",
        "/EF",
    }
    from pypdf.generic import IndirectObject

    pending = [
        reader.get_object(IndirectObject(n, g, reader))
        for g, entries in reader.xref.items()
        for n in entries
        if n and g != 65535
    ]
    seen = set()
    while pending:
        value = pending.pop()
        if isinstance(value, IndirectObject):
            value = value.get_object()
        if not isinstance(value, DictionaryObject | ArrayObject) or id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, DictionaryObject):
            assert not forbidden.intersection(value.keys())
            assert str(value.get("/Type")) not in {"/Action", "/EmbeddedFile"}
            assert str(value.get("/S")) not in {
                "/JavaScript",
                "/Launch",
                "/SubmitForm",
                "/URI",
                "/Named",
                "/GoToR",
            }
            pending.extend(value.values())
        else:
            pending.extend(value)


@pytest.mark.parametrize("trigger", ["open", "catalog-aa", "page-aa", "annotation", "orphan"])
@pytest.mark.parametrize(
    "subtype",
    [
        "/JavaScript",
        "/Launch",
        "/GoToR",
        "/GoToE",
        "/SubmitForm",
        "/ImportData",
        "/Named",
        "/URI",
        "/UnknownAction",
    ],
)
def test_all_active_action_bearers_are_stripped_without_execution(tmp_path, trigger, subtype):
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    marker = tmp_path / "executed"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(0.02)
        target = f"http://127.0.0.1:{listener.getsockname()[1]}/private"
        action = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Action"),
                NameObject("/S"): NameObject(subtype),
                NameObject("/JS"): TextStringObject(f"touch {marker}"),
                NameObject("/URI"): TextStringObject(target),
                NameObject("/F"): TextStringObject(str(marker)),
                NameObject("/N"): NameObject("/Print"),
            }
        )
        action[NameObject("/Next")] = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/S"): NameObject("/JavaScript"),
                    NameObject("/JS"): TextStringObject("hidden_payload()"),
                }
            )
        )
        ref = writer._add_object(action)
        if trigger == "open":
            writer.root_object[NameObject("/OpenAction")] = ref
        elif trigger in {"catalog-aa", "page-aa"}:
            owner = writer.root_object if trigger == "catalog-aa" else writer.pages[0]
            owner[NameObject("/AA")] = DictionaryObject({NameObject("/O"): ref})
        elif trigger == "annotation":
            writer.pages[0][NameObject("/Annots")] = ArrayObject(
                [
                    writer._add_object(
                        DictionaryObject(
                            {NameObject("/Type"): NameObject("/Annot"), NameObject("/A"): ref}
                        )
                    )
                ]
            )
        original = write(writer)
        item = source(original)
        vault = LocalUploadVault(tmp_path / "vault")
        verified = vault.verify_and_promote(item, PdfLimits.display(), tenant_id=item.tenant_id)
        assert vault.original_path(verified).read_bytes() == original
        assert verified.source.expected_sha256 == sha256(original).hexdigest()
        assert verified.security_metadata["source_sha256"] == sha256(original).hexdigest()
        assert verified.security_metadata["derived"] is True
        assert (
            verified.security_metadata["display_sha256"]
            == sha256(verified.display_content).hexdigest()
        )
        assert_display_safe(verified.display_content)
        with pytest.raises(TimeoutError):
            listener.accept()
    assert not marker.exists()


@pytest.mark.parametrize(
    "key", ["/EmbeddedFiles", "/EmbeddedFile", "/XFA", "/RichMedia", "/JavaScript"]
)
def test_embedded_and_form_payloads_cannot_survive_in_display(tmp_path, key):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    writer.add_attachment("secret.exe", b"active_attachment_payload")
    writer.root_object[NameObject("/AcroForm")] = DictionaryObject(
        {
            NameObject("/XFA"): TextStringObject("<xml>external payload</xml>"),
        }
    )
    page[NameObject(key)] = TextStringObject("active_payload")
    item = source(write(writer))
    result = verify_quarantined_pdf(item, PdfLimits.display(), tenant_id=item.tenant_id)
    assert_display_safe(result.display_content)
    assert b"active_attachment_payload" not in result.display_content
    assert b"active_payload" not in result.display_content
    assert b"external payload" not in result.display_content


def test_empty_user_password_is_accepted_and_permissions_recorded():
    item = source(pdf(password=""))
    result = verify_quarantined_pdf(item, PdfLimits.display(), tenant_id=item.tenant_id)
    assert result.source.content == item.content
    assert result.security_metadata["encrypted"] is True
    assert type(result.security_metadata["permissions"]) is int
    assert_display_safe(result.display_content)


@pytest.mark.parametrize(
    "data,limits,code",
    [
        (pdf(password="secret"), PdfLimits.display(), "PDF_PASSWORD_REQUIRED"),
        (pdf(bomb=True), PdfLimits.display(), "UPLOAD_LIMIT_EXCEEDED"),
        (pdf(bomb=True), PdfLimits.display(max_decoded_bytes=1024), "UPLOAD_LIMIT_EXCEEDED"),
        (pdf(), PdfLimits.display(max_bytes=100), "UPLOAD_LIMIT_EXCEEDED"),
        (pdf(pages=2), PdfLimits.display(max_pages=1), "UPLOAD_LIMIT_EXCEEDED"),
        (pdf(), PdfLimits.display(max_objects=1), "UPLOAD_LIMIT_EXCEEDED"),
        (pdf(), PdfLimits.display(memory_bytes=1), "UPLOAD_LIMIT_EXCEEDED"),
        (pdf(), PdfLimits.display(timeout_seconds=0.000001), "UPLOAD_LIMIT_EXCEEDED"),
    ],
)
def test_new_profile_keeps_resource_and_password_guards(tmp_path, data, limits, code):
    item = source(data)
    with pytest.raises(UploadRejected, match=code):
        LocalUploadVault(tmp_path).verify_and_promote(item, limits, tenant_id=item.tenant_id)
    assert not list(tmp_path.rglob("*.pdf"))


@pytest.mark.parametrize("profile", ["strict-v1", "display-v2", "historical-unpinned"])
def test_pending_upload_policy_is_pinned_across_service_reconfiguration(tmp_path, profile):
    data = pdf(action=("/JavaScript", "/JS", "not_executed()"))
    initial = PdfLimits.display() if profile == "display-v2" else PdfLimits()
    service, doc, data, body = setup_upload(tmp_path, data=data, limits=initial)
    ticket = service.initiate_upload(TENANT, doc["document_id"], body, str(uuid4()))
    if profile == "historical-unpinned":
        item = service._get(TENANT, "upload", ticket["upload_id"])
        item.pop("upload_security_limits")
        service._put(TENANT, "upload", ticket["upload_id"], item, update=True)
    service.receive_content(TENANT, ticket["upload_id"], data, "application/pdf")
    service.limits = PdfLimits() if profile == "display-v2" else PdfLimits.display()
    complete = dict(sha256=body["sha256"], size_bytes=len(data))
    if profile != "display-v2":
        with pytest.raises(UploadRejected, match="PDF_INVALID"):
            service.complete_upload(TENANT, ticket["upload_id"], complete, str(uuid4()))
        return
    key = str(uuid4())
    result = service.complete_upload(TENANT, ticket["upload_id"], complete, key)
    snapshot = service.version_snapshot(TENANT, result["version_id"])
    assert snapshot["upload_security"]["policy_profile"] == "display-v2"
    service.limits = PdfLimits(max_bytes=1)
    assert service.complete_upload(TENANT, ticket["upload_id"], complete, key) == result
    assert service.read_original(TENANT, result["version_id"]) == data
    display, metadata = service.read_display(TENANT, result["version_id"])
    assert_display_safe(display)
    assert metadata == snapshot["upload_security"]
    assert service.version_snapshot(TENANT, result["version_id"]) == snapshot
    with pytest.raises(UploadRejected, match="NOT_FOUND"):
        service.read_display("00000000-0000-4000-8000-000000000002", result["version_id"])
    target = service.root / "original" / TENANT / f'{result["version_id"]}.display-v2.pdf'
    target.chmod(0o600)
    target.write_bytes(b"tampered")
    with pytest.raises(UploadRejected, match="UPLOAD_INTEGRITY_MISMATCH"):
        service.read_display(TENANT, result["version_id"])


def test_legacy_display_cache_preserves_version_and_audit(tmp_path, monkeypatch):
    service, doc, data, body = setup_upload(tmp_path, limits=PdfLimits())
    put = service._put

    def historical_put(tenant, kind, identifier, item, **kwargs):
        if kind == "version":
            item = dict(item)
            item.pop("upload_security", None)
        return put(tenant, kind, identifier, item, **kwargs)

    monkeypatch.setattr(service, "_put", historical_put)
    ticket = service.initiate_upload(TENANT, doc["document_id"], body, str(uuid4()))
    service.receive_content(TENANT, ticket["upload_id"], data, "application/pdf")
    result = service.complete_upload(
        TENANT, ticket["upload_id"], dict(sha256=body["sha256"], size_bytes=len(data)), str(uuid4())
    )
    # Emulate an already-persisted pre-profile version.
    snapshot = service.version_snapshot(TENANT, result["version_id"])
    assert "upload_security" not in snapshot
    audit = service.read_upload_audit(TENANT, doc["document_id"])
    first = service.read_display(TENANT, result["version_id"])
    assert service.read_display(TENANT, result["version_id"]) == first
    assert first[1]["source_sha256"] == body["sha256"]
    assert_display_safe(first[0])
    assert service.version_snapshot(TENANT, result["version_id"]) == snapshot
    assert service.read_upload_audit(TENANT, doc["document_id"]) == audit
    assert service.read_original(TENANT, result["version_id"]) == data


def test_pdfium_repair_is_followed_by_complete_sanitization(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf(action=("/JavaScript", "/JS", "evil()")))
    from proofops.application import uploads_security

    # Force the syntax-repair branch in its isolated process, with real PDFium save.
    code = """
import json, runpy, sys
from pathlib import Path
from pypdf.errors import PdfReadError
module = runpy.run_path(sys.argv[1])
g = module['_inspect_display'].__globals__
original = g['_display_reader']
calls = 0
def retry(*args, **kwargs):
    global calls
    calls += 1
    if calls <= 2: raise PdfReadError('synthetic syntax failure')
    return original(*args, **kwargs)
g['_display_reader'] = retry
result = g['_inspect_display'](sys.argv[2], g['PdfLimits'].display(), Path(sys.argv[3]))
print(json.dumps(result))
"""
    output = tmp_path / "display.pdf"
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, uploads_security.__file__, str(path), str(output)],
        capture_output=True,
        timeout=30,
        check=True,
    )
    metadata = json.loads(result.stdout)
    assert metadata["parser"] == "pdfium-repair+pypdf-tolerant"
    assert len(metadata["parser_retry_errors"]) == 2
    assert_display_safe(output.read_bytes())
    assert not output.with_suffix(".repaired.pdf").exists()


def test_unknown_profiles_and_invalid_ratio_are_rejected():
    for kwargs in ({"policy_profile": "unknown"}, {"max_expansion_ratio": 0}):
        with pytest.raises(ValueError):
            PdfLimits(**kwargs)
