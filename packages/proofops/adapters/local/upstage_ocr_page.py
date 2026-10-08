"""Pinned synchronous PNG-only OCR, tenant page cache and trusted collection store.

The SQLite ledger is private trusted storage. Hashes bind collected bytes; they
are not signatures by the provider. Replay never accepts caller supplied OCR.
"""

from __future__ import annotations

import fcntl
import http.client
import io
import json
import math
import os
import sqlite3
import time
from contextlib import closing
from decimal import Decimal
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import pypdfium2 as pdfium
from PIL import Image

from proofops.adapters.local.upstage import PRICE_RECHECK_AT, UpstageProbe
from proofops.domain.provenance import canonical_hash

PROFILE = "upstage-ocr-page-v1"
MODEL = "ocr-260930"
COST = Decimal("0.00165")  # USD0.0015/page +10% VAT; checked 2026-10-09.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000
TOL = 0.001  # Existing PDF coordinate quantization, in points.


def reader_policy():
    from proofops.application.evidence import citations

    return dict(
        profile=PROFILE,
        model=MODEL,
        api_version="1.1",
        dpi=216,
        renderer="PDFium",
        renderer_version=version("pypdfium2"),
        reader_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        mapping_sha256=canonical_hash(
            dict(algorithm="whole-polygon-provider-order-v1", tolerance_pt=TOL)
        ),
        normalization_sha256=sha256(Path(citations.__file__).read_bytes()).hexdigest(),
        max_pixels=MAX_PIXELS,
        max_png_bytes=50 * 1024 * 1024,
    )


def render_page(source: bytes, page_num: int):
    if (
        not isinstance(source, bytes)
        or not source
        or len(source) > 100 * 1024 * 1024
        or type(page_num) is not int
    ):
        raise ValueError("OCR_SOURCE_INVALID")
    with pdfium.PdfDocument(source) as doc:
        if not 1 <= page_num <= len(doc):
            raise ValueError("OCR_PAGE_INVALID")
        with closing(doc[page_num - 1]) as page:
            w, h = page.get_size()
            crop = list(page.get_cropbox())
            media = list(page.get_mediabox())
            if page.get_rotation() or crop[:2] != [0, 0] or page.get_bbox()[:2] != (0, 0):
                raise ValueError("OCR_GEOMETRY_UNSUPPORTED")
            if w * h * 9 > MAX_PIXELS:
                raise ValueError("OCR_RENDER_LIMIT")
            with closing(page.render(scale=3)) as bitmap:
                image = bitmap.to_pil()
                try:
                    buf = io.BytesIO()
                    image.save(buf, format="PNG")
                    size = list(image.size)
                finally:
                    image.close()
    png = buf.getvalue()
    if len(png) > 50 * 1024 * 1024:
        raise ValueError("OCR_RENDER_LIMIT")
    manifest = dict(
        source_sha256=sha256(source).hexdigest(),
        physical_page=page_num,
        rotation=0,
        crop_box=crop,
        media_box=media,
        width_pt=w,
        height_pt=h,
        pixel_size=size,
        png_sha256=sha256(png).hexdigest(),
        renderer="PDFium",
        renderer_version=version("pypdfium2"),
        dpi=216,
    )
    return dict(manifest=manifest, png=png)


def _number(x):
    return type(x) in (int, float) and math.isfinite(x)


