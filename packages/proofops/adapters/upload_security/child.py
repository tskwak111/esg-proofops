"""CLI dispatch and code-only inspection failures for the isolated parser child."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from proofops.application.upload_contracts import (
    PdfLimits,
    UploadRejected,
)

from .display import _inspect_display
from .strict import _inspect_strict


def _inspect(path: str, limits: PdfLimits) -> int:
    if limits.policy_profile == "strict-v1":
        return cast(int, _inspect_strict(path, limits)["pages"])
    with TemporaryDirectory(prefix="proofops-display-") as temporary:
        return cast(int, _inspect_display(path, limits, Path(temporary) / "display.pdf")["pages"])


def main() -> None:
    import logging

    logging.disable(logging.CRITICAL)
    try:
        limits = PdfLimits(**json.loads(sys.argv[2]))
        if limits.policy_profile == "display-v2":
            with TemporaryDirectory(prefix="proofops-display-cli-") as scratch:
                output = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(scratch) / "display.pdf"
                security = _inspect_display(sys.argv[1], limits, output)
                print(
                    json.dumps(
                        {"code": "verified", "pages": security["pages"], "security": security}
                    )
                )
        else:
            with TemporaryDirectory(prefix="proofops-strict-cli-") as scratch:
                output = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(scratch) / "decrypted.pdf"
                print(json.dumps(_inspect_strict(sys.argv[1], limits, output)))
    except MemoryError:
        print('{"code":"UPLOAD_LIMIT_EXCEEDED"}')
    except Exception as error:
        from pypdf.errors import LimitReachedError

        code = (
            "UPLOAD_LIMIT_EXCEEDED"
            if isinstance(error, MemoryError | LimitReachedError)
            else str(error)
            if isinstance(error, UploadRejected)
            else "PDF_INVALID"
        )
        failure: dict[str, Any] = {"code": code}
        if isinstance(error, UploadRejected) and error.security_metadata:
            failure["security"] = error.security_metadata
        if sys.platform != "win32":
            import resource

            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            failure.setdefault("security", {})["peak_rss_bytes"] = (
                peak if sys.platform == "darwin" else peak * 1024
            )
        print(json.dumps(failure))
