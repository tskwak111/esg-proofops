"""Standalone experiment backend with receipts proving actual Docling completion.

Runs in the isolated ODL environment, not in the application dependency environment.
"""

from __future__ import annotations

import argparse
import json
import time
from contextlib import asynccontextmanager
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path


class RecordingConverter:
    def __init__(self, inner, receipt: Path, allowed: set[int]):
        self.inner, self.receipt, self.allowed = inner, receipt, allowed

    def convert(self, path, *, page_range=None):
        started = time.monotonic()
        record = {
            "schema": "docling-receipt-v1",
            "status": "started",
            "source_sha256": sha256(Path(path).read_bytes()).hexdigest(),
            "received_page_range": page_range,
        }
        self.receipt.write_text(json.dumps(record), encoding="utf-8")
        try:
            if page_range is None and self.allowed:
                first, last = min(self.allowed), max(self.allowed)
                if self.allowed == set(range(first, last + 1)):
                    page_range = (first, last)
                    record["range_override"] = "explicit_experiment_pages"
            record["page_range"] = page_range
            if (
                not page_range
                or page_range[0] > page_range[1]
                or not set(range(page_range[0], page_range[1] + 1)) <= self.allowed
            ):
                raise ValueError("UNEXPECTED_BACKEND_PAGE_RANGE")
            result = self.inner.convert(path, page_range=page_range)
            document = result.document.export_to_dict()
            raw = json.dumps(document, ensure_ascii=True).encode()
            raw_path = self.receipt.with_name("docling-document.json")
            raw_path.write_bytes(raw)
            record.update(
                status=result.status.value,
                document_sha256=sha256(raw).hexdigest(),
                pages=sorted(map(int, document.get("pages", {}))),
                docling_version=version("docling"),
            )
            return result
        except Exception as error:
            record.update(status="failed", reason=type(error).__name__ + ": " + str(error))
            raise
        finally:
            record["processing_seconds"] = time.monotonic() - started
            self.receipt.write_text(
                json.dumps(record, ensure_ascii=True, indent=2), encoding="utf-8"
            )


def main():
    import uvicorn
    from opendataloader_pdf import hybrid_server

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--pages", required=True)
    args = parser.parse_args()
    allowed = set(map(int, args.pages.split(",")))
    app = hybrid_server.create_app(ocr_lang=["ko", "en"])
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            hybrid_server.converter = RecordingConverter(
                hybrid_server.converter, args.receipt, allowed
            )
            yield

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
