"""Fresh, deterministic model transports. No saved LLM answers or product patches.

Loaded only from the gate's private sitecustomize mount in network-none images.
Source parsing, verification, authorization, leases, replicas and rules stay real.
All model-generated element states deliberately remain unknown: this tests wiring,
not semantic accuracy. The audit identifies every generated transport response.
"""

import csv
import hashlib
import html
import io
import json
import re
import socket
import subprocess
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4

from predeploy_runtime_base import audit as base_audit
from predeploy_runtime_base import intake as base_intake
from predeploy_runtime_base import request as api_request
from predeploy_runtime_base import verify as base_verify


def audit(event, **values):
    base_audit(event, utc_epoch=time.time(), **values)


def intake():
    case = json.loads(Path("/fixtures/case.json").read_text())
    return base_intake(tenant_id=case.get("tenant_id"))


def generate_llm(body):
    user = json.loads(body["messages"][1]["content"])
    data = user.get("untrusted_document_data", {})
    system = body["messages"][0]["content"]
    if "claim" in user and "sources" in user:
        payload = dict(
            track="management",
            safe_harbor_category=None,
            superlative_quote=None,
            period_kind=None,
            dimensions=dict(activity=None, period=None, boundary=None),
            elements={f"M{i}": dict(state="unknown", evidence=None) for i in range(1, 5)},
            triggers=dict(governance_claim=None, compensation_link_claim=None),
        )
        role = "c3"
    elif "source_sentences" in data:
        payload = dict(sentence_ids=[s["sentence_id"] for s in data["source_sentences"]])
        role = "extract"
    elif "spans" in data and "packet_sha256" in user:
        payload = dict(
            complete=True,
            records=[],
            packet_sha256=user["packet_sha256"],
            replicate_id=user["replicate_id"],
        )
        role = "inventory"
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
        role = "relations"
    elif "allowed_elements" in data:
        allowed = data["allowed_elements"]
        track = {"G": "goal", "P": "performance", "M": "management"}[allowed[0][0]]
        payload = dict(
            track=track,
            safe_harbor_category=None,
            elements=[
                dict(
                    element_id=e,
                    state="unknown",
                    evidence_refs=[],
                    normalized_value=None,
                    credited_from=None,
                    reason_code=None,
                )
                for e in allowed
            ],
            superlative_quote=None,
            warnings=[],
        )
        if "omit claim_id/packet_sha256/replicate_id" not in system:
            payload.update({k: user[k] for k in ("claim_id", "packet_sha256", "replicate_id")})
        role = "elements"
    else:
        quote = data.get("atomic_quote", data.get("claim_quote", ""))
        track = (
            "goal"
            if re.search(r"목표|2030|2050", quote)
            else "performance"
            if re.search(r"\d|배출량", quote)
            else "management"
        )
        payload = dict(
            track=track,
            safe_harbor_category=None,
            track_confidence=1,
            dimensions=dict(entity=None, metric=None, reporting_period=None),
        )
        if "exactly track, safe_harbor_category, track_confidence, dimensions" not in system:
            payload["claim_id"] = user["claim_id"]
        role = "preliminary"
    audit(
        "generated_reply",
        provider="llm",
        role=role,
        wire_bytes=len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()),
    )
    return dict(
        id="fresh-sim-" + str(uuid4()),
        model=body["model"],
        usage=dict(prompt_tokens=100, completion_tokens=100, prompt_tokens_details={}),
        choices=[dict(finish_reason="stop", message=dict(content=json.dumps(payload)))],
    )


