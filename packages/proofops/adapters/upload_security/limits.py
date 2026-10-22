"""Child-only OS resource limits; never call these in the API process."""

from __future__ import annotations

import sys
from pathlib import Path

from proofops.application.upload_contracts import (
    PdfLimits,
    UploadRejected,
)


def _windows_limits(limits: PdfLimits) -> int:
    """Attach this parser child to a fail-closed Windows Job Object.

    The returned OS handle is intentionally held until process exit. This helper
    must never be called in the API process. Layouts/flags follow Microsoft's
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION and JOBOBJECT_BASIC_LIMIT_INFORMATION.
    """
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_working_set", ctypes.c_size_t),
            ("max_working_set", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io_counters", ctypes.c_uint64 * 6),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise UploadRejected("PDF_INVALID")
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        kernel.CloseHandle(job)
        raise UploadRejected("PDF_INVALID")
    baseline = Extended()
    if not kernel.QueryInformationJobObject(
        job,
        9,
        ctypes.byref(baseline),
        ctypes.sizeof(baseline),
        None,
    ):
        kernel.CloseHandle(job)
        raise UploadRejected("PDF_INVALID")
    if baseline.peak_process_memory > limits.memory_bytes:
        kernel.CloseHandle(job)
        raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
    info = Extended()
    info.basic.process_time = limits.cpu_seconds * 10_000_000
    info.basic.active_processes = 1
    info.basic.flags = 0x00000002 | 0x00000008 | 0x00000100
    info.process_memory = limits.memory_bytes
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        kernel.CloseHandle(job)
        raise UploadRejected("PDF_INVALID")
    return job


def apply_basic_limits(limits: PdfLimits) -> None:
    """Restrict CPU, core dumps and output size before importing the PDF parser."""
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.max_bytes, limits.max_bytes))


def apply_parser_limits(limits: PdfLimits) -> None:
    """Keep Windows Job Objects and Linux address-space/process hard limits distinct.

    macOS has no equivalent hard memory limit here; its parent samples RSS.
    The trusted parser must already be loaded when this function is called.
    """
    if sys.platform == "win32":
        _windows_limits(limits)
    elif sys.platform == "linux":
        import resource

        current_vm = int(Path("/proc/self/statm").read_text().split()[0]) * resource.getpagesize()
        if current_vm > limits.memory_bytes:
            raise UploadRejected("UPLOAD_LIMIT_EXCEEDED")
        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
