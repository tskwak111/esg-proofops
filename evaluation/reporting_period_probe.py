"""Offline FX7 corpus census: native first/last 12 pages; no model transports."""

import argparse
import json
import time
from collections import Counter
from hashlib import file_digest
from pathlib import Path
from unicodedata import normalize

import pypdfium2 as pdfium

from evaluation.reporting_period import detect_reporting_period


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--corpus", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    start = time.monotonic()
    for pdf in sorted(args.corpus.rglob("*.pdf")):
        tick = time.monotonic()
        with pdf.open("rb") as stream:
            digest = file_digest(stream, "sha256").hexdigest()
        texts, issues = {}, []
        with pdfium.PdfDocument(pdf) as doc:
            count = len(doc)
            for page_num in sorted(
                set(range(1, min(12, count) + 1)) | set(range(max(1, count - 11), count + 1))
            ):
                page = doc[page_num - 1]
                tp = None
                try:
                    tp = page.get_textpage()
                    if tp.count_chars() > 100_000:
                        raise ValueError("page_character_limit")
                    texts[page_num] = tp.get_text_range()
                except Exception as error:
                    issues.append(dict(page=page_num, error=type(error).__name__))
                finally:
                    if tp is not None:
                        tp.close()
                    page.close()
        detection = detect_reporting_period(texts, count, digest)
        rows.append(
            dict(
                file=str(pdf),
                name=normalize("NFC", pdf.name),
                page_count=count,
                detection=detection,
                issues=issues,
                duration_s=round(time.monotonic() - tick, 3),
            )
        )
    summary = dict(
        count=len(rows),
        counts=dict(Counter(r["detection"]["status"] for r in rows)),
        duration_s=round(time.monotonic() - start, 3),
        provider_calls=0,
        cost_usd=0,
    )
    (args.output / "corpus.json").write_text(
        json.dumps(dict(summary=summary, reports=rows), ensure_ascii=False, indent=2)
    )
    lines = [
        "| 보고서 | 감지 상태 | 보고연도 | 시작 | 종료 | 원문 쪽 |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        d = row["detection"]
        v = d["selected"] or {}
        pages = (
            ",".join(
                str(p) for p in sorted({c["source_ref"]["physical_page"] for c in d["candidates"]})
            )
            or "—"
        )
        lines.append(
            f"| {row['name']} | {d['status']} | {v.get('report_year', '—')} "
            f"| {v.get('period_start', '—')} | {v.get('period_end', '—')} | {pages} |"
        )
    (args.output / "corpus-table.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
