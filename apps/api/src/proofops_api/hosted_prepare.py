"""Bounded selected-page preparation subprocess, with no network or provider input."""

from __future__ import annotations

import json
import resource
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def main() -> None:
    # Linux container supplies additional aggregate cgroup/CPU limits.
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    source, target, pages_json = sys.argv[1:]
    reader = PdfReader(source)
    writer = PdfWriter()
    for page in json.loads(pages_json):
        writer.add_page(reader.pages[page - 1])
    with Path(target).open("xb") as output:
        writer.write(output)


if __name__ == "__main__":
    main()
