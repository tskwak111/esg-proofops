"""Operator-only P4 profiles: frozen candidate preparation and failed reader gates."""

import json
import os
import sys

import pytest
from proofops_api import hosted_analysis
from pypdf import PdfWriter

from evaluation.hosted_r108 import prepare_argv

SCOPE = dict(report_year=2025, period_start="2024-01-01", period_end="2024-12-31")


@pytest.mark.parametrize(
    "profile", [None, "r108-default", "r108-finals-candidate", "r108-finals-candidate-v2"]
)
@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_hosted_preparation_pins_requested_bundle(tmp_path, monkeypatch, profile, platform):
    from evaluation import local_upstage_pilot as pilot

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(hosted_analysis.sys, "platform", platform)
    pdf, state = tmp_path / "selected.pdf", tmp_path / "state"
    writer = PdfWriter()
    writer.add_blank_page(300, 300)
    writer.write(pdf)
    config = SCOPE | (dict(analysis_profile=profile) if profile else {})
    argv = prepare_argv(pdf, state, "11111111-1111-4111-8111-111111111111", config)
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    settings = json.loads((state / "settings.json").read_text())
    manifest = json.loads((state / "pilot.json").read_text())
    if profile in ("r108-finals-candidate", "r108-finals-candidate-v2"):
        if platform == "darwin":
            assert settings["r108_profile"] == manifest["r108_profile"] == profile
        flags = (
            pilot.FINALS_CANDIDATE_V2_FLAGS
            if profile == "r108-finals-candidate-v2"
            else pilot.FINALS_CANDIDATE_FLAGS
        )
        assert all(manifest[name] for name in flags)
        if profile == "r108-finals-candidate-v2":
            assert not manifest.get("extraction_table_rows", False)
            assert "--extraction-table-rows" not in argv
            assert not manifest.get("extraction_recall_prompt", False)
            assert "--extraction-recall-prompt" not in argv
            assert manifest["preliminary_sentence_fallback"]
        assert settings["tagging_settings"]["model_profile"] == (
            "upstage-compact-element-consistency-v6"
        )
        assert "--position-context-order" not in argv
    else:
        assert "r108_profile" not in settings
        assert "--position-context-order" in argv
        assert argv[argv.index("--vision-parse") + 1] == "off"
    assert manifest["claim_source_profile"] == (
        "glyph-alignment-v1" if platform == "darwin" else "upstage-ocr-page-v3"
    )


@pytest.mark.parametrize(
    "config", [{"analysis_profile": "invented"}, {"rendered_reader_profile": "upstage-ocr-page-v4"}]
)
def test_unknown_operator_profiles_rejected(config):
    with pytest.raises(ValueError, match="HOSTED_.*PROFILE_INVALID"):
        hosted_analysis.operator_profiles(config)


@pytest.mark.parametrize("reader", ["upstage-ocr-page-v1", "upstage-ocr-page-v2"])
def test_failed_linux_reader_gate_cannot_be_enabled_in_json(reader, monkeypatch):
    monkeypatch.setattr(hosted_analysis.sys, "platform", "linux")
    config = dict(analysis_profile="r108-finals-candidate", rendered_reader_gate_passed=True)
    if reader:
        config["rendered_reader_profile"] = reader
    profiles = hosted_analysis.operator_profiles(config)
    assert profiles["source_reader"] == "unresolved"
    assert profiles["analysis_profile"] == "r108-finals-candidate"
    assert hosted_analysis.GATE_PASSED_RENDERED_READERS == {"upstage-ocr-page-v3"}


def test_linux_default_v3_carries_holdout_provenance(monkeypatch):
    monkeypatch.setattr(hosted_analysis.sys, "platform", "linux")
    profiles = hosted_analysis.operator_profiles({})
    assert profiles["source_reader"] == profiles["claim_source"] == "upstage-ocr-page-v3"
    assert profiles["rendered_reader_gate_report_sha256"] == (
        "69f0797dbae5420ba1b5deb4ef2f12df3e7a820c0a9a37c5f5d16c37deea741e"
    )
    monkeypatch.setattr(hosted_analysis, "GATE_PASSED_RENDERED_READERS", frozenset())
    assert hosted_analysis.operator_profiles({})["source_reader"] == "unresolved"


def test_mac_default_reader_unchanged(monkeypatch):
    monkeypatch.setattr(hosted_analysis.sys, "platform", "darwin")
    assert hosted_analysis.operator_profiles({})["source_reader"] == "apple-vision"


def test_hosted_operator_choice_excludes_regressed_v1_but_warns_on_existing_config():
    profiles = hosted_analysis.operator_profiles({"analysis_profile": "r108-finals-candidate"})
    assert profiles["analysis_profile_options"] == ["r108-default", "r108-finals-candidate-v2"]
    assert "E2E5" in profiles["analysis_profile_warning"]
    assert hosted_analysis.operator_profiles({})["analysis_profile"] == "r108-default"
    assert hosted_analysis.operator_profiles({})["llm_max_workers"] == 8
