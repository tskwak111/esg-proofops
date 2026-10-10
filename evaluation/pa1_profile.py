"""PA1 private measurement wrapper around the hosted subprocess entry point."""

import atexit
import cProfile
import functools
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path


def main():
    from proofops.adapters.local import upstage_ocr_page
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.upstage_parse import UpstageParseProbe
    from proofops_api import hosted_analysis

    from evaluation import hosted_r108

    output = Path(os.environ["PA1_PROFILE_DIR"])
    events = []
    exceptions = []
    lock = threading.Lock()

    def instrument(owner, name, label):
        original = getattr(owner, name)

        @functools.wraps(original)
        def measured(*args, **kwargs):
            start = time.monotonic()
            error = None
            try:
                return original(*args, **kwargs)
            except BaseException as exc:
                error = type(exc).__name__
                raise
            finally:
                with lock:
                    events.append(
                        dict(
                            function=label,
                            start=start,
                            seconds=time.monotonic() - start,
                            thread=threading.get_ident(),
                            error=error,
                        )
                    )

        setattr(owner, name, measured)

    for owner, name, label in (
        (OpenAIProbe, "_post", "openai.transport"),
        (UpstageParseProbe, "_post_parse", "parse.post"),
        (UpstageParseProbe, "_async_status", "parse.poll"),
        (UpstageParseProbe, "_download", "parse.download"),
        (upstage_ocr_page, "post_png", "ocr.transport"),
        (upstage_ocr_page, "render_page", "ocr.render"),
        (upstage_ocr_page.PageOCRStore, "fetch", "ocr.fetch"),
    ):
        if hasattr(owner, name):
            instrument(owner, name, label)
    # hosted_ocr imported the function by value before this instrumentation.
    from proofops_api import hosted_ocr

    hosted_ocr.post_png = upstage_ocr_page.post_png
    hosted_analysis.ANALYSIS_TIMEOUT_SECONDS = 5400
    profiler = cProfile.Profile()
    profiler.enable()

    def trace(frame, event, arg):
        if event == "exception" and "proofops_worker/local_runner.py" in frame.f_code.co_filename:
            typ, value, _ = arg
            code = str(value)
            exceptions.append(
                dict(
                    line=frame.f_lineno,
                    type=typ.__name__,
                    code=code if re.fullmatch(r"[A-Z0-9_]+", code) else "REDACTED",
                )
            )
            stderr = getattr(value, "stderr_path", None)
            if stderr is not None and stderr.is_file():
                (output / "parser-private-stderr.txt").write_bytes(stderr.read_bytes())
        return trace

    if os.environ.get("PA1_TRACE_SETUP") == "true":
        sys.settrace(trace)

    def save():
        profiler.disable()
        profiler.dump_stats(str(output / "main-thread.prof"))
        (output / "function-events.json").write_text(json.dumps(events))
        (output / "exceptions.json").write_text(json.dumps(exceptions))
        state = Path(sys.argv[-1]) / "state"
        if state.is_dir():
            shutil.copytree(state, output / "retained-state", dirs_exist_ok=True)

    atexit.register(save)
    hosted_r108.main()


if __name__ == "__main__":
    main()
