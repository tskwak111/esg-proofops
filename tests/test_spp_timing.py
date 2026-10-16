import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


def test_observer_keeps_static_parser_execute_descriptor(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    timing = importlib.import_module("fresh_e2e_timing")
    events = []
    monkeypatch.setitem(
        sys.modules,
        "predeploy_runtime_base",
        SimpleNamespace(audit=lambda event, **values: events.append(values)),
    )

    class Parser:
        @staticmethod
        def execute(value):
            return value

    timing.observe(Parser, "execute", label="isolated_parser")
    assert Parser.execute(7) == Parser().execute(7) == 7
    assert len(events) == 2
    assert all(
        set(event) == {"function", "started", "seconds", "thread", "failed"} for event in events
    )
