"""Run one local CPU hybrid experiment and always stop its owned backend."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from proofops.adapters.parsing.windows_isolation import kill_and_reap, process_isolation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument(
        "--client-python",
        type=Path,
        help="Optional distinct environment for comparing Java client versions",
    )
    parser.add_argument("--client-version", choices=("2.0.0", "2.5.7"), default="2.0.0")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pages", default="105")
    parser.add_argument("--port", type=int, default=5057)
    args = parser.parse_args()
    selected = sorted(set(map(int, args.pages.split(","))))
    if not selected or selected[0] < 1 or selected != list(range(selected[0], selected[-1] + 1)):
        parser.error("hybrid pilot requires a contiguous positive page range")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with socket.socket() as check:
        check.bind(("127.0.0.1", args.port))
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATH",
            "PATHEXT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "HOME",
            "LOCALAPPDATA",
            "APPDATA",
        }
    }
    env.update(
        PYTHONUTF8="1",
        HF_HOME=str(output.parent / "model-cache"),
        HF_HUB_DISABLE_TELEMETRY="1",
        DOCLING_DEVICE="cpu",
        OMP_NUM_THREADS="4",
        TOKENIZERS_PARALLELISM="false",
    )
    owner = process_isolation(memory_bytes=8 * 1024**3, cpu_seconds=1200)
    process = None
    report = {
        "schema": "odl-hybrid-supervisor-v1",
        "host": "127.0.0.1",
        "port": args.port,
        "device": "cpu",
        "ocr_languages": ["ko", "en"],
        "backend_status": "starting",
        "client_status": "not_run",
    }
    try:
        process = owner.spawn(
            [
                str(args.python.resolve()),
                "-I",
                str(Path(__file__).with_name("odl_hybrid_backend.py").resolve()),
                "--port",
                str(args.port),
                "--receipt",
                str(output / "backend-receipt.json"),
                "--pages",
                args.pages,
            ],
            cwd=output,
            env=env,
        )
        deadline = time.monotonic() + 180
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"BACKEND_EXIT_{process.returncode}")
            try:
                with opener.open(f"http://127.0.0.1:{args.port}/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(1)
        else:
            raise RuntimeError("BACKEND_START_TIMEOUT")
        report["backend_status"] = "ready"
        print("Local hybrid backend ready; running selected pages", flush=True)
        command = [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "evaluation.odl_pilot",
            "--pdf",
            str(args.pdf.resolve()),
            "--output",
            str(output / "client"),
            "--pages",
            args.pages,
            "--candidate-python",
            str((args.client_python or args.python).resolve()),
            "--candidate-version",
            args.client_version,
            "--hybrid-url",
            f"http://127.0.0.1:{args.port}",
            "--hybrid-receipt",
            str(output / "backend-receipt.json"),
        ]
        with (output / "client.log").open("wb") as log:
            result = subprocess.run(command, stdout=log, stderr=log, timeout=660, check=False)
        report["client_status"] = "succeeded" if result.returncode == 0 else "failed"
        report["client_exit_code"] = result.returncode
    except Exception as error:
        report["reason"] = f"{type(error).__name__}: {error}"
        report["backend_status"] = "failed"
    finally:
        if process is not None:
            report["peak_backend_memory_bytes"] = owner.peak_memory_bytes(process)
            owner.terminate_tree(process)
            kill_and_reap(process)
        owner.close()
        report["backend_stopped"] = True
        (output / "supervisor.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["client_status"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
