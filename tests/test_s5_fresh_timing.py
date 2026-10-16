import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def timing(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("fresh_e2e_timing")


def test_observer_preserves_values_and_failures_without_logging_inputs(timing, monkeypatch):
    events = []
    monkeypatch.setitem(
        sys.modules,
        "predeploy_runtime_base",
        SimpleNamespace(audit=lambda event, **kw: events.append(dict(event=event, **kw))),
    )
    secret = object()
    module = SimpleNamespace(call=lambda value: value)
    timing.observe(module, "call", label="test.call")
    assert module.call(secret) is secret
    assert events[-1]["failed"] is False
    assert "args" not in events[-1]

    def fails():
        raise ValueError("private document text")

    module.call = fails
    timing.observe(module, "call", label="test.failure")
    with pytest.raises(ValueError, match="private document text"):
        module.call()
    assert events[-1]["failed"] is True
    assert "private document text" not in str(events)


def test_timing_reports_overlap_instead_of_adding_waits_as_wall_time(timing):
    events = [
        dict(event="function_timing", function="call", failed=False, started=a, seconds=b)
        for a, b in ((1, 3), (2, 4), (7, 1))
    ]
    result = timing.summarize(events)["functions"]["call"]
    assert result == dict(
        calls=3,
        failures=0,
        inclusive_seconds=8,
        max_seconds=4,
        wall_union_seconds=6,
        peak_concurrent=2,
    )


def test_fresh_harness_rejects_unbounded_extraction_batches(timing, tmp_path):
    gate = importlib.import_module("fresh_e2e_gate")
    for value in (0, 257, True, "256"):
        with pytest.raises(ValueError, match="FRESH_EXTRACTION_BATCH_INVALID"):
            gate.prepare(dict(extract_batch_calls=value), tmp_path, tmp_path / "fixtures")
