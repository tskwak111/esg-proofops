"""Read-only harness injected into an isolated image by predeploy_gate.py.

Production API, hosted_control.worker_loop, execute_analysis, drive, native/table
readers and inherited publication FD all run unchanged. Patch provider I/O only;
observe subprocess/handoff without replacing their return values.
"""

import hashlib
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from predeploy_replies import (
    digest,
    lookup_reply,
    normalized_wire,
    pdfium_transport_key,
    remap_response,
)

DATA = Path("/data")
FIXTURE = Path("/fixtures")


def parse_request_key(pdf, mode, pages, model, *, asynchronous):
    body = dict(
        model=model,
        mode=mode,
        pdf_sha256=hashlib.sha256(pdf).hexdigest(),
        pages=pages,
        bytes_len=len(pdf),
    )
    if asynchronous:
        body["transport"] = "async"
    return digest(body)


def next_reply_attempt(uses, key, body):
    # Fresh claim/request UUIDs may share a normalized wire. They are separate
    # logical calls, each entitled to the first recorded reply. Only retries of
    # the same actual wire consume that call's subsequent recorded attempts.
    identity = (key, digest(body))
    index = uses.get(identity, 0)
    uses[identity] = index + 1
    return index


def capture_input_miss(key, content, *, kind):
    """Save an unmatched public-report input with private permissions."""
    extension = {"ocr": ".png", "parse": ".pdf"}[kind]
    path = DATA / ("gate-miss-" + kind + "-" + key + extension)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError("PREDEPLOY_CAPTURE_HASH_COLLISION") from None
        return path.name
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path.name


