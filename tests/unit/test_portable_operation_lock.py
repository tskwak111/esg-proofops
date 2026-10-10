"""Real kernel exclusion and offline transport budget checks on either host."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from proofops_agent.portable_lock import acquire_operation_lock

from tests.integration.test_upstage_tagging import configured


def _contend(path):
    return subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from pathlib import Path
from proofops_agent.portable_lock import acquire_operation_lock
try:
    lock = acquire_operation_lock(Path(sys.argv[1]))
except BlockingIOError:
    sys.exit(7)
lock.close()
""",
            str(path),
        ],
        capture_output=True,
        timeout=15,
    )


def test_concurrent_contenders_rejected_and_close_releases(tmp_path):
    path = tmp_path / "operation.lock"
    with acquire_operation_lock(path):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(_contend, [path] * 4))
        assert all(result.returncode == 7 for result in results), results
    assert _contend(path).returncode == 0


def test_crashed_holder_releases_kernel_lock(tmp_path):
    path = tmp_path / "operation.lock"
    with subprocess.Popen(
        [
            sys.executable,
            "-c",
            """
import sys
from pathlib import Path
from proofops_agent.portable_lock import acquire_operation_lock
lock = acquire_operation_lock(Path(sys.argv[1]))
print('ready', flush=True)
sys.stdin.read()
""",
            str(path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as holder:
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                ready = pool.submit(holder.stdout.readline)
                assert ready.result(timeout=15).strip() == "ready"
                assert _contend(path).returncode == 7
            finally:
                # Kill before joining a potentially blocked readiness reader.
                holder.kill()
                holder.wait(timeout=10)
    assert path.exists()
    assert _contend(path).returncode == 0


def test_busy_transport_never_dispatches_or_reserves(tmp_path, monkeypatch):
    adapter, probe, calls, request = configured(tmp_path, monkeypatch)
    with acquire_operation_lock(tmp_path / "receipts" / ".operation.lock"):
        result = adapter.invoke(request)
    assert result.usage.status == "failed"
    assert not calls and probe.summary()["calls"] == 0
    assert not (tmp_path / "receipts" / request["request_id"]).exists()


def test_transport_exception_releases_lock(tmp_path, monkeypatch):
    adapter, _, _, request = configured(tmp_path, monkeypatch)

    def fail(request):
        raise ValueError("offline failure")

    monkeypatch.setattr(adapter, "_invoke", fail)
    with pytest.raises(ValueError, match="offline failure"):
        adapter.invoke(request)
    assert _contend(tmp_path / "receipts" / ".operation.lock").returncode == 0


def test_missing_lock_backend_fails_before_creating_receipt(tmp_path, monkeypatch):
    adapter, probe, calls, request = configured(tmp_path, monkeypatch)
    module = "msvcrt" if sys.platform == "win32" else "fcntl"
    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(ModuleNotFoundError):
        adapter.invoke(request)
    assert not calls and probe.summary()["calls"] == 0
    assert not list((tmp_path / "receipts").iterdir())
