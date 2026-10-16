"""Offline-only isolated parser timer. Retains no PDF text or function arguments."""

import functools
import json
import sys
import time
from pathlib import Path


def main():
    import opendataloader_pdf
    import pdfplumber
    from proofops.adapters.parsing import odl_table_repair, opendataloader

    work = Path(sys.argv[1])
    records = []

    def observe(owner, name, label):
        original = getattr(owner, name)

        @functools.wraps(original)
        def timed(*args, **kwargs):
            started = time.monotonic()
            failed = True
            try:
                value = original(*args, **kwargs)
                failed = False
                return value
            finally:
                records.append(
                    dict(
                        function=label,
                        started=started,
                        seconds=time.monotonic() - started,
                        thread=0,
                        failed=failed,
                    )
                )

        setattr(owner, name, timed)

    observe(opendataloader_pdf, "convert", "spp.child.odl_java_start_and_execute")
    observe(pdfplumber, "open", "spp.child.pdfplumber_open")
    observe(pdfplumber.page.Page, "extract_words", "spp.child.extract_words")
    observe(pdfplumber.page.Page, "find_tables", "spp.child.find_tables")
    observe(odl_table_repair, "repair_stacked_headers", "spp.child.repair_stacked_headers")
    observe(odl_table_repair, "locate_auxiliary_cells", "spp.child.locate_auxiliary_cells")
    observe(opendataloader, "_locates_auxiliary_cells", "spp.child.reader_lookup")
    try:
        opendataloader._child(work)
    finally:
        (work / "spp-timing.json").write_text(json.dumps(records))


if __name__ == "__main__":
    main()