def generate_parse(content, mode):
    """Generate candidate text/boxes from THIS request's PDF, without verified flags."""
    import opendataloader_pdf
    from proofops.adapters.parsing.opendataloader import _node_text
    from pypdf import PdfReader

    pdf = PdfReader(io.BytesIO(content))
    count = len(pdf.pages)
    elements = []
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "request.pdf"
        path.write_bytes(content)
        opendataloader_pdf.convert(
            str(path), output_dir=temp, format="json", quiet=True, image_output="off", threads="1"
        )
        native = json.loads(path.with_suffix(".json").read_text())

    def walk(nodes):
        for node in nodes:
            kind = node.get("type")
            if kind in ("paragraph", "heading", "list item", "table"):
                number = node["page number"]
                page = pdf.pages[number - 1]
                w, h = float(page.mediabox.width), float(page.mediabox.height)
                box = node.get("bounding box")
                text = _node_text(node)
                if not box or not text.strip():
                    continue
                x0, bottom, x1, top = box
                if not (0 <= x0 < x1 <= w and 0 <= bottom < top <= h):
                    continue
                markup = "<p>" + html.escape(text) + "</p>"
                category = "paragraph"
                if kind == "table":
                    rows = node.get("rows", node.get("kids", []))
                    markup = (
                        "<table>"
                        + "".join(
                            "<tr>"
                            + "".join(
                                "<td>" + html.escape(_node_text(cell)) + "</td>"
                                for cell in row.get("cells", row.get("kids", []))
                            )
                            + "</tr>"
                            for row in rows
                        )
                        + "</table>"
                    )
                    category = "table"
                elements.append(
                    dict(
                        id=len(elements),
                        page=number,
                        category=category,
                        coordinates=[
                            dict(x=x / w, y=y / h)
                            for x, y in (
                                (x0, h - top),
                                (x1, h - top),
                                (x1, h - bottom),
                                (x0, h - bottom),
                            )
                        ],
                        content=dict(text=text, html=markup),
                    )
                )
            else:
                walk(node.get("kids", []))

    walk(native["kids"])
    audit(
        "generated_reply",
        provider="parse",
        pages=count,
        source_sha256=hashlib.sha256(content).hexdigest(),
    )
    return dict(
        model="document-parse-260128",
        usage={"pages": count, mode: list(range(1, count + 1))},
        elements=elements,
    )


def generate_ocr(png):
    """Exact current-PDF pixel matches get deterministic native-word simulation.

    This is deliberately a fake provider, not independent visual evidence. Every
    product source guard still runs. Unmatched crops use actual local OCR.
    """
    native = native_ocr(png)
    if native is not None:
        audit(
            "generated_reply",
            provider="ocr",
            generator="native-geometry-simulation",
            png_sha256=hashlib.sha256(png).hexdigest(),
        )
        return json.dumps(native).encode(), "fresh-native-sim-" + str(uuid4())
    from PIL import Image

    width, height = Image.open(io.BytesIO(png)).size
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "page.png"
        path.write_bytes(png)
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "kor+eng", "tsv"],
            capture_output=True,
            check=True,
            timeout=120,
            text=True,
        )
    words = []
    for row in csv.DictReader(io.StringIO(result.stdout), delimiter="\t"):
        if not row.get("text", "").strip() or row["level"] != "5":
            continue
        x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        words.append(
            dict(
                id=len(words),
                text=row["text"],
                confidence=max(0, float(row["conf"])) / 100,
                boundingBox=dict(
                    vertices=[
                        dict(x=a, y=b) for a, b in ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
                    ]
                ),
            )
        )
    audit("generated_reply", provider="ocr", png_sha256=hashlib.sha256(png).hexdigest())
    return json.dumps(
        dict(
            apiVersion="1.1",
            modelVersion="ocr-260930",
            numBilledPages=1,
            stored=False,
            pages=[dict(id=0, width=width, height=height, words=words)],
        )
    ).encode(), "fresh-tesseract"


_native_pages = None
_native_lock = threading.RLock()


def native_ocr(png):
    with _native_lock:
        return _native_ocr_locked(png)


