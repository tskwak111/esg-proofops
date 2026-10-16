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


def test_parser_child_observer_preserves_glyph_and_other_helpers(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    timing = importlib.import_module("fresh_e2e_timing")
    monkeypatch.setitem(
        sys.modules, "predeploy_runtime_base", SimpleNamespace(audit=lambda *a, **k: None)
    )
    calls = []

    class Parser:
        @staticmethod
        def _execute(command, work, env, profile):
            calls.append(command)
            return 42

    parser = tmp_path / "opendataloader.py"
    timing.observe_parser_child(Parser, parser)
    for name in ["w18_glyph_worker.py", "page_render.py", "opendataloader.py"]:
        command = [sys.executable, "-I", str(tmp_path / name), str(tmp_path)]
        assert Parser()._execute(command, tmp_path, {}, None) == 42
        expected = (
            str(Path(timing.__file__).with_name("fresh_parser_timing.py"))
            if name == "opendataloader.py"
            else command[2]
        )
        assert calls[-1] == [*command[:2], expected, command[3]]
