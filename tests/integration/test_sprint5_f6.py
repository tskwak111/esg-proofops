"""Offline REVIEW-UP regressions, including actual pre-F5 persisted results."""

import json
import subprocess
import sys
import types
import zlib
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pypdfium2 as pdfium
import pytest
from proofops.application.uploads_security import PdfLimits, UploadRejected, verify_quarantined_pdf
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject as A,
)
from pypdf.generic import (
    DecodedStreamObject,
)
from pypdf.generic import (
    DictionaryObject as D,
)
from pypdf.generic import (
    NameObject as N,
)
from pypdf.generic import (
    TextStringObject as T,
)

from tests.acceptance.test_upload import TENANT, setup_upload
from tests.acceptance.test_upload_display_security import assert_display_safe, write
from tests.acceptance.test_upload_security import _hide_action, _widget_with_trigger, source

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def raw_pdf(payload, broken):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
        payload,
    ]
    if broken:
        objects.append(b"BROKEN_OBJECT")
    data, offsets = b"%PDF-1.7\n", []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return (
        data
        + (
            f"trailer\n<< /Root 1 0 R /Size {len(objects)+1} >>\nstartxref\n{xref}\n%%EOF\n"
        ).encode()
    )


@pytest.mark.parametrize("broken", [False, True])
@pytest.mark.parametrize("kind", ["external", "expansion"])
def test_repair_cannot_approve_uninspected_original_objects(kind, broken):
    encoded = zlib.compress(b" " * 2_000_000)
    payload = (
        b"<< /Length 0 /F (file:///DO_NOT_OPEN_REVIEW_ONLY) >>\nstream\n\nendstream"
        if kind == "external"
        else f"<< /Length {len(encoded)} /Filter /FlateDecode >>\nstream\n".encode()
        + encoded
        + b"\nendstream"
    )
    item = source(raw_pdf(payload, broken))
    with pytest.raises(UploadRejected) as error:
        verify_quarantined_pdf(item, PdfLimits.display(), tenant_id=item.tenant_id)
    assert str(error.value) == (
        "PDF_INVALID" if broken or kind == "external" else "UPLOAD_LIMIT_EXCEEDED"
    )


def layer_pdf(mode):
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    group = writer._add_object(D({N("/Type"): N("/OCG"), N("/Name"): T("layer")}))
    default = D({N("/BaseState"): N("/ON")})
    if mode in {"off", "ocmd"}:
        default[N("/OFF")] = A([group])
    elif mode == "on":
        default[N("/BaseState")] = N("/OFF")
        default[N("/ON")] = A([group])
    else:
        group.get_object()[N("/Usage")] = D(
            {
                N("/View"): D({N("/ViewState"): N("/OFF")}),
                N("/Print"): D({N("/PrintState"): N("/ON")}),
            }
        )
        default[N("/AS")] = A(
            [D({N("/Event"): N("/View"), N("/Category"): A([N("/View")]), N("/OCGs"): A([group])})]
        )
    writer.root_object[N("/OCProperties")] = D({N("/OCGs"): A([group]), N("/D"): default})
    membership = (
        writer._add_object(
            D({N("/Type"): N("/OCMD"), N("/OCGs"): A([group]), N("/P"): N("/AnyOn")})
        )
        if mode == "ocmd"
        else group
    )
    page[N("/Resources")] = D({N("/Properties"): D({N("/Hidden"): membership})})
    stream = DecodedStreamObject()
    stream.set_data(b"q 1 1 1 rg 0 0 100 100 re f /OC /Hidden BDC 1 0 0 rg 0 0 100 100 re f EMC Q")
    page[N("/Contents")] = writer._add_object(stream)
    return write(writer)


def pixels(content, *, printing=False):
    with pdfium.PdfDocument(content) as document:
        page = document[0]
        bitmap = page.render(
            scale=1,
            draw_annots=False,
            may_draw_forms=False,
            extra_flags=pdfium.raw.FPDF_PRINTING if printing else 0,
        )
        image = bitmap.to_pil().convert("RGB")
        result = image.tobytes(), image.getpixel((50, 50))
        image.close()
        bitmap.close()
        page.close()
        return result


