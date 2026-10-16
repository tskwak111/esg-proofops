"""Bounded free OCR discovery using installed CPU readers, never SourceRefs.

All pages are original physical pages. Cache separates tenant, original/input SHA,
rendered pixels, rotation/CropBox, engine/config/policy; no paid transport here.
"""

from __future__ import annotations

import io
import json
import math
import platform
import subprocess
import tempfile
import time
from contextlib import closing
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

import pypdfium2 as pdfium
from proofops.domain.provenance import canonical_hash

POLICY = dict(
    version="scope-ocr-fallback-v1",
    dpi=108,
    max_pixels=4_000_000,
    max_text_chars=100_000,
    timeout_seconds=20,
    max_pages=24,
    front_back_pages=6,
    purpose="discovery_only",
    source_verified=False,
    ordering="front6_back6_then_remaining_physical_pages",
    cost_usd="0",
)
POLICY_SHA256 = canonical_hash(POLICY)


def discover(page_count, readable_pages, reader, *, source_sha256, max_pages=24, wall_seconds=60):
    if (
        type(page_count) is not int
        or not 1 <= page_count <= 300
        or type(max_pages) is not int
        or not 0 <= max_pages <= 300
        or type(wall_seconds) not in (int, float)
        or not 0 < wall_seconds <= 600
        or not isinstance(source_sha256, str)
        or len(source_sha256) != 64
    ):
        raise ValueError("invalid OCR discovery limits or source")
    readable = set(readable_pages)
    if any(type(p) is not int or not 1 <= p <= page_count for p in readable):
        raise ValueError("invalid readable physical page")
    ends = list(range(1, min(6, page_count) + 1)) + list(
        range(max(1, page_count - 5), page_count + 1)
    )
    order = list(dict.fromkeys(ends + list(range(1, page_count + 1))))
    missing = set(range(1, page_count + 1)) - readable
    attempted, records, texts, unresolved = [], [], {}, []
    started = time.monotonic()
    for p in order:
        if p not in missing:
            continue
        if len(attempted) >= max_pages or time.monotonic() - started >= wall_seconds:
            break
        attempted.append(p)
        try:
            row = reader(p)
            if (
                row.get("status") != "read"
                or row.get("physical_page") != p
                or row.get("source_sha256") != source_sha256
                or not isinstance(row.get("text"), str)
                or not row["text"].strip()
                or len(row["text"]) > POLICY["max_text_chars"]
                or not isinstance(row.get("image_sha256"), str)
                or len(row["image_sha256"]) != 64
                or not isinstance(row.get("reader_policy"), dict)
            ):
                raise ValueError("OCR_DISCOVERY_RECEIPT_INVALID")
            texts[p] = row["text"]
            records.append(dict(row, purpose="discovery_only", source_verified=False))
        except Exception as error:
            unresolved.append(p)
            records.append(
                dict(
                    physical_page=p,
                    status="unresolved",
                    purpose="discovery_only",
                    source_verified=False,
                    error_type=type(error).__name__,
                )
            )
    unsearched = sorted(missing - set(attempted))
    return dict(
        policy_sha256=POLICY_SHA256,
        source_sha256=source_sha256,
        texts=texts,
        attempted_pages=attempted,
        unsearched_pages=unsearched,
        unresolved_pages=sorted(unresolved),
        records=records,
        scope_incomplete=bool(unsearched or unresolved),
        cost_usd="0",
        wall_seconds=time.monotonic() - started,
        precision_verification="not_run",
    )


