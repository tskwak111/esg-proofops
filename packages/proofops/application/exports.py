"""Capture revisions once, then render only immutable inputs; no grading/model calls."""

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from proofops.application.reporting import build_report_model, render_report
from proofops.domain.rulepacks import canonical_json

MAX_EXPORT_BYTES = 32 * 1024 * 1024


class ExportRejected(ValueError):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def timestamp(now):
    return datetime.fromtimestamp(now, UTC).isoformat().replace("+00:00", "Z")


def create_snapshot(store, tenant_id, export_id):
    for _ in range(4):  # First attempt, then at most three snapshot-only retries.
        frozen = store.frozen(tenant_id, export_id)
        if frozen is not None:
            return frozen
        captured = store.capture(tenant_id, export_id)
        if store.freeze(tenant_id, export_id, captured):
            return captured
    raise ExportRejected("EXPORT_SNAPSHOT_BUSY")


def build_export(snapshot, formats):
    model = build_report_model(snapshot["manifest"], snapshot["decisions"])
    manifest = canonical_json(snapshot["manifest"]).encode()
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED) as bundle:
        for fmt in ("manifest", *formats):
            name = "manifest.json" if fmt == "manifest" else f"report.{fmt}"
            content = manifest if fmt == "manifest" else render_report(model, fmt)
            if stream.tell() + len(content) > MAX_EXPORT_BYTES:
                raise ExportRejected("EXPORT_SIZE_LIMIT")
            bundle.writestr(ZipInfo(name), content)
    content = stream.getvalue()
    if len(content) > MAX_EXPORT_BYTES:
        raise ExportRejected("EXPORT_SIZE_LIMIT")
    return content, sha256(manifest).hexdigest(), model["partial"]


class ExportService:
    def __init__(self, store):
        self.store = store

    def create(self, actor, run_id, body, key, *, now):
        if not isinstance(body, dict) or set(body) != {"formats", "allow_partial"}:
            raise ExportRejected("VALIDATION_ERROR", 422)
        formats = body["formats"]
        if (
            not isinstance(formats, list)
            or not 1 <= len(formats) <= 3
            or any(not isinstance(f, str) or f not in ("json", "csv", "html") for f in formats)
            or len(set(formats)) != len(formats)
            or type(body["allow_partial"]) is not bool
        ):
            raise ExportRejected("VALIDATION_ERROR", 422)
        if not isinstance(key, str) or not 16 <= len(key) <= 128:
            raise ExportRejected("IDEMPOTENCY_KEY_INVALID", 400)
        export_id = self.store.reserve(actor, run_id, body, key, now=now)
        result = self.get(actor, export_id, now=now)
        if result["state"] == "failed":
            raise ExportRejected(self.store.state(actor.tenant_id, export_id)["errors"][0])
        return result

    def get(self, actor, export_id, *, now):
        state = self.store.state(actor.tenant_id, export_id)
        if state["response"]["state"] in ("ready", "failed") or now < state["retry_at"]:
            return state["response"]
        try:
            snapshot = create_snapshot(self.store, actor.tenant_id, export_id)
            content, manifest_hash, partial = build_export(snapshot, state["body"]["formats"])
            if partial and not state["body"]["allow_partial"]:
                raise ExportRejected("REPORT_NOT_FINALIZABLE")
            return self.store.complete(actor.tenant_id, export_id, content, manifest_hash, partial)
        except ExportRejected as exc:
            self.store.defer(actor.tenant_id, export_id, exc.code, now=now)
            return self.store.get(actor.tenant_id, export_id)

    def authorize_download(self, actor, export_id, *, now):
        return self.store.authorize_download(actor, export_id, now=now)
