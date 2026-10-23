"""S_PIL contracts captured on c191f687 before responsibility extraction."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from evaluation import local_upstage_pilot as pilot
from tests.unit.test_ta_a1_boundaries import PILOT_GOLDENS, pilot_case

CLI_GOLDEN = "42234781d4b633022904e02e88ee481065e71f6899b28fc26cb1396daa52b4a1"
TAGGING_GOLDEN = "f072c6bf7c1e822e8bdd2bffc7e848f6a345c27c807ea494933dcd5a159887bd"


def cli_bytes(monkeypatch: pytest.MonkeyPatch) -> bytes:
    monkeypatch.setattr(sys, "argv", ["local_upstage_pilot.py"])
    monkeypatch.setenv("COLUMNS", "80")
    parser = pilot._build_parser()
    defaults = vars(parser.parse_args(["--state", "/pilot-fixture"]))
    return (parser.format_help() + json.dumps(defaults, default=str)).encode()


def tagging_bytes(monkeypatch: pytest.MonkeyPatch) -> bytes:
    monkeypatch.setattr(pilot, "uuid4", lambda: UUID(int=123))
    cases: list[dict[str, Any]] = [
        {},
        {"model_id": "gpt-6-luna", "relations": True},
        {
            "model_id": "openai/gpt-6-luna",
            "relations": True,
            "preliminary_context": True,
            "preliminary_table_context": True,
            "preliminary_table_role": True,
            "preliminary_goal_role": True,
            "preliminary_actor_role": True,
            "preliminary_sentence_context": True,
            "preliminary_sentence_fallback": True,
            "compact_element_wire": True,
            "element_consistency": True,
        },
    ]
    results = [pilot.live_tagging_settings(12, **case) for case in cases]
    results.append(pilot.raster_settings(max_pages=4, max_calls=2))
    return json.dumps(results, ensure_ascii=False).encode()


def test_cli_help_and_defaults_are_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    assert sha256(cli_bytes(monkeypatch)).hexdigest() == CLI_GOLDEN


@pytest.mark.parametrize("as_file", [False, True])
def test_cli_entry_points_preserve_help_without_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, as_file: bool
) -> None:
    monkeypatch.setattr(sys, "argv", ["local_upstage_pilot.py"])
    monkeypatch.setenv("COLUMNS", "80")
    env = dict(os.environ)
    # --help never executes stages; ensure the direct-file bootstrap stands alone.
    env.pop("PYTHONPATH", None)
    target = (
        [str(Path(pilot.__file__).resolve())]
        if as_file
        else ["-m", "evaluation.local_upstage_pilot"]
    )
    result = subprocess.run(
        [sys.executable, *target, "--help"],
        cwd=tmp_path if as_file else pilot.ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == pilot._build_parser().format_help()


def test_tagging_and_raster_policy_bytes_are_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    assert sha256(tagging_bytes(monkeypatch)).hexdigest() == TAGGING_GOLDEN


@pytest.mark.parametrize("mode", ["legacy", "source_context", "rich"])
def test_settings_bytes_and_read_only_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    assert pilot_case(tmp_path, monkeypatch, mode) == PILOT_GOLDENS[mode]


def test_spend_session_wraps_original_dispatch_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    from proofops.adapters.local import profile_runtime

    events: list[object] = []
    result = {"status": "failed", "exit_code": 1}

    @contextmanager
    def session(run_id: str) -> Iterator[None]:
        events.append(("enter", run_id))
        try:
            yield
        finally:
            events.append("exit")

    def run(args: object, *, tenant_id: str, run_id: str) -> dict[str, Any]:
        events.append(("run", tenant_id, run_id))
        return result

    monkeypatch.setattr(profile_runtime, "spend_session", session)
    monkeypatch.setattr(pilot, "_run_live_stages", run)
    args = pilot._build_parser().parse_args(["--state", "/unused"])
    args.pipeline_profile = "finals-unattended-v2"
    assert pilot.run_live_stages(args, tenant_id="tenant", run_id="run") is result
    assert events == [("enter", "run"), ("run", "tenant", "run"), "exit"]


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--resume", "--invoke"], "--resume is read-only for model calls; omit --invoke"),
        (
            ["--claim-span-typography"],
            "--claim-span-typography requires --claim-span-bullet-spacing",
        ),
        (["--extraction-atomic"], "--extraction-atomic requires --extraction-source-ids"),
        (["--serve-worker"], "--serve-worker requires --serve"),
        (["--parser-memory-bytes", "0"], "--parser-memory-bytes must be an integer"),
    ],
)
def test_cli_error_codes_precede_state_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    message: str,
) -> None:
    state = tmp_path / "must-not-exist"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "local_upstage_pilot.py",
            "--state",
            str(state),
            "--pdf",
            "/missing.pdf",
            "--report-year",
            "2025",
            "--period-start",
            "2025-01-01",
            "--period-end",
            "2025-12-31",
            *flags,
        ],
    )
    with pytest.raises(SystemExit) as error:
        pilot.main()
    assert error.value.code == 2
    assert message in capsys.readouterr().err
    assert not state.exists()


def test_resume_dispatches_through_original_metadata_attribute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "pilot.json"
    manifest.write_bytes(b'{"source_path":"/missing.pdf"}')
    parser = pilot._build_parser()
    args = parser.parse_args(["--state", str(tmp_path)])
    seen: list[object] = []
    monkeypatch.setattr(pilot, "apply_resume_metadata", lambda a, saved: seen.append((a, saved)))
    pilot._restore_resume_args(args, parser, tmp_path, manifest)
    assert seen == [(args, {"source_path": "/missing.pdf"})]
    assert manifest.read_bytes() == b'{"source_path":"/missing.pdf"}'
