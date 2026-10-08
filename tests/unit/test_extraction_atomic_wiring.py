"""Atomic challenger wiring, with no credentials or provider dispatch."""

import json
import sys
from dataclasses import asdict

import pytest
from proofops.application.ingest.atomic_candidates import POLICY, PROFILE
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import _profile_with_options

from evaluation import local_upstage_pilot as pilot
from tests.unit.test_extraction_source_id_wiring import _args


def test_atomic_resume_restores_and_defaults():
    args = _args()
    pilot.apply_resume_metadata(args, {"source_path": "/tmp/r.pdf", "extraction_atomic": True})
    assert args.extraction_atomic is True
    args = _args()
    pilot.apply_resume_metadata(args, {"source_path": "/tmp/r.pdf"})
    assert args.extraction_atomic is False


def test_atomic_cli_requires_source_ids(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pilot",
            "--state",
            str(tmp_path),
            "--pdf",
            str(tmp_path / "absent.pdf"),
            "--report-year",
            "2025",
            "--period-start",
            "2024-01-01",
            "--period-end",
            "2024-12-31",
            "--extraction-atomic",
        ],
    )
    with pytest.raises(SystemExit):
        pilot.main()
    assert "--extraction-atomic requires --extraction-source-ids" in capsys.readouterr().err


def test_resume_cannot_add_atomic(tmp_path, monkeypatch, capsys):
    (tmp_path / "pilot.json").write_text(json.dumps({"source_path": "/tmp/r.pdf"}))
    monkeypatch.setattr(
        sys, "argv", ["pilot", "--resume", "--state", str(tmp_path), "--extraction-atomic"]
    )
    with pytest.raises(SystemExit):
        pilot.main()
    assert "--resume cannot add extraction atomic" in capsys.readouterr().err


@pytest.mark.parametrize("atomic", [False, True])
def test_pilot_freezes_profile_and_inspection_only_when_opted_in(tmp_path, monkeypatch, atomic):
    from pypdf import PdfWriter

    pdf = tmp_path / "r.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(pdf)
    state = tmp_path / "run"
    argv = [
        "pilot",
        "--state",
        str(state),
        "--pdf",
        str(pdf),
        "--report-year",
        "2025",
        "--period-start",
        "2024-01-01",
        "--period-end",
        "2024-12-31",
        "--parser",
        "local",
        "--extraction-source-ids",
    ]
    if atomic:
        argv.append("--extraction-atomic")
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    settings = json.loads((state / "settings.json").read_text())
    manifest = json.loads((state / "pilot.json").read_text())
    inspection = json.loads(next(state.glob("inspection-*.json")).read_text())
    expected = asdict(
        _profile_with_options(
            "openai/gpt-6-luna", source_ids=True, wire_policy_version=2, extraction_atomic=atomic
        )
    )
    assert settings["extraction_profile"] == expected
    if atomic:
        assert settings["extraction_atomic"] is True
        for document in (manifest, inspection):
            assert document["extraction_profile"] == expected
            assert document["extraction_profile_name"] == PROFILE
            assert document["atomic_policy_sha256"] == canonical_hash(POLICY)
        # Read-only resume restores the atomic profile without repeating flags.
        before = (state / "pilot.json").read_bytes()
        monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
        assert pilot.main() == 0
        assert (state / "pilot.json").read_bytes() == before
        # Profile cannot be changed in an existing state, even without --resume.
        monkeypatch.setattr(sys, "argv", argv[:-1])
        with pytest.raises(ValueError, match="atomic policy changed"):
            pilot.main()
    else:
        for document in (settings, manifest, inspection):
            assert "extraction_atomic" not in document
        for document in (manifest, inspection):
            assert "atomic_policy_sha256" not in document
            assert "extraction_profile_name" not in document
            assert "extraction_profile" not in document


@pytest.mark.parametrize(
    "atomic,source_ids,mode,accepted",
    [
        (True, True, "upstage_probe", True),
        (True, False, "upstage_probe", False),
        (False, True, "upstage_probe", False),
        ("yes", True, "upstage_probe", False),
        (True, True, "local_synthetic", False),
    ],
)
def test_runtime_validates_atomic_opt_in(tmp_path, atomic, source_ids, mode, accepted):
    from proofops_api.local_runtime import load_local_runtime

    from tests.integration.test_local_runtime_config import (
        _budget_limits,
        _parser_snapshot,
        _probe_extraction_profile,
        _write_json,
    )

    parser = _write_json(tmp_path / "parser.json", _parser_snapshot())
    settings = _write_json(
        tmp_path / "settings.json",
        {
            "build_root": str(tmp_path),
            "budget_limits": _budget_limits(),
            "extraction_profile": _probe_extraction_profile(),
            "extraction_limits": {"max_calls": 2, "max_output_tokens": 128},
            "extraction_atomic": atomic,
            **({"extraction_source_ids": True} if source_ids else {}),
        },
    )
    env = {
        "LOCAL_PARSER_PROFILE_PATH": str(parser),
        "LOCAL_RUN_SETTINGS_PATH": str(settings),
        "LOCAL_EXTRACTION_MODE": mode,
    }
    if accepted:
        assert load_local_runtime(env)["extraction_mode"] == mode
    else:
        with pytest.raises(ValueError, match="LOCAL_RUNTIME_CONFIG_INVALID"):
            load_local_runtime(env)