def _native_ocr_locked(png):
    """Bind fake OCR to freshly rendered pixels of the fixture's original PDF."""
    global _native_pages
    import pdfplumber
    from PIL import Image
    from proofops.adapters.local import source_fxf, upstage_ocr_page

    def pixels(raw):
        with Image.open(io.BytesIO(raw)) as im:
            return (im.size, hashlib.sha256(im.convert("RGBA").tobytes()).hexdigest())

    if _native_pages is None:
        _native_pages = {}
        source = Path("/fixtures/original.pdf").read_bytes()
        case = json.loads(Path("/fixtures/case.json").read_text())
        pages = case.get("pages")
        if case.get("selection_mode") == "automatic":
            session = json.loads(Path("/data/gate-session.json").read_text())
            pages = session["run"]["selected_pages"]
        if hashlib.sha256(source).hexdigest() != case["source_sha256"]:
            raise ValueError("FRESH_ORIGINAL_SHA_MISMATCH")
        with pdfplumber.open(io.BytesIO(source)) as pdf:
            for number in pages:
                page = pdf.pages[number - 1]
                words = page.extract_words()
                for render in (upstage_ocr_page.render_page, source_fxf.render_page):
                    try:
                        rendered = render(source, number)
                    except ValueError:
                        continue
                    raw = rendered["png"]
                    key = pixels(raw)
                    width, height = key[0]
                    response_words = []
                    for word in words:
                        left, right = (
                            word["x0"] * width / page.width,
                            word["x1"] * width / page.width,
                        )
                        top, bottom = (
                            word["top"] * height / page.height,
                            word["bottom"] * height / page.height,
                        )
                        response_words.append(
                            dict(
                                id=len(response_words),
                                text=word["text"],
                                confidence=1.0,
                                boundingBox=dict(
                                    vertices=[
                                        dict(x=x, y=y)
                                        for x, y in (
                                            (left, top),
                                            (right, top),
                                            (right, bottom),
                                            (left, bottom),
                                        )
                                    ]
                                ),
                            )
                        )
                    _native_pages[key] = dict(
                        apiVersion="1.1",
                        modelVersion="ocr-260930",
                        numBilledPages=1,
                        stored=False,
                        pages=[dict(id=0, width=width, height=height, words=response_words)],
                    )
    return _native_pages.get(pixels(png))