class CPUDiscoveryReader:
    """Reuse compiled Apple Vision or the existing pinned Linux OCR installation.

    The source reader is intentionally distinct from admission readers: rotated
    or cropped display pixels can be searched, but produce no trusted bbox.
    """

    def __init__(self, pdf, *, tenant_id, cache_dir, source_sha256=None):
        if not isinstance(tenant_id, str) or not tenant_id or len(tenant_id) > 200:
            raise ValueError("discovery tenant required")
        self.pdf = Path(pdf)
        if self.pdf.stat().st_size > 150 * 1024 * 1024:
            raise ValueError("discovery input byte cap")
        self.input_sha = sha256(self.pdf.read_bytes()).hexdigest()
        self.source_sha = source_sha256 or self.input_sha
        self.tenant_id = tenant_id
        self.cache = Path(cache_dir)
        self.cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.binary = None
        self.policy = dict(
            POLICY,
            renderer="PDFium",
            renderer_version=version("pypdfium2"),
            os=platform.platform(),
            adapter_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        )
        if platform.system() == "Darwin":
            import proofops.adapters.local as local
            from proofops.adapters.local.native_ocr_compiled import ensure_compiled_binary

            swift = Path(local.__file__).with_name("native_ocr.swift")
            self.binary = ensure_compiled_binary(swift, timeout_s=60)
            self.policy.update(
                engine="Apple Vision CPU",
                swift_sha256=sha256(swift.read_bytes()).hexdigest(),
                binary_sha256=sha256(self.binary.read_bytes()).hexdigest() if self.binary else None,
            )
        else:
            from proofops.adapters.local.local_raster_reader import runtime_policy

            self.policy.update(engine="pinned_tesseract", runtime=runtime_policy())

    def __call__(self, physical_page):
        if sha256(self.pdf.read_bytes()).hexdigest() != self.input_sha:
            raise ValueError("discovery input changed")
        with pdfium.PdfDocument(self.pdf) as doc, closing(doc[physical_page - 1]) as page:
            w, h = page.get_size()
            if not all(math.isfinite(v) and v > 0 for v in (w, h)):
                raise ValueError("discovery geometry invalid")
            scale = min(1.5, math.sqrt((POLICY["max_pixels"] - 10_000) / (w * h)))
            if scale < 0.1:
                raise ValueError("discovery pixel cap")
            geometry = dict(
                physical_page=physical_page,
                rotation=page.get_rotation(),
                crop_box=list(page.get_cropbox()),
                media_box=list(page.get_mediabox()),
                width_pt=w,
                height_pt=h,
                render_scale=scale,
                actual_dpi=scale * 72,
            )
            with (
                closing(page.render(scale=scale, draw_annots=True)) as bitmap,
                bitmap.to_pil() as image,
            ):
                if image.width * image.height > POLICY["max_pixels"]:
                    raise ValueError("discovery pixel cap")
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
        png = buffer.getvalue()
        key_data = dict(
            tenant_id=self.tenant_id,
            source_sha256=self.source_sha,
            input_sha256=self.input_sha,
            image_sha256=sha256(png).hexdigest(),
            geometry=geometry,
            reader_policy=self.policy,
            policy_sha256=POLICY_SHA256,
        )
        key = canonical_hash(key_data)
        path = self.cache / (key + ".json")
        if path.exists():
            cached = json.loads(path.read_text())
            if cached["key_data"] != key_data or cached["receipt_sha256"] != canonical_hash(
                cached["receipt"]
            ):
                raise ValueError("discovery cache identity mismatch")
            return cached["receipt"]
        started = time.monotonic()
        if platform.system() == "Darwin":
            if self.binary is None:
                raise ValueError("discovery CPU OCR unavailable")
            with tempfile.TemporaryDirectory(prefix="scope-discovery-") as temp:
                image_path = Path(temp) / "page.png"
                image_path.write_bytes(png)
                result = subprocess.run(
                    [str(self.binary), str(image_path)],
                    capture_output=True,
                    check=True,
                    timeout=POLICY["timeout_seconds"],
                )
            raw = json.loads(result.stdout)
            text = raw["text"]
            engine_result = {k: v for k, v in raw.items() if k != "text"}
        else:
            import shutil

            from proofops.adapters.local.local_raster_reader import TESSDATA

            if self.policy["runtime"]["status"] != "ready":
                raise ValueError("discovery CPU OCR unavailable")
            result = subprocess.run(
                [
                    shutil.which("tesseract"),
                    "stdin",
                    "stdout",
                    "--tessdata-dir",
                    str(TESSDATA),
                    "-l",
                    "kor+eng",
                    "--oem",
                    "1",
                    "--psm",
                    "6",
                ],
                input=png,
                capture_output=True,
                check=True,
                timeout=POLICY["timeout_seconds"],
                env={"LANG": "C.UTF-8", "OMP_THREAD_LIMIT": "1"},
            )
            text = result.stdout.decode("utf-8")
            engine_result = {}
        receipt = dict(
            status="read",
            text=text,
            physical_page=physical_page,
            source_sha256=self.source_sha,
            input_sha256=self.input_sha,
            tenant_id=self.tenant_id,
            image_sha256=sha256(png).hexdigest(),
            geometry=geometry,
            reader_policy=self.policy,
            engine_result=engine_result,
            purpose="discovery_only",
            source_verified=False,
            cost_usd="0",
            seconds=time.monotonic() - started,
        )
        if len(text) > POLICY["max_text_chars"]:
            raise ValueError("discovery text cap")
        with path.open("x") as stream:
            json.dump(
                dict(key_data=key_data, receipt=receipt, receipt_sha256=canonical_hash(receipt)),
                stream,
                ensure_ascii=False,
            )
        path.chmod(0o600)
        return receipt