@pytest.mark.parametrize("provider", ["upstage", "openrouter"])
@pytest.mark.parametrize("atomic", [False, True])
def test_composition_passes_atomic_to_real_extractor(tmp_path, monkeypatch, provider, atomic):
    from proofops.adapters.local import openrouter, upstage
    from proofops_worker.composition import build_composition

    from tests.integration.test_local_runtime_config import _parser_snapshot
    from tests.integration.test_upstage_extraction import FakeProbe

    model = "solar-pro3" if provider == "upstage" else openrouter.MODEL
    version = 1 if provider == "upstage" else 2
    profile = asdict(
        _profile_with_options(
            model, source_ids=True, wire_policy_version=version, extraction_atomic=atomic
        )
    )
    settings = {
        "extraction_profile": profile,
        "extraction_limits": {"max_calls": 2, "max_output_tokens": 128},
        "extraction_source_ids": True,
        **({"extraction_atomic": True} if atomic else {}),
    }
    (tmp_path / "settings.json").write_text(json.dumps(settings))
    (tmp_path / "parser.json").write_text(json.dumps(_parser_snapshot()))
    for key, value in {
        "LOCAL_DATABASE_PATH": str(tmp_path / "state.sqlite3"),
        "LOCAL_PARSER_PROFILE_PATH": str(tmp_path / "parser.json"),
        "LOCAL_RUN_SETTINGS_PATH": str(tmp_path / "settings.json"),
        "LOCAL_EXTRACTION_MODE": "upstage_probe",
    }.items():
        monkeypatch.setenv(key, value)

    def fake(*args, **kwargs):
        probe = FakeProbe()
        probe.model = model
        probe.wire_policy_version = version
        return probe

    monkeypatch.setattr(upstage, "UpstageProbe", fake)
    monkeypatch.setattr(
        openrouter,
        "OpenRouterProbe",
        type(
            "FakeOpenRouter",
            (FakeProbe,),
            {
                "model": model,
                "wire_policy_version": version,
                "__init__": lambda self, *a, **kw: FakeProbe.__init__(self),
            },
        ),
    )
    runner = build_composition(stage="extract")
    try:
        assert asdict(runner.extractor.profile) == profile
        assert runner.extractor._atomic is atomic
        settings["extraction_profile"]["rule_sha256"] = "0" * 64
        (tmp_path / "settings.json").write_text(json.dumps(settings))
        with pytest.raises(ValueError, match="EXTRACTION_PROFILE_MISMATCH"):
            build_composition(stage="extract")
    finally:
        runner.uploads.close()
        runner.uploads.registry.close()


@pytest.mark.parametrize("atomic", [False, True])
def test_e2e_challenger_preserves_control_flags(tmp_path, atomic):
    from evaluation.r108_extraction_challenger import build_run_argv

    control = [
        "pilot",
        "--state",
        "/old/state",
        "--extraction-source-ids",
        "--llm-provider",
        "openrouter",
        "--preliminary-profile",
        "decision-v1",
        "--relation-profile",
        "decision-gate-v1",
        "--pages",
        "14,73",
    ]
    new_state = tmp_path / "fresh"
    result = build_run_argv(control, new_state, extraction_atomic=atomic)
    expected = list(control)
    expected[2] = str(new_state.resolve())
    assert result == expected + (["--extraction-atomic"] if atomic else [])
    assert control[2] == "/old/state"
    new_state.mkdir()
    with pytest.raises(ValueError, match="new state"):
        build_run_argv(control, new_state, extraction_atomic=atomic)


def test_e2e_harness_passes_opt_in_to_pilot(tmp_path, monkeypatch):
    from evaluation import r108_extraction_challenger as harness

    control = ["pilot", "--state", "/old/state", "--extraction-source-ids"]
    controls = tmp_path / "control.json"
    controls.write_text(json.dumps({company: control for company in harness.COMPANIES}))

    def fake_pilot():
        assert "--extraction-atomic" in sys.argv
        state = tmp_path / "states" / "samsung"
        state.mkdir(parents=True)
        (state / "pilot.json").write_text(
            json.dumps(
                {
                    "extraction_profile_name": PROFILE,
                    "atomic_policy_sha256": canonical_hash(POLICY),
                    "extraction_profile": {"test": "profile"},
                }
            )
        )
        return 0

    monkeypatch.setattr(harness.pilot, "main", fake_pilot)
    output = tmp_path / "results.json"
    assert (
        harness.main(
            [
                "--control-argv",
                str(controls),
                "--state-root",
                str(tmp_path / "states"),
                "--output",
                str(output),
                "--extraction-atomic",
                "--prepare",
                "samsung",
            ]
        )
        == 0
    )
    row = json.loads(output.read_text())["runs"]["samsung"]
    assert row["extraction_profile_name"] == PROFILE
    assert row["atomic_policy_sha256"] == canonical_hash(POLICY)
    assert row["status"] == "prepared_no_provider_calls"
