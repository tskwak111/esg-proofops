"""Bounded child execution, cleanup and sanitized launcher environment."""

from __future__ import annotations

import math
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from proofops.adapters.parsing.odl_parts.common import ParseFailure, _output_bytes
from proofops.adapters.parsing.windows_isolation import IsolationUnavailable


def execute(command, work, env, profile, *, isolate, check_limits, reap):
    deadline = monotonic() + profile.timeout_seconds
    cpu_seconds = max(1, math.ceil(profile.timeout_seconds))
    try:
        isolation = isolate(memory_bytes=profile.memory_bytes, cpu_seconds=cpu_seconds)
    except IsolationUnavailable:
        # Containment is not optional: refuse to parse rather than run loose.
        raise ParseFailure("PARSER_ISOLATION_UNAVAILABLE") from None
    try:
        with isolation.spawn(command, cwd=work, env=env) as process:
            try:
                while process.poll() is None:
                    if monotonic() >= deadline:
                        raise ParseFailure("PARSER_TIMEOUT")
                    check_limits(isolation, process, work, profile)
                    try:
                        process.wait(timeout=min(0.05, max(0.001, deadline - monotonic())))
                    except subprocess.TimeoutExpired:
                        pass
                # A child can allocate or write past a limit and exit between
                # two samples; the breach is still a breach, so sample once
                # more now that the outcome is final.
                check_limits(isolation, process, work, profile)
                if process.returncode:
                    stderr = b""
                    for name in ("parser-stderr.txt", "launcher-stderr.txt"):
                        path = work / name
                        if path.is_file():
                            with path.open("rb") as handle:
                                stderr += handle.read(65536)
                    diagnostic = work.parent / (".parser-failure-" + uuid4().hex)
                    diagnostic.mkdir(mode=0o700)
                    target = diagnostic / "stderr.txt"
                    target.write_bytes(stderr[:65536])
                    target.chmod(0o600)
                    code = (
                        "PARSER_JAVA_HEAP_EXHAUSTED"
                        if b"java.lang.OutOfMemoryError: Java heap space" in stderr
                        else "PARSER_NATIVE_TEXT_UNREADABLE"
                        if b"pdfplumber.utils.exceptions.PdfminerException: Unexpected EOF"
                        in stderr
                        else "PARSER_FAILED"
                    )
                    failure = ParseFailure(code)
                    failure.stderr_path = target
                    raise failure
            finally:
                try:
                    isolation.terminate_tree(process)
                finally:
                    reap(process)
    except IsolationUnavailable:
        raise ParseFailure("PARSER_ISOLATION_UNAVAILABLE") from None
    finally:
        isolation.close()


def _cleanup_parser_work(temporary, parent: Path, *, timeout_seconds: float = 15) -> None:
    deadline = monotonic() + timeout_seconds
    parent = parent.resolve()
    while True:
        target = Path(temporary.name).resolve()
        if target.parent != parent or not target.name.startswith(".parse-"):
            raise ValueError("parser cleanup target outside its artifact parent")
        try:
            temporary.cleanup()
            return
        except PermissionError:
            # Job termination is asynchronous. Windows may retain a descendant's
            # file handles briefly even after the job's active count reaches zero.
            # Retry only this owned scratch directory, with a fixed deadline.
            if sys.platform != "win32" or monotonic() >= deadline:
                raise
            sleep(0.01)


@contextmanager
def _parser_work_directory(parent: Path):
    temporary = TemporaryDirectory(prefix=".parse-", dir=parent)
    try:
        yield Path(temporary.name)
    finally:
        _cleanup_parser_work(temporary, parent)


def _check_limits(isolation, process, work: Path, profile) -> None:
    if _output_bytes(work) > profile.max_output_bytes:
        raise ParseFailure("PARSER_OUTPUT_LIMIT")
    if isolation.memory_limit_exceeded(process):
        raise ParseFailure("PARSER_MEMORY_LIMIT")


def _child_limits(profile: dict[str, Any]) -> None:
    """Self-imposed limits inside the launcher.

    POSIX keeps the original hard rlimits. On Windows the same CPU and memory
    ceilings are already enforced by the job object the parent assigned before
    this process was resumed, so the only thing left to do here is suppress the
    crash dialog that would otherwise hold a terminated parse open forever;
    `RLIMIT_FSIZE` has no Windows analogue and the parent's output watchdog is
    what bounds written bytes on both platforms.
    """
    cpu = max(1, math.ceil(profile["timeout_seconds"]))
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(
            resource.RLIMIT_FSIZE, (profile["max_output_bytes"], profile["max_output_bytes"])
        )
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        return
    import ctypes

    # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
    ctypes.WinDLL("kernel32", use_last_error=True).SetErrorMode(0x0001 | 0x0002 | 0x8000)


def _child_environment(java: str, work: Path, profile) -> dict[str, str]:
    """The minimal environment the launcher and its JVM need, and nothing else.

    The inherited environment is never passed through on either platform. On
    Windows a JVM additionally needs `SystemRoot` and the system directory to
    resolve core DLLs, and the temporary directory is pinned inside the
    per-parse work directory so scratch files stay under the output watchdog.
    """
    heap = f"-Xmx{max(1, profile.memory_bytes // (2 * 1024 * 1024))}m"
    if sys.platform != "win32":
        return {
            "PATH": str(Path(java).parent) + ":/usr/bin:/bin",
            "JAVA_TOOL_OPTIONS": heap,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    system32 = str(Path(system_root) / "System32")
    return {
        "PATH": os.pathsep.join([str(Path(java).parent), system32, system_root]),
        "SystemRoot": system_root,
        "SystemDrive": os.environ.get("SystemDrive", "C:"),
        "ComSpec": os.environ.get("ComSpec", str(Path(system32) / "cmd.exe")),
        "NUMBER_OF_PROCESSORS": os.environ.get("NUMBER_OF_PROCESSORS", "1"),
        "TEMP": str(work),
        "TMP": str(work),
        "JAVA_TOOL_OPTIONS": heap,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
    }