def install():
    from proofops.adapters.local.upstage_parse import UpstageParseProbe
    from proofops_api import hosted_analysis, hosted_ocr, hosted_publication

    connect = socket.socket.connect

    def local_only(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in (
            "127.0.0.1",
            "::1",
        ):
            audit("network_denied")
            raise OSError("FRESH_GATE_EXTERNAL_NETWORK_FORBIDDEN")
        return connect(sock, address)

    socket.socket.connect = local_only
    socket.socket.connect_ex = local_only
    responses = {}

    def parse(probe, content, mode):
        response = generate_parse(content, mode)
        if not probe.integrated:
            return response
        key = str(uuid4())
        responses[key] = response
        return dict(request_id=key)

    def status(probe, key):
        response = responses[key]
        n = response["usage"]["pages"]
        return dict(
            status="completed",
            total_pages=n,
            completed_pages=n,
            model=response["model"],
            batches=[dict(download_url="https://offline.files.upstage.ai/" + key)],
        )

    def inject(cls, post):
        init = cls.__init__

        def wrapped(self, *a, **kw):
            kw["post"] = (lambda pdf, mode: parse(self, pdf, mode)) if post is None else post
            init(self, *a, **kw)

        cls.__init__ = wrapped

    inject(hosted_analysis.HostedOpenAILunaProbe, generate_llm)
    inject(hosted_analysis.HostedParseProbe, None)
    inject(hosted_ocr.HostedOCRStore, generate_ocr)
    UpstageParseProbe._async_status = status
    UpstageParseProbe._async_download = staticmethod(lambda url: responses[url.rsplit("/", 1)[1]])
    process = hosted_analysis.run_analysis_process

    def observed(*a, **kw):
        audit("analysis_subprocess", publication_fd=kw.get("publication_fd"))
        return process(*a, **kw)

    hosted_analysis.run_analysis_process = observed
    handoff = hosted_publication.make_handoff

    def observed_handoff(*a, **kw):
        started = time.monotonic()
        value = handoff(*a, **kw)
        audit("child_handoff", bytes=len(value) if value else 0, seconds=time.monotonic() - started)
        return value

    hosted_publication.make_handoff = observed_handoff


def verify():
    result = base_verify()
    data = Path("/data")
    session = json.loads((data / "gate-session.json").read_text())
    result["selection"] = dict(
        automatic=session["automatic_selection"],
        proposal=session["proposal"],
        accepted=session["selection"],
        pages=session["run"]["selected_pages"],
        claim_pages=session["run"]["claim_pages"],
    )
    if result.get("result") is not None:
        route = session["run"]["status_url"] + "/result?w18=true"
        located, _ = api_request(route, auth=session["auth"])
        exact, reasons = 0, Counter()

        def strip_w18(value):
            nonlocal exact
            if isinstance(value, dict):
                if value.get("w18_line_rects") or value.get("w18_cell_rects"):
                    exact += 1
                if value.get("w18_reason"):
                    reasons[value["w18_reason"]] += 1
                return {k: strip_w18(v) for k, v in value.items() if not k.startswith("w18_")}
            if isinstance(value, list):
                return [strip_w18(v) for v in value]
            return value

        unchanged = strip_w18(located) == result["result"]
        result["w18"] = dict(exact_refs=exact, reasons=dict(reasons), default_unchanged=unchanged)
        if not unchanged:
            raise ValueError("W18_CHANGED_EXISTING_RESULT")
    state = (
        data
        / "payloads"
        / session["tenant"]
        / session["document"]["document_id"]
        / "analysis"
        / session["run"]["run_id"]
    )
    inventories = [
        json.loads(p.read_text())
        for p in state.glob("tagging-receipts/*/sc1-inventory-artifacts/*/*/*.json")
    ]
    result["inventory_completed"] = sum(i["completed_calls"] for i in inventories)
    result["inventory_planned"] = sum(i["planned_calls"] for i in inventories)
    reasons = Counter()
    for claim in (result.get("result") or {}).get("claims", []):
        reason = (claim.get("provisional_grade") or {}).get("reason")
        if reason:
            reasons[reason] += 1
    result["hold_distribution"] = dict(reasons)
    if (state / "outcome.json").exists():
        result["outcome"] = json.loads((state / "outcome.json").read_text())
    audit_path = data / "gate-audit.jsonl"
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    timed = [e for e in events if "utc_epoch" in e]
    result["clock_discontinuity_seconds"] = max(
        [
            abs((b["utc_epoch"] - a["utc_epoch"]) - (b["monotonic"] - a["monotonic"]))
            for a, b in zip(timed, timed[1:])
        ],
        default=0,
    )
    for event in events:
        if event["event"] == "child_handoff" and "seconds" in event and "outcome" in result:
            result["outcome"]["stage_seconds"]["publish"] = event["seconds"]
    result["c3_generated_calls"] = sum(
        e.get("event") == "generated_reply" and e.get("role") == "c3" for e in events
    )
    import sqlite3

    if not (state / "state.sqlite3").exists():
        result["errors"] = {"ANALYSIS_STATE_MISSING": 1}
        return result
    db = sqlite3.connect(f"file:{state}/state.sqlite3?mode=ro", uri=True)
    errors = Counter()
    for (raw,) in db.execute("SELECT value FROM job_records WHERE kind='job'"):
        value = json.loads(raw)
        if value.get("error_code"):
            errors[value["error_code"]] += 1
    for (raw,) in db.execute("SELECT value FROM job_records WHERE kind='artifact'"):
        value = json.loads(raw)
        for claim in value.get("claims", []):
            for run in claim.get("tag_runs", []):
                errors.update(run.get("errors", []))
    result["errors"] = dict(errors)
    db.close()
    return result
