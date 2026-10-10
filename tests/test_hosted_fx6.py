"""FX6: real hosted HTTP upload path, local storage, no model calls."""

from hashlib import sha256
from io import BytesIO

import pytest
from proofops_api.hosted import HostedStore, create_hosted_app
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject

from tests.acceptance.test_upload_security import _hide_action, _widget_with_trigger
from tests.test_hosted_public import login
from tests.test_hosted_public import settings as _settings


@pytest.fixture
def settings(tmp_path):
    return _settings.__wrapped__(tmp_path)


@pytest.mark.parametrize("trigger", ["/E", "/X", "/Fo", "/Bl"])
@pytest.mark.parametrize("next_kind", [None, "/JavaScript", "/URI"])
def test_hosted_interaction_hide_upload_preserves_security(settings, trigger, next_kind):
    store = HostedStore(settings)
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    next_action = None
    if next_kind:
        key = "/JS" if next_kind == "/JavaScript" else "/URI"
        next_action = DictionaryObject(
            {NameObject("/S"): NameObject(next_kind), NameObject(key): TextStringObject("evil()")}
        )
    action = writer._add_object(
        _hide_action(target="ToF-MS 팝업", hidden=False, next_action=next_action)
    )
    _widget_with_trigger(writer, trigger, action)
    content = BytesIO()
    writer.write(content)
    data = content.getvalue()
    client, headers, tenant, _ = login(create_hosted_app(settings), store)
    request_headers = headers | {
        "Content-Type": "application/pdf",
        "Idempotency-Key": "fx6-hover-upload001",
    }
    response = client.post("/v1/documents", content=data, headers=request_headers)
    if next_kind:
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "PDF_INVALID"
        assert not list(settings.root.rglob("original.pdf"))
    else:
        assert response.status_code == 201, response.text
        document = response.json()
        assert document["page_count"] == 1
        assert document["sha256"] == sha256(data).hexdigest()
        assert (
            store.document_dir(tenant, document["document_id"]) / "original.pdf"
        ).read_bytes() == data
        replay = client.post("/v1/documents", content=data, headers=request_headers)
        assert replay.json() == document