@pytest.mark.parametrize("mode", ["off", "on", "ocmd", "view-usage"])
def test_display_preserves_default_optional_content_pixels(mode):
    item = source(layer_pdf(mode))
    verified = verify_quarantined_pdf(item, PdfLimits.display(), tenant_id=item.tenant_id)
    assert_display_safe(verified.display_content)
    original = pixels(item.content)
    assert original[1] == ((255, 0, 0) if mode == "on" else (255, 255, 255))
    assert pixels(verified.display_content) == original
    assert pixels(verified.display_content, printing=True) == pixels(item.content, printing=True)


@pytest.mark.parametrize("trigger", ["/E", "/X"])
def test_strict_v1_hover_matches_historical_inspector(tmp_path, trigger):
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    _widget_with_trigger(writer, trigger, _hide_action())
    item = source(write(writer))
    path = tmp_path / "hover.pdf"
    path.write_bytes(item.content)
    limits = asdict(PdfLimits())
    for key in ("policy_profile", "max_expansion_ratio"):
        limits.pop(key)
    baseline = subprocess.run(
        [
            sys.executable,
            "-I",
            str(FIXTURES / "upload_security_strict_v1.txt"),
            str(path),
            json.dumps(limits),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    assert json.loads(baseline.stdout)["code"] == "PDF_INVALID"
    with pytest.raises(UploadRejected, match="PDF_INVALID"):
        verify_quarantined_pdf(item, PdfLimits(), tenant_id=item.tenant_id)
    assert_display_safe(
        verify_quarantined_pdf(item, PdfLimits.display(), tenant_id=item.tenant_id).display_content
    )


@pytest.mark.parametrize("historical", [False, True])
def test_upload_receive_and_initiate_replay_use_pinned_limits(tmp_path, historical):
    service, doc, data, body = setup_upload(tmp_path, limits=PdfLimits.display())
    key = str(uuid4())
    ticket = service.initiate_upload(TENANT, doc["document_id"], body, key)
    if historical:
        item = service._get(TENANT, "upload", ticket["upload_id"])
        item.pop("upload_security_limits")
        service._put(TENANT, "upload", ticket["upload_id"], item, update=True)
    service.limits = PdfLimits.display(max_bytes=1)
    assert service.initiate_upload(TENANT, doc["document_id"], body, key) == ticket
    service.receive_content(TENANT, ticket["upload_id"], data, "application/pdf")
    assert service.complete_upload(
        TENANT,
        ticket["upload_id"],
        {"sha256": body["sha256"], "size_bytes": len(data)},
        str(uuid4()),
    )
    with pytest.raises(UploadRejected, match="UPLOAD_LIMIT_EXCEEDED"):
        service.initiate_upload(TENANT, doc["document_id"], body, str(uuid4()))


@pytest.mark.parametrize("historical", [True, False])
def test_saved_partial_facts_citation_failure_replays_its_pinned_algorithm(
    tmp_path, monkeypatch, historical
):
    from proofops.adapters.local import tag_store
    from proofops.application.budget import TokenUsage
    from proofops.application.tagging import consensus
    from proofops.application.tagging.service import RawTagResponse
    from proofops_worker import tag_runner

    from tests.integration import test_run_lifecycle as lifecycle
    from tests.integration.test_local_tag_runner import verified_setup

    baseline = types.ModuleType("pre_f5_consensus")
    monkeypatch.setitem(sys.modules, baseline.__name__, baseline)
    exec(
        compile((FIXTURES / "consensus_pre_f5.txt").read_text(), "pre_f5_consensus", "exec"),
        baseline.__dict__,
    )
    setup = lifecycle.setup

    def partial_setup(directory):
        service, body = setup(directory)
        service.fact_assembly_profile = (
            consensus.PARTIAL_FACTS_V1 if historical else consensus.PARTIAL_FACTS_V2
        )
        return service, body

    monkeypatch.setattr(lifecycle, "setup", partial_setup)
    _, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    invoke = runner.transport.invoke

    def response(request):
        if request["replicate_id"] == 2:
            return RawTagResponse(
                None,
                TokenUsage(10, 5, 0, 0, 1, "succeeded", "citation-fixture"),
                True,
                json.dumps({"validation_error": "TAGGING_EVIDENCE_ID_INVALID"}),
            )
        return invoke(request)

    monkeypatch.setattr(runner.transport, "invoke", response)
    writer = baseline.form_consensus if historical else consensus.form_consensus
    monkeypatch.setattr(tag_runner, "form_consensus", writer)
    monkeypatch.setattr(tag_store, "form_consensus", writer)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    snapshot = runner.tags.load_snapshot(TENANT, run_id)
    claim_id = snapshot["claims"][0]["claim_id"]
    before = runner.tags.load_inputs(TENANT, run_id, claim_id)
    if historical:
        assert before.consensus.reasons == ("PARTIAL_FACTS_UNSAFE",)
        assert before.snapshot()["fact_assembly"]["sha256"] == baseline.PARTIAL_FACTS_HASH
    else:
        assert len(before.consensus.candidate_elements) == 6
        assert all(e.state == "unknown" for e in before.consensus.candidate_elements)
        assert before.snapshot()["fact_assembly"] == {
            "profile": consensus.PARTIAL_FACTS_V2,
            "sha256": consensus.PARTIAL_FACTS_V2_HASH,
        }
        assert consensus.PARTIAL_FACTS_V2_HASH != baseline.PARTIAL_FACTS_HASH
    stored = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    monkeypatch.setattr(tag_store, "form_consensus", consensus.form_consensus)
    assert runner.tags.load_inputs(TENANT, run_id, claim_id).snapshot() == before.snapshot()
    assert runner.tags.load_snapshot(TENANT, run_id) == snapshot
    assert {p: p.read_bytes() for p in stored} == stored


@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("historical", [False, True])
def test_http_receipt_transport_and_file_read_use_upload_limits(tmp_path, streamed, historical):
    from tests.acceptance.test_upload import http_client

    # Larger than multipart envelope slack, so the mutable current limit also breaks transport.
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": "x" * 70_000})
    service, doc, data, body = setup_upload(
        tmp_path, data=write(writer), limits=PdfLimits.display()
    )
    ticket = service.initiate_upload(TENANT, doc["document_id"], body, str(uuid4()))
    if historical:
        item = service._get(TENANT, "upload", ticket["upload_id"])
        item.pop("upload_security_limits")
        service._put(TENANT, "upload", ticket["upload_id"], item, update=True)
    service.limits = PdfLimits.display(max_bytes=1)
    envelope = (
        b'--boundary\r\nContent-Disposition: form-data; name="ticket"\r\n\r\n'
        + ticket["post_fields"]["ticket"].encode()
        + b'\r\n--boundary\r\nContent-Disposition: form-data; name="file";'
        b' filename="source.pdf"\r\nContent-Type: application/pdf\r\n\r\n'
        + data
        + b"\r\n--boundary--\r\n"
    )
    with http_client(service) as client:
        response = client.post(
            ticket["post_url"],
            content=iter([envelope]) if streamed else envelope,
            headers={"Content-Type": "multipart/form-data; boundary=boundary"},
        )
        assert response.status_code == 204, response.text


def test_existing_ocg_display_cache_is_rebuilt_without_rewriting_version(tmp_path, monkeypatch):
    from hashlib import sha256
    from io import BytesIO

    from pypdf import PdfReader

    data = layer_pdf("off")
    # Reproduce the previous page-only writer's OCG visibility error.
    writer = PdfWriter()
    writer.add_page(PdfReader(BytesIO(data)).pages[0])
    previous_display = write(writer)
    assert pixels(previous_display)[1] == (255, 0, 0)
    service, doc, data, body = setup_upload(tmp_path, data=data, limits=PdfLimits.display())
    put = service._put

    def historical_put(tenant, kind, identifier, item, **kwargs):
        if kind == "version":
            metadata = item["upload_security"]
            for key in ("original_inspection", "repaired_inspection", "display_inspection"):
                metadata.pop(key, None)
            metadata["display_sha256"] = sha256(previous_display).hexdigest()
            path = service.root / "original" / tenant / f"{identifier}.display-v2.pdf"
            path.chmod(0o600)
            path.write_bytes(previous_display)
            path.chmod(0o400)
        return put(tenant, kind, identifier, item, **kwargs)

    monkeypatch.setattr(service, "_put", historical_put)
    ticket = service.initiate_upload(TENANT, doc["document_id"], body, str(uuid4()))
    service.receive_content(TENANT, ticket["upload_id"], data, "application/pdf")
    result = service.complete_upload(
        TENANT,
        ticket["upload_id"],
        {"sha256": body["sha256"], "size_bytes": len(data)},
        str(uuid4()),
    )
    snapshot = service.version_snapshot(TENANT, result["version_id"])
    audit = service.read_upload_audit(TENANT, doc["document_id"])
    display, metadata = service.read_display(TENANT, result["version_id"])
    assert pixels(display) == pixels(data)
    assert metadata["original_inspection"] == "complete"
    assert service.read_display(TENANT, result["version_id"]) == (display, metadata)
    assert service.version_snapshot(TENANT, result["version_id"]) == snapshot
    assert service.read_upload_audit(TENANT, doc["document_id"]) == audit
    old_path = service.root / "original" / TENANT / f'{result["version_id"]}.display-v2.pdf'
    assert old_path.read_bytes() == previous_display
    assert service.read_original(TENANT, result["version_id"]) == data


@pytest.mark.parametrize("configured", ["partial-facts-v1", "partial-facts-v2"])
def test_new_run_opt_in_pins_v2_without_changing_stored_v1(tmp_path, monkeypatch, configured):
    from proofops.application.runs import RunService

    from tests.integration.test_local_tag_runner import verified_setup

    init = RunService.__init__

    def configured_init(self, *args, **kwargs):
        init(self, *args, **(kwargs | {"fact_assembly_profile": configured}))

    monkeypatch.setattr(RunService, "__init__", configured_init)
    service, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    assert service.fact_assembly_profile == "partial-facts-v2"
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "needs_review"
    assert runner.tags.load_snapshot(TENANT, run_id)["fact_assembly_profile"] == "partial-facts-v2"


def test_failed_original_scan_status_is_stored_separately(tmp_path):
    external = b"<< /Length 0 /F (file:///DO_NOT_OPEN_REVIEW_ONLY) >>\nstream\n\nendstream"
    service, doc, data, body = setup_upload(
        tmp_path, data=raw_pdf(external, True), limits=PdfLimits.display()
    )
    ticket = service.initiate_upload(TENANT, doc["document_id"], body, str(uuid4()))
    service.receive_content(TENANT, ticket["upload_id"], data, "application/pdf")
    with pytest.raises(UploadRejected, match="PDF_INVALID") as error:
        service.complete_upload(
            TENANT,
            ticket["upload_id"],
            {"sha256": body["sha256"], "size_bytes": len(data)},
            str(uuid4()),
        )
    status = service._get(TENANT, "upload", ticket["upload_id"])
    assert status["status"] == "rejected"
    assert status["upload_security"] == error.value.security_metadata
    assert status["upload_security"]["original_inspection"] == "incomplete"
    assert status["upload_security"]["repaired_inspection"] == "not_attempted"
    assert not list((service.root / "original").rglob("*.pdf"))


def test_pinned_upload_limit_still_rejects_after_service_limit_increases(tmp_path):
    from tests.acceptance.test_upload import http_client

    service, doc, data, body = setup_upload(tmp_path, limits=PdfLimits.display())
    service.limits = PdfLimits.display(max_bytes=len(data))
    ticket = service.initiate_upload(TENANT, doc["document_id"], body, str(uuid4()))
    service.limits = PdfLimits.display()
    with pytest.raises(UploadRejected, match="UPLOAD_LIMIT_EXCEEDED"):
        service.receive_content(TENANT, ticket["upload_id"], data + b"x", "application/pdf")
    with http_client(service) as client:
        response = client.post(
            ticket["post_url"],
            data=ticket["post_fields"],
            files={"file": ("source.pdf", data + b"x", "application/pdf")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "UPLOAD_LIMIT_EXCEEDED"
    assert not service._get(TENANT, "upload", ticket["upload_id"])["received"]


@pytest.mark.parametrize("trigger", ["/E", "/X"])
def test_historical_unpinned_hover_keeps_legacy_rejection(tmp_path, trigger):
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    _widget_with_trigger(writer, trigger, _hide_action())
    service, doc, data, body = setup_upload(
        tmp_path, data=write(writer), limits=PdfLimits.display()
    )
    ticket = service.initiate_upload(TENANT, doc["document_id"], body, str(uuid4()))
    item = service._get(TENANT, "upload", ticket["upload_id"])
    item.pop("upload_security_limits")
    service._put(TENANT, "upload", ticket["upload_id"], item, update=True)
    service.receive_content(TENANT, ticket["upload_id"], data, "application/pdf")
    with pytest.raises(UploadRejected, match="PDF_INVALID"):
        service.complete_upload(
            TENANT,
            ticket["upload_id"],
            {"sha256": body["sha256"], "size_bytes": len(data)},
            str(uuid4()),
        )
