"""S5 configurable worker limits and one process-wide raw OCR pool."""

from concurrent.futures import ThreadPoolExecutor

import pytest


def test_resources_validate_and_old_ocr_defaults_ignore_new_env(monkeypatch):
    from proofops.adapters.local.worker_resources import ocr_workers, resource_settings

    monkeypatch.setenv("PROOFOPS_OCR_PROCESSES", "4")
    monkeypatch.setenv("PROOFOPS_PDFIUM_WORKERS", "2")
    assert ocr_workers() == 2
    monkeypatch.setenv("PROOFOPS_RESOURCE_PROFILE", "worker-resources-s5-v1")
    assert ocr_workers() == 4
    runtime = resource_settings()
    assert runtime["pdfium_workers"] == 2 and runtime["omp_threads"] == 1
    monkeypatch.setenv("PROOFOPS_OCR_PROCESSES", "0")
    with pytest.raises(ValueError, match="RESOURCE_SETTING_INVALID"):
        resource_settings()


def test_ocr_cap_is_shared_across_reader_contexts(monkeypatch):
    from proofops.adapters.local import worker_resources as runtime

    pools = []

    class Pool:
        def __init__(self, *, max_workers, mp_context):
            self._max_workers = max_workers
            pools.append(self)

        def shutdown(self, *, wait):
            pass

    monkeypatch.setattr(runtime, "ProcessPoolExecutor", Pool)
    monkeypatch.setenv("PROOFOPS_RESOURCE_PROFILE", runtime.PROFILE)
    monkeypatch.setenv("PROOFOPS_OCR_PROCESSES", "2")
    runtime.close_ocr_pool()
    try:
        with ThreadPoolExecutor(12) as threads:
            results = list(threads.map(lambda _: runtime.shared_ocr_pool(), range(12)))
        assert len(pools) == 1 and all(p is pools[0] for p in results)
        assert pools[0]._max_workers == 2
        monkeypatch.setenv("PROOFOPS_OCR_PROCESSES", "4")
        with pytest.raises(ValueError, match="RUNTIME_CHANGED"):
            runtime.shared_ocr_pool()
    finally:
        runtime.close_ocr_pool()


def test_cpu_memory_env_matches_compose_defaults_and_candidate():
    from pathlib import Path

    import yaml

    config = yaml.safe_load(Path("deploy/ec2/compose.yaml").read_text())["services"]["worker"]
    assert config["cpus"] == "${WORKER_CPUS:-1.5}"
    assert config["mem_limit"] == config["memswap_limit"] == "${WORKER_MEMORY:-2560m}"
    assert config["environment"]["PROOFOPS_WORKER_CPUS"] == config["cpus"]
    assert config["environment"]["PROOFOPS_WORKER_MEMORY"] == config["mem_limit"]
