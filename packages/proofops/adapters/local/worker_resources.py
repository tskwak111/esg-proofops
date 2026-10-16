"""Validated runtime caps; native reader bytes and all evidence policies stay fixed."""

import atexit
import os
import re
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal, InvalidOperation
from multiprocessing import get_context
from pathlib import Path
from threading import Lock

PROFILE = "worker-resources-s5-v1"
_pool = None
_pool_lock = Lock()


def close_ocr_pool():
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=True)
            _pool = None


atexit.register(close_ocr_pool)


def shared_ocr_pool():
    """One pool per isolated S5 worker process, shared across reader contexts."""
    global _pool
    workers = ocr_workers()
    with _pool_lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn"))
        elif _pool._max_workers != workers:
            raise ValueError("WORKER_RESOURCE_RUNTIME_CHANGED")
        return _pool


def enabled():
    return os.environ.get("PROOFOPS_RESOURCE_PROFILE") == PROFILE


def resource_settings():
    def integer(name, default, maximum):
        raw = os.environ.get(name, str(default))
        if not re.fullmatch(r"[1-9][0-9]*", raw) or not 1 <= int(raw) <= maximum:
            raise ValueError("WORKER_RESOURCE_SETTING_INVALID")
        return int(raw)

    try:
        cpus = Decimal(os.environ.get("PROOFOPS_WORKER_CPUS", "1.5"))
        if not cpus.is_finite() or not Decimal(".25") <= cpus <= 64:
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError("WORKER_RESOURCE_SETTING_INVALID") from None
    memory = os.environ.get("PROOFOPS_WORKER_MEMORY", "2560m")
    if not re.fullmatch(r"[1-9][0-9]*[mg]", memory):
        raise ValueError("WORKER_RESOURCE_SETTING_INVALID")
    return dict(
        profile=PROFILE,
        worker_cpus=str(cpus),
        worker_memory=memory,
        ocr_processes=integer("PROOFOPS_OCR_PROCESSES", 2, 4),
        pdfium_workers=integer("PROOFOPS_PDFIUM_WORKERS", 4, 4),
        omp_threads=1,
    )


def resource_snapshot():
    result = resource_settings()
    # Requested configuration and actual cgroup ceilings are separate evidence.
    result["cgroup"] = {}
    for name in ("cpu.max", "memory.max"):
        path = Path("/sys/fs/cgroup") / name
        if path.is_file():
            result["cgroup"][name] = path.read_text().strip()
    return result


def ocr_workers():
    if enabled():
        return resource_settings()["ocr_processes"]
    return 2


def apply_resources():
    settings = resource_settings()
    os.environ.update(
        PROOFOPS_RESOURCE_PROFILE=PROFILE,
        PROOFOPS_WORKER_CPUS=settings["worker_cpus"],
        PROOFOPS_WORKER_MEMORY=settings["worker_memory"],
        PROOFOPS_OCR_PROCESSES=str(settings["ocr_processes"]),
        PROOFOPS_PDFIUM_WORKERS=str(settings["pdfium_workers"]),
        PROOFOPS_DISPLAY_PREFETCH_WORKERS=str(settings["pdfium_workers"]),
    )
    # LocalRasterReader pins Tesseract to OMP_THREAD_LIMIT=1 independently.
    return resource_snapshot()
