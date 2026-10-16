"""Deterministic synthetic PDF/provider responses for the offline release smoke.

No external transport or keys. Replies exercise production schema validation;
unknown evidence stays unknown and never receives a confirmed grade.
"""

import io
import json
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

import pdfplumber
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


@contextmanager
def async_parse_replies():
    """Replace only provider POST/status/download I/O, retaining async receipt checks."""
    from proofops.adapters.local.upstage_parse import UpstageParseProbe

    replies = {}

    def submit(content, mode):
        request = str(uuid4())
        replies[request] = fake_parse(content, mode)
        return {"request_id": request}

    def status(_probe, request):
        reply = replies[request]
        return dict(
            status="completed",
            total_pages=reply["usage"]["pages"],
            completed_pages=reply["usage"]["pages"],
            model=reply["model"],
            batches=[dict(download_url=f"https://offline.files.upstage.ai/{request}")],
        )

    def download(url):
        return replies[url.rsplit("/", 1)[1]]

    with (
        patch.object(UpstageParseProbe, "_async_status", status),
        patch.object(UpstageParseProbe, "_async_download", staticmethod(download)),
    ):
        yield submit


TEXT = "Acme reduced energy use by 20 percent in 2024."


def source_pdf():
    writer = PdfWriter()
    for number in range(2):
        page = writer.add_blank_page(600, 400)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 16 Tf 40 250 Td ({TEXT}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def fake_parse(content, mode):
    elements = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            elements.append(
                dict(
                    id=i,
                    page=i,
                    category="paragraph",
                    coordinates=[
                        dict(x=x, y=y)
                        for x, y in ((0.05, 0.30), (0.95, 0.30), (0.95, 0.45), (0.05, 0.45))
                    ],
                    content=dict(text=TEXT, html=f"<p>{TEXT}</p>"),
                )
            )
    return dict(
        model="document-parse-260128",
        usage={"pages": len(elements), mode: list(range(1, len(elements) + 1))},
        elements=elements,
    )


def fake_page_ocr(_png):
    with pdfplumber.open(io.BytesIO(source_pdf())) as pdf:
        page = pdf.pages[0]
        words = [
            dict(
                id=i,
                text=w["text"],
                confidence=0.99,
                boundingBox=dict(
                    vertices=[
                        dict(x=x * 3, y=y * 3)
                        for x, y in (
                            (w["x0"], w["top"]),
                            (w["x1"], w["top"]),
                            (w["x1"], w["bottom"]),
                            (w["x0"], w["bottom"]),
                        )
                    ]
                ),
            )
            for i, w in enumerate(page.extract_words())
        ]
        raw = dict(
            apiVersion="1.1",
            modelVersion="ocr-260930",
            numBilledPages=1,
            stored=False,
            pages=[dict(id=0, width=page.width * 3, height=page.height * 3, words=words)],
        )
    return json.dumps(raw).encode(), "fake-page-ocr"


def fake_llm(body):
    user = json.loads(body["messages"][1]["content"])
    data = user["untrusted_document_data"]
    if "source_sentences" in data:
        payload = dict(sentence_ids=[s["sentence_id"] for s in data["source_sentences"]])
    elif "spans" in data and user.get("packet_sha256"):
        payload = dict(
            complete=True,
            records=[],
            packet_sha256=user["packet_sha256"],
            replicate_id=user["replicate_id"],
        )
    elif user.get("schema") == "source-relations-occurrence-v3":
        payload = dict(
            relations=[
                dict(
                    source_index=s["source_index"],
                    dimensions=dict(entity=None, metric=None, reporting_period=None),
                )
                for s in data["sources"]
            ]
        )
    elif "allowed_elements" in data:
        payload = dict(
            claim_id=user["claim_id"],
            packet_sha256=user["packet_sha256"],
            replicate_id=user["replicate_id"],
            track="performance",
            safe_harbor_category=None,
            elements=[
                dict(
                    element_id=e,
                    state="unknown",
                    evidence_refs=[],
                    normalized_value=None,
                    credited_from=None,
                    reason_code="fixture_unresolved",
                )
                for e in data["allowed_elements"]
            ],
            superlative_quote=None,
            warnings=[],
        )
    else:
        payload = dict(
            claim_id=user["claim_id"],
            track="performance",
            safe_harbor_category=None,
            track_confidence=1,
            dimensions=dict(entity=None, metric=None, reporting_period=None),
        )
    model = body["model"]
    usage = dict(prompt_tokens=20, completion_tokens=10)
    if model == "gpt-6-luna":
        usage["prompt_tokens_details"] = {}
    else:
        usage["cost"] = 0.00001
    return dict(
        id=str(uuid4()),
        model=model,
        usage=usage,
        choices=[dict(finish_reason="stop", message=dict(content=json.dumps(payload)))],
    )
