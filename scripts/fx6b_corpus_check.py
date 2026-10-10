"""Offline FX6b corpus check using the same bounded entry as HostedStore.upload_file."""

import argparse
import json
from collections import Counter
from dataclasses import asdict
from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from unicodedata import normalize

from proofops.application.uploads_security import PdfLimits, UploadRejected, verify_pdf_file


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    files = sorted(args.corpus.rglob("*.pdf"))
    assert len(files) == 50, len(files)
    limits = PdfLimits(max_bytes=150 * 1024**2, max_decoded_bytes=512 * 1024**2)
    code = Path(__file__).resolve().parents[1] / "packages/proofops/application/uploads_security.py"
    code_sha = digest(code)
    rows = []
    for number, path in enumerate(files, 1):
        source_sha, size = digest(path), path.stat().st_size
        security = {}
        start = monotonic()
        with TemporaryDirectory(prefix="fx6b-corpus-") as temporary:
            derived = Path(temporary) / "decrypted.pdf"
            try:
                pages = verify_pdf_file(
                    path,
                    limits,
                    expected_size=size,
                    expected_sha256=source_sha,
                    derived_path=derived,
                    security_metadata=security,
                )
                status = "verified"
            except UploadRejected as error:
                pages, status = None, str(error)
                security = error.security_metadata
            seconds = monotonic() - start
            if derived.exists() and status == "verified":
                assert digest(derived) == security["analysis_sha256"]
        row = dict(
            file=normalize("NFC", str(path.relative_to(args.corpus))),
            sha256=source_sha,
            size_bytes=size,
            pages=pages,
            code=status,
            seconds=round(seconds, 4),
            peak_rss_bytes=security.get("peak_rss_bytes"),
            security=security,
            original_sha256_unchanged=digest(path) == source_sha,
        )
        assert row["original_sha256_unchanged"]
        rows.append(row)
        result = dict(
            method="HostedStore.upload_file-equivalent verify_pdf_file; sequential; "
            "no network/model calls; macOS child ru_maxrss in bytes",
            limits=asdict(limits),
            validator_sha256=code_sha,
            files=rows,
            counts=dict(Counter(r["code"] for r in rows)),
        )
        (args.output / "corpus-results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        print(number, row["file"], status, row["seconds"], row["peak_rss_bytes"], flush=True)
    assert digest(code) == code_sha, "Validator changed during corpus check"
    table = [
        "# FX6b · 50개 원본 업로드 검증",
        "",
        "|파일|쪽|결과|처리 초|자식 최대 RSS MiB|",
        "|---|---:|---|---:|---:|",
    ]
    for row in rows:
        peak = row["peak_rss_bytes"]
        table.append(
            f"|{row['file']}|{row['pages'] or '-'}|{row['code']}|"
            f"{row['seconds']:.4f}|{peak / 1024**2:.2f}|"
            if peak
            else f"|{row['file']}|{row['pages'] or '-'}|{row['code']}|"
            f"{row['seconds']:.4f}|not_measured|"
        )
    (args.output / "corpus-table.md").write_text("\n".join(table) + "\n")
    print("COUNTS", result["counts"], flush=True)


if __name__ == "__main__":
    main()