def audit(event, **values):
    record = dict(event=event, pid=os.getpid(), monotonic=time.monotonic(), **values)
    fd = os.open(DATA / "gate-audit.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (json.dumps(record) + "\n").encode())
    finally:
        os.close(fd)


def install():
    """Activated only by the harness's private sitecustomize mount, never an env switch."""
    original_connect = socket.socket.connect

    def loopback_only(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in (
            "127.0.0.1",
            "::1",
        ):
            audit("network_denied")
            raise OSError("PREDEPLOY_EXTERNAL_NETWORK_FORBIDDEN")
        return original_connect(sock, address)

    socket.socket.connect = loopback_only
    socket.socket.connect_ex = loopback_only
    original_excepthook = sys.excepthook

    def exception(kind, value, trace):
        code = str(value)
        audit(
            "process_exception",
            exception_type=kind.__name__,
            code=code if re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", code) else None,
        )
        original_excepthook(kind, value, trace)

    sys.excepthook = exception
    from proofops.adapters.local.upstage_parse import UpstageParseProbe
    from proofops_api import hosted_analysis as analysis
    from proofops_api import hosted_ocr, hosted_publication

    replies = None
    uses = {}
    import threading

    lock = threading.Lock()

    def load():
        nonlocal replies
        if replies is None:
            replies = json.loads((FIXTURE / "replies.json").read_text())
        return replies

    def llm(probe, body):
        context = probe._response_context.get()
        replica = context[1] if context else 0
        match = lookup_reply(body, replica, load()["llm"])
        if match is None:
            key, _ = normalized_wire(body, replica)
            # A new prompt/geometry/selector cannot borrow a similar old answer.
            path = DATA / ("gate-miss-" + key + ".json")
            path.write_text(json.dumps(dict(body=body, replica=replica), ensure_ascii=False))
            path.chmod(0o600)
            audit("fixture_miss", provider="llm", wire_sha256=key, replica=replica)
            raise ValueError("PREDEPLOY_RECORDED_WIRE_MISSING")
        key, identities, reordered = match
        candidates = load()["llm"][key]
        if reordered:
            audit("extraction_context_order_normalized", wire_sha256=key)
        with lock:
            index = next_reply_attempt(uses, key, body)
        if index >= len(candidates):
            audit("fixture_miss", provider="llm", wire_sha256=key, replica=replica)
            raise ValueError("PREDEPLOY_RECORDED_ATTEMPT_MISSING")
        record = candidates[index]
        audit(
            "recorded_reply",
            provider="llm",
            replica=replica,
            response_sha256=record["response_sha256"],
        )
        return dict(
            id="offline-recorded",
            model="gpt-6-luna",
            choices=[
                dict(
                    message=dict(
                        content=remap_response(record["content"], record["identities"], identities)
                    ),
                    finish_reason="stop",
                )
            ],
            usage=dict(
                prompt_tokens=record["input_tokens"],
                completion_tokens=record["output_tokens"],
                prompt_tokens_details=dict(cached_tokens=record["cached_tokens"]),
            ),
        )

    def ocr(png):
        key = hashlib.sha256(png).hexdigest()
        record = load()["ocr"].get(key)
        if record is None:
            if os.environ.get("PREDEPLOY_CAPTURE_MISSES") == "1":
                name = capture_input_miss(key, png, kind="ocr")
                audit("fixture_miss_capture", provider="ocr", png_sha256=key, file=name)
            audit("fixture_miss", provider="ocr", png_sha256=key)
            raise ValueError("PREDEPLOY_RECORDED_PNG_MISSING")
        raw = bytes.fromhex(record["response_hex"])
        if hashlib.sha256(raw).hexdigest() != record["response_sha256"]:
            raise ValueError("PREDEPLOY_RESPONSE_HASH_MISMATCH")
        audit("recorded_reply", provider="ocr", response_sha256=record["response_sha256"])
        return raw, "offline-recorded-ocr"

    def parse(probe, pdf, mode):
        import io

        from proofops.adapters.local.upstage_parse import PARSE_MODEL_PINNED
        from pypdf import PdfReader

        key = parse_request_key(
            pdf,
            mode,
            len(PdfReader(io.BytesIO(pdf)).pages),
            PARSE_MODEL_PINNED,
            asynchronous=probe.integrated,
        )
        record = load()["parse"].get(key)
        if record is None:
            transport_key = pdfium_transport_key(
                pdf,
                mode,
                PARSE_MODEL_PINNED,
                asynchronous=probe.integrated,
            )
            saved_key = load().get("parse_aliases", {}).get(transport_key)
            if saved_key is not None:
                key, record = saved_key, load()["parse"][saved_key]
                audit(
                    "parse_pdfium_metadata_normalized",
                    request_sha256=key,
                    pdfium_transport_key=transport_key,
                )
        if record is None:
            if os.environ.get("PREDEPLOY_CAPTURE_MISSES") == "1":
                name = capture_input_miss(key, pdf, kind="parse")
                audit("fixture_miss_capture", provider="parse", request_sha256=key, file=name)
            audit(
                "fixture_miss",
                provider="parse",
                request_sha256=key,
                pdf_sha256=hashlib.sha256(pdf).hexdigest(),
            )
            raise ValueError("PREDEPLOY_RECORDED_PDF_MISSING")
        if (
            record["asynchronous"] != probe.integrated
            or record["mode"] != mode
            or digest(record["response"], ensure_ascii=True) != record["response_sha256"]
        ):
            raise ValueError("PREDEPLOY_RESPONSE_HASH_MISMATCH")
        if probe.integrated:
            return dict(request_id="offline-" + key)
        audit("recorded_reply", provider="parse", response_sha256=record["response_sha256"])
        return record["response"]

    def status(probe, request):
        outputs = load()["parse"][request.removeprefix("offline-")]["response"]
        pages = sum(
            len(r["elements"]) > 0 and len({e["page"] for e in r["elements"]}) for r in outputs
        )
        return dict(
            status="completed",
            total_pages=pages,
            completed_pages=pages,
            model=outputs[0]["model"],
            batches=[
                dict(download_url=f"https://offline.files.upstage.ai/{request}/{i}")
                for i in range(len(outputs))
            ],
        )

    def download(url):
        request, index = url.rsplit("/", 2)[-2:]
        audit("recorded_reply", provider="parse")
        return load()["parse"][request.removeprefix("offline-")]["response"][int(index)]

    def inject(cls, post):
        original = cls.__init__

        def init(self, *args, **kwargs):
            if post == "llm":
                kwargs["post"] = lambda body: llm(self, body)
            elif post == "parse":
                kwargs["post"] = lambda pdf, mode: parse(self, pdf, mode)
            else:
                kwargs["post"] = post
            original(self, *args, **kwargs)

        cls.__init__ = init

    inject(analysis.HostedOpenAILunaProbe, "llm")
    inject(analysis.HostedParseProbe, "parse")
    inject(hosted_ocr.HostedOCRStore, ocr)
    UpstageParseProbe._async_status = status
    UpstageParseProbe._async_download = staticmethod(download)

    original_process = analysis.run_analysis_process

    def process(command, store, job, document_lock, *, publication_fd=None):
        if publication_fd is None:
            raise ValueError("PREDEPLOY_PUBLICATION_FD_REQUIRED")
        os.fstat(publication_fd)
        audit(
            "analysis_subprocess",
            run_id=job["run_id"],
            lock_fd=document_lock.fileno(),
            publication_fd=publication_fd,
        )
        result = original_process(command, store, job, document_lock, publication_fd=publication_fd)
        audit("analysis_subprocess_returned", run_id=job["run_id"])
        return result

    analysis.run_analysis_process = process
    original_handoff = hosted_publication.make_handoff

    def handoff(*args, **kwargs):
        packet = original_handoff(*args, **kwargs)
        audit("child_handoff", bytes=len(packet) if packet else 0)
        return packet

    hosted_publication.make_handoff = handoff


def request(path, *, body=None, auth=None, headers=None, pdf=False):
    values = dict(Origin=os.environ["APP_ORIGIN"]) | (headers or {})
    if auth:
        values |= {"Cookie": auth["cookie"], "X-CSRF-Token": auth["csrf"]}
    if body is not None:
        values["Content-Type"] = "application/pdf" if pdf else "application/json"
        body = body if pdf else json.dumps(body).encode()
    req = urllib.request.Request("http://127.0.0.1:8000" + path, body, values)
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.load(response), response.headers


def intake(*, tenant_id=None):
    from proofops_api.hosted_store import HostedSettings, HostedStore

    case = json.loads((FIXTURE / "case.json").read_text())
    source = (FIXTURE / "original.pdf").read_bytes()
    assert hashlib.sha256(source).hexdigest() == case["source_sha256"]
    store = HostedStore(HostedSettings.from_env(os.environ))
    tenant = tenant_id or str(uuid4())
    invite = store.invite(tenant, str(uuid4()), "editor", now=time.time())
    session, headers = request("/v1/auth/invitation", body=dict(code=invite))
    auth = dict(cookie=headers["Set-Cookie"].split(";", 1)[0], csrf=session["csrf_token"])
    document, _ = request(
        "/v1/documents",
        body=source,
        pdf=True,
        auth=auth,
        headers={"Idempotency-Key": "predeploy-upload-0001"},
    )
    path = f'/v1/documents/{document["document_id"]}/scope-plan'
    scope, headers = request(path, body={}, auth=auth)
    automatic = case.get("selection_mode") == "automatic"
    # The response uses pages/claim_pages; the edit request uses selected_*.
    # Record the same proposed arrays in request form, without choosing pages.
    proposal = dict(
        selected_claim_pages=scope["selection"]["claim_pages"],
        selected_evidence_pages=scope["selection"]["pages"],
    )
    scope, _ = request(
        path + "/selection",
        auth=auth,
        headers={"If-Match": headers["ETag"]},
        body=dict(
            selected_claim_pages=proposal["selected_claim_pages"]
            if automatic
            else case["claim_pages"],
            selected_evidence_pages=proposal["selected_evidence_pages"]
            if automatic
            else case["pages"],
            manual_selection=not automatic,
            reporting_scope=case["reporting_scope"],
        ),
    )
    started = time.monotonic()
    run, _ = request(
        "/v1/runs",
        auth=auth,
        headers={"Idempotency-Key": "predeploy-run-0001"},
        body=dict(
            document_id=document["document_id"],
            scope_selection_sha256=scope["selection"]["selection_sha256"],
        ),
    )
    (DATA / "gate-session.json").write_text(
        json.dumps(
            dict(
                auth=auth,
                tenant=tenant,
                document=document,
                run=run,
                accepted_monotonic=started,
                automatic_selection=automatic,
                proposal=proposal,
                selection=scope["selection"],
            )
        )
    )
    return dict(
        run_id=run["run_id"],
        scope_status=scope["plan"]["status"],
        pages=run["selected_pages"],
        claim_pages=run["claim_pages"],
    )


def verify():
    from proofops_api.hosted_store import HostedSettings, HostedStore

    record = json.loads((DATA / "gate-session.json").read_text())
    run, _ = request(record["run"]["status_url"], auth=record["auth"])
    result = None
    if run.get("result_url"):
        result, _ = request(run["result_url"], auth=record["auth"])
    store = HostedStore(HostedSettings.from_env(os.environ))
    directory = store.document_dir(record["tenant"], record["document"]["document_id"])
    assert (
        hashlib.sha256((directory / "original.pdf").read_bytes()).hexdigest()
        == (record["document"]["sha256"])
    )
    state = directory / "analysis" / run["run_id"]
    fingerprint = None
    runtime = None
    table_blocks = 0
    from proofops.adapters.parsing.parser_artifacts import (
        iter_parser_artifacts,
        read_parser_json,
    )

    for graph_path in iter_parser_artifacts(state / "parser-prepared", "graph.json"):
        graph = read_parser_json(graph_path)
        table_blocks += sum(b["kind"] == "table" for b in graph["blocks"])
    if (state / "result-1.json").exists():
        fingerprint = hashlib.sha256((state / "result-1.json").read_bytes()).hexdigest()
        previous = DATA / "gate-snapshot-sha256"
        if previous.exists():
            assert previous.read_text() == fingerprint
        else:
            previous.write_text(fingerprint)
    if (state / "worker-runtime.json").exists():
        runtime = json.loads((state / "worker-runtime.json").read_text())
    with store.transaction() as db:
        unsettled = db.execute(
            "SELECT count(*) FROM deletion.costs WHERE status!='settled'"
        ).fetchone()[0]
    return dict(
        status=run["status"],
        error_code=run.get("error_code"),
        result=result,
        seconds=time.monotonic() - record["accepted_monotonic"],
        source_preserved=True,
        snapshot_sha256=fingerprint,
        runtime=runtime,
        table_blocks=table_blocks,
        unsettled_costs=unsettled,
    )


if __name__ == "__main__":
    print(json.dumps({"intake": intake, "verify": verify}[sys.argv[1]]()))
