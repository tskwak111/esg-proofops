"""Explicit model/profile selection through the real worker composition; no network."""

import json
from dataclasses import asdict

import pytest
from proofops.application.ingest.graph_fusion import ParserProfile
from proofops_agent.upstage_extraction import _profile


@pytest.mark.parametrize("model", ["solar-pro3", "solar-pro4", "unknown"])
def test_composition_selects_frozen_model_or_refuses_before_transport(tmp_path, monkeypatch, model):
    from proofops.adapters.local import upstage
    from proofops_worker import composition

    monkeypatch.setattr(
        composition, "__file__", str(tmp_path / "apps/worker/src/worker/composition.py")
    )
    ledger = tmp_path / ".local/upstage/budget.sqlite3"
    ledger.parent.mkdir(parents=True)
    ledger.touch()  # existence only; fake transport never reads/writes this file
    parser = tmp_path / "parser.json"
    parser.write_text(
        json.dumps(ParserProfile("00000000-0000-4000-8000-000000000000").config_snapshot())
    )
    settings = tmp_path / "settings.json"
    profile = asdict(_profile(model if model != "unknown" else "solar-pro3"))
    if model == "unknown":
        profile["model_sha256"] = "a" * 64
    settings.write_text(
        json.dumps(dict(extraction_profile=profile, extraction_limits=dict(max_output_tokens=1024)))
    )
    for key, value in dict(
        APP_ENV="local",
        MODEL_ADAPTER="synthetic",
        LOCAL_EXTRACTION_MODE="upstage_probe",
        LOCAL_DATABASE_PATH=str(tmp_path / "state.sqlite3"),
        LOCAL_PARSER_PROFILE_PATH=str(parser),
        LOCAL_RUN_SETTINGS_PATH=str(settings),
    ).items():
        monkeypatch.setenv(key, value)
    calls = []

    class Probe:
        def __init__(self, key, path, *, model):
            self.model = model
            calls.append((path, model))

        def complete(self, *args, **kwargs):
            raise AssertionError("composition must not invoke model")

    monkeypatch.setattr(upstage, "UpstageProbe", Probe)
    if model == "unknown":
        with pytest.raises(ValueError, match="EXTRACTION_PROFILE_MISMATCH"):
            composition.build_composition(stage="extract")
        assert calls == []
    else:
        runner = composition.build_composition(stage="extract")
        assert runner.extractor.profile == _profile(model)
        assert calls == [(ledger, model)]
        runner.uploads.close()
        runner.uploads.registry.close()
    assert ledger.read_bytes() == b""