def parse_response(raw: bytes):
    try:
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError
        data = json.loads(raw)
        if (
            data["apiVersion"] != "1.1"
            or data["modelVersion"] != MODEL
            or type(data["numBilledPages"]) is not int
            or data["numBilledPages"] != 1
        ):
            raise ValueError
        pages = data["pages"]
        if not isinstance(pages, list) or len(pages) != 1:
            raise ValueError
        page = pages[0]
        w, h = page["width"], page["height"]
        if (
            not _number(w)
            or not _number(h)
            or not 0 < w <= MAX_PIXELS
            or not 0 < h <= MAX_PIXELS
            or w * h > MAX_PIXELS
        ):
            raise ValueError
        if (
            type(page["id"]) is not int
            or page["id"] != 0
            or not isinstance(page["words"], list)
            or len(page["words"]) > 50000
        ):
            raise ValueError
        words = []
        ids = set()
        chars = 0
        for order, word in enumerate(page["words"]):
            wid = word["id"]
            text = word["text"]
            confidence = word["confidence"]
            if (
                type(wid) is not int
                or wid < 0
                or wid in ids
                or not isinstance(text, str)
                or not _number(confidence)
                or not 0 <= confidence <= 1
            ):
                raise ValueError
            ids.add(wid)
            chars += len(text)
            vertices = word["boundingBox"]["vertices"]
            if not isinstance(vertices, list) or len(vertices) != 4:
                raise ValueError
            polygon = []
            for v in vertices:
                x, y = v["x"], v["y"]
                if not _number(x) or not _number(y) or not 0 <= x <= w or not 0 <= y <= h:
                    raise ValueError
                polygon.append([x, y])
            if min(v[0] for v in polygon) >= max(v[0] for v in polygon) or min(
                v[1] for v in polygon
            ) >= max(v[1] for v in polygon):
                raise ValueError
            # Convex, clockwise TL->TR->BR->BL, no self-intersection.
            crosses = []
            for i in range(4):
                a, b, c = polygon[i], polygon[(i + 1) % 4], polygon[(i + 2) % 4]
                crosses.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
            if not all(c > 0 for c in crosses):
                raise ValueError
            words.append(
                dict(id=wid, text=text, confidence=confidence, polygon=polygon, order=order)
            )
        if chars > 200000:
            raise ValueError
        return dict(
            width=w,
            height=h,
            words=words,
            modelVersion=MODEL,
            apiVersion="1.1",
            stored=data.get("stored"),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("OCR_RESPONSE_INVALID") from None


def _bounds(polygon):
    return [
        min(p[0] for p in polygon),
        min(p[1] for p in polygon),
        max(p[0] for p in polygon),
        max(p[1] for p in polygon),
    ]


def _inside(poly, box):
    return all(
        box[0] - TOL <= p[0] <= box[2] + TOL and box[1] - TOL <= p[1] <= box[3] + TOL for p in poly
    )


def _overlap(a, b):
    return a[0] < b[2] - TOL and a[2] > b[0] + TOL and a[1] < b[3] - TOL and a[3] > b[1] + TOL


def map_words(response, manifest, box, *, competing_boxes=()):
    def hold(reason):
        return dict(status="unresolved", reason=reason, word_ids=[w["id"] for w in chosen])

    chosen = []
    if len(box) != 4 or any(not _number(x) for x in box) or box[0] >= box[2] or box[1] >= box[3]:
        return hold("ocr_invalid_box")
    peers = {tuple(b) for b in competing_boxes if tuple(b) != tuple(box)}
    for w in response["words"]:
        poly = [
            [
                p[0] * manifest["width_pt"] / response["width"],
                p[1] * manifest["height_pt"] / response["height"],
            ]
            for p in w["polygon"]
        ]
        bounds = _bounds(poly)
        if not _overlap(bounds, box):
            continue
        if not _inside(poly, box):
            return hold("ocr_boundary_ambiguous")
        if not w["text"]:
            return hold("ocr_unrecognized_word")
        if any(_overlap(bounds, b) for b in peers):
            return hold("ocr_block_overlap_ambiguous")
        # Detection polygons can tilt very slightly; pin a 0.001pt edge rule.
        if any(
            abs(poly[a][axis] - poly[b][axis]) > TOL
            for a, b, axis in [(0, 1, 1), (2, 3, 1), (0, 3, 0), (1, 2, 0)]
        ):
            return hold("ocr_word_rotation_ambiguous")
        if any(_overlap(bounds, v["bbox"]) for v in chosen):
            return hold("ocr_word_overlap_ambiguous")
        chosen.append(dict(**w, bbox=bounds, pdf_polygon=poly))
    if not chosen:
        return hold("ocr_no_words")
    # Keep provider sequence. Do not reorder a multi-column/ambiguous reading.
    for left, right in zip(chosen, chosen[1:]):
        a, b = left["bbox"], right["bbox"]
        same = min(a[3], b[3]) - max(a[1], b[1]) >= 0.5 * min(a[3] - a[1], b[3] - b[1])
        if (same and b[0] < a[2] - TOL) or (not same and b[1] < a[3] - TOL):
            return hold("ocr_order_ambiguous")
    return dict(
        status="read",
        text=" ".join(w["text"] for w in chosen),
        word_ids=[w["id"] for w in chosen],
        words=chosen,
        coordinate_transform=dict(
            x=manifest["width_pt"] / response["width"], y=manifest["height_pt"] / response["height"]
        ),
    )


def post_png(png):
    from datetime import UTC, datetime

    if datetime.now(UTC) >= PRICE_RECHECK_AT:
        raise ValueError("PRICE_RECHECK_REQUIRED")
    key = os.environ.get("UPSTAGE_API_KEY", "")
    if not key or any(c.isspace() for c in key):
        raise ValueError("UPSTAGE_API_KEY_MISSING_OR_INVALID")
    boundary = uuid4().hex
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
            f"{MODEL}\r\n--{boundary}\r\nContent-Disposition: form-data; "
            'name="document"; filename="page.png"\r\nContent-Type: image/png\r\n\r\n'
        ).encode()
        + png
        + f"\r\n--{boundary}--\r\n".encode()
    )
    connection = http.client.HTTPSConnection("api.upstage.ai", timeout=60)
    try:
        connection.request(
            "POST",
            "/v1/document-digitization",
            body=body,
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        r = connection.getresponse()
        if r.status != 200:
            raise ValueError(f"UPSTAGE_HTTP_{r.status}")
        raw = r.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("OCR_RESPONSE_TOO_LARGE")
        return raw, r.getheader("x-request-id") or r.getheader("request-id")
    except (OSError, http.client.HTTPException):
        raise ValueError("UPSTAGE_OCR_REQUEST_FAILED") from None
    finally:
        connection.close()


class PageOCRStore:
    def __init__(
        self,
        ledger: Path,
        spend: Path,
        *,
        transport=post_png,
        cap_usd=Decimal("0.50"),
        max_calls=36,
    ):
        self.ledger, self.spend = Path(ledger), Path(spend)
        if not self.ledger.is_file() or not self.spend.is_file():
            raise ValueError("OCR_SHARED_LEDGER_REQUIRED")
        if (
            not cap_usd.is_finite()
            or not 0 < cap_usd <= Decimal("0.50")
            or type(max_calls) is not int
            or not 1 <= max_calls <= 36
        ):
            raise ValueError("OCR_LIMIT_INVALID")
        self.transport, self.cap_usd, self.max_calls = transport, cap_usd, max_calls
        with sqlite3.connect(self.ledger) as db:
            UpstageProbe._authorized_limit(db)
            db.execute(
                "CREATE TABLE IF NOT EXISTS ocr_calls (request_id TEXT PRIMARY KEY,"
                "tenant TEXT NOT NULL,cache_key TEXT NOT NULL,committed TEXT NOT NULL,"
                "state TEXT NOT NULL,collection TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS ocr_page_cache (tenant TEXT NOT NULL,"
                "cache_key TEXT NOT NULL,request_id TEXT NOT NULL,PRIMARY KEY(tenant,cache_key))"
            )
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS ocr_collection_immutable "
                "BEFORE UPDATE ON ocr_calls WHEN OLD.collection IS NOT NULL "
                "BEGIN SELECT RAISE(ABORT,'immutable OCR collection'); END"
            )
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS ocr_reservation_no_delete "
                "BEFORE DELETE ON ocr_calls "
                "BEGIN SELECT RAISE(ABORT,'retained OCR reservation'); END"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS ocr_response_bytes "
                "(request_id TEXT PRIMARY KEY,body BLOB NOT NULL,sha256 TEXT NOT NULL)"
            )
            for action in ("UPDATE", "DELETE"):
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS ocr_response_no_{action.lower()} "
                    f"BEFORE {action} ON ocr_response_bytes "
                    "BEGIN SELECT RAISE(ABORT,'immutable OCR response'); END"
                )
        self.ledger.chmod(0o600)

    @classmethod
    def from_env(cls):
        root = Path(__file__).resolve().parents[4]
        return cls(
            Path(os.environ.get("UPSTAGE_OCR_LEDGER", str(root / ".local/upstage/budget.sqlite3"))),
            Path(
                os.environ.get(
                    "R108_SPEND_PATH",
                    str(
                        root / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json"
                    ),
                )
            ),
        )

    def usage(self):
        with sqlite3.connect(self.ledger) as db:
            rows = db.execute("SELECT committed,state FROM ocr_calls").fetchall()
        return dict(
            calls=len(rows),
            unsettled_calls=sum(s != "collected" for _, s in rows),
            committed_or_reserved_usd=str(sum((Decimal(c) for c, _ in rows), Decimal(0))),
        )

    def _reserve(self, image, tenant_id, run_id, force):
        manifest = image["manifest"]
        if not image["png"].startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("OCR_PNG_REQUIRED")
        with Image.open(io.BytesIO(image["png"])) as png_image:
            if list(png_image.size) != manifest["pixel_size"] or (
                png_image.width * png_image.height > MAX_PIXELS
            ):
                raise ValueError("OCR_IMAGE_IDENTITY_INVALID")
            png_image.verify()
        if (
            not tenant_id
            or not run_id
            or sha256(image["png"]).hexdigest() != manifest["png_sha256"]
        ):
            raise ValueError("OCR_REQUEST_INVALID")
        key = canonical_hash(dict(manifest=manifest, policy=reader_policy()))
        # This lock is shared with the R108 decisions/finals transports. JSON
        # goes first: a crash before SQLite commit retains a conservative orphan.
        with self.spend.with_suffix(".decisions.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with sqlite3.connect(self.ledger, timeout=10) as db:
                db.execute("BEGIN IMMEDIATE")
                if not force:
                    row = db.execute(
                        "SELECT request_id FROM ocr_page_cache WHERE tenant=? AND cache_key=?",
                        (tenant_id, key),
                    ).fetchone()
                    if row:
                        return row[0], False
                total = UpstageProbe._call_total(db)
                count = db.execute("SELECT COUNT(*) FROM ocr_calls").fetchone()[0]
                own_total = sum(
                    (Decimal(r[0]) for r in db.execute("SELECT committed FROM ocr_calls")),
                    Decimal(0),
                )
                if (
                    total + COST > UpstageProbe._authorized_limit(db)
                    or count >= self.max_calls
                    or own_total + COST > self.cap_usd
                ):
                    raise ValueError("OCR_BUDGET_EXHAUSTED")
                data = json.loads(self.spend.read_text())
                limit = Decimal(data["limit_usd"])
                spent = Decimal(data["cumulative_usd"])
                if (
                    not limit.is_finite()
                    or not 0 < limit <= 10
                    or not spent.is_finite()
                    or spent < 0
                ):
                    raise ValueError("R108_BUDGET_INVALID")
                if spent + COST > limit:
                    raise ValueError("R108_BUDGET_EXHAUSTED")
                request_id = "ocr:" + str(uuid4())
                entries = data.setdefault("ocr_reservations", {})
                if (
                    len(entries) >= self.max_calls
                    or sum((Decimal(e["committed_usd"]) for e in entries.values()), Decimal(0))
                    + COST
                    > self.cap_usd
                ):
                    raise ValueError("OCR_BUDGET_EXHAUSTED")
                entries[request_id] = dict(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    signature=key,
                    committed_usd=str(COST),
                    state="reserved",
                    ledger=str(self.ledger),
                )
                data["cumulative_usd"] = str(spent + COST)
                temp = self.spend.with_name(self.spend.name + ".ocr-" + uuid4().hex + ".tmp")
                with temp.open("x") as f:
                    json.dump(data, f, sort_keys=True, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                temp.chmod(0o600)
                temp.replace(self.spend)
                db.execute(
                    "INSERT INTO ocr_calls VALUES (?,?,?,?,?,NULL)",
                    (request_id, tenant_id, key, str(COST), "pending"),
                )
                if not force:
                    db.execute(
                        "INSERT INTO ocr_page_cache VALUES (?,?,?)", (tenant_id, key, request_id)
                    )
                return request_id, True

    def fetch(self, image, *, tenant_id, run_id, force=False):
        rid, owner = self._reserve(image, tenant_id, run_id, force)
        if owner:
            started = time.monotonic()
            try:
                raw, provider_id = self.transport(image["png"])
                with sqlite3.connect(self.ledger) as db:
                    db.execute(
                        "INSERT INTO ocr_response_bytes VALUES (?,?,?)",
                        (rid, raw, sha256(raw).hexdigest()),
                    )
                parsed = parse_response(raw)
                collection = dict(
                    schema="upstage_ocr_collection_v1",
                    request_id=rid,
                    provider_request_id=provider_id,
                    tenant_id=tenant_id,
                    collected_run_id=run_id,
                    manifest=image["manifest"],
                    policy=reader_policy(),
                    response_hex=raw.hex(),
                    response_sha256=sha256(raw).hexdigest(),
                    derived_sha256=canonical_hash(parsed),
                    latency_seconds=time.monotonic() - started,
                )
                collection["artifact_sha256"] = canonical_hash(collection)
                with sqlite3.connect(self.ledger) as db:
                    if (
                        db.execute(
                            "UPDATE ocr_calls SET state='collected',collection=? "
                            "WHERE request_id=? AND state='pending' AND collection IS NULL",
                            (json.dumps(collection, sort_keys=True), rid),
                        ).rowcount
                        != 1
                    ):
                        raise ValueError("OCR_COLLECTION_CONFLICT")
                return collection
            except Exception as error:
                with sqlite3.connect(self.ledger) as db:
                    db.execute(
                        "UPDATE ocr_calls SET state='failed' "
                        "WHERE request_id=? AND state='pending'",
                        (rid,),
                    )
                # Only our fixed error vocabulary is exposed, never provider
                # response text, HTTP headers, credentials or arbitrary exceptions.
                code = str(error) if isinstance(error, ValueError) else type(error).__name__
                allowed = code.startswith(("OCR_", "UPSTAGE_HTTP_", "UPSTAGE_OCR_", "PRICE_"))
                detail = code if allowed and code.replace("_", "").isalnum() else "invalid_response"
                raise ValueError("OCR_COLLECTION_FAILED_RESERVATION_RETAINED:" + detail) from None
        deadline = time.monotonic() + 65
        while True:
            with sqlite3.connect(self.ledger) as db:
                row = db.execute(
                    "SELECT state,collection FROM ocr_calls WHERE request_id=? AND tenant=?",
                    (rid, tenant_id),
                ).fetchone()
            if row and row[0] == "collected":
                return self.validate(json.loads(row[1]), image, tenant_id=tenant_id)
            if not row or row[0] != "pending" or time.monotonic() > deadline:
                raise ValueError("OCR_PENDING_OR_FAILED")
            time.sleep(0.05)

    def validate(self, collection, image, *, tenant_id):
        try:
            with sqlite3.connect(self.ledger.resolve().as_uri() + "?mode=ro", uri=True) as db:
                row = db.execute(
                    "SELECT collection FROM ocr_calls "
                    "WHERE request_id=? AND tenant=? AND state='collected'",
                    (collection["request_id"], tenant_id),
                ).fetchone()
            if (
                row is None
                or json.loads(row[0]) != collection
                or collection["tenant_id"] != tenant_id
                or collection["manifest"] != image["manifest"]
                or collection["policy"] != reader_policy()
            ):
                raise ValueError
            raw = bytes.fromhex(collection["response_hex"])
            if (
                sha256(image["png"]).hexdigest() != image["manifest"]["png_sha256"]
                or sha256(raw).hexdigest() != collection["response_sha256"]
                or canonical_hash(parse_response(raw)) != collection["derived_sha256"]
                or canonical_hash({k: v for k, v in collection.items() if k != "artifact_sha256"})
                != collection["artifact_sha256"]
            ):
                raise ValueError
            return collection
        except (KeyError, TypeError, ValueError, sqlite3.Error):
            raise ValueError("OCR_COLLECTION_UNTRUSTED") from None
