"""Offline integration checks for the opt-in I1 bundle and frozen identities."""

import json
import os
import sys
from dataclasses import asdict
from itertools import product
from pathlib import Path

import pytest
from proofops_agent.upstage_extraction import UpstageClaimExtractor, _profile_with_options
from pypdf import PdfWriter

from evaluation import local_upstage_pilot as pilot
from scripts.finals_demo import pilot_argv
from tests.unit.test_extraction_recall_profiles import Probe, packet


@pytest.fixture(autouse=True)
def isolate_pilot_environment(monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())


def create_argv(tmp_path):
    pdf = tmp_path / "report.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(pdf)
    return [
        "pilot",
        "--pdf",
        str(pdf),
        "--state",
        str(tmp_path / "state"),
        "--report-year",
        "2025",
        "--period-start",
        "2024-01-01",
        "--period-end",
        "2024-12-31",
    ]


def test_candidate_create_resume_and_legacy_defaults(tmp_path, monkeypatch):
    argv = create_argv(tmp_path)
    monkeypatch.setattr(sys, "argv", argv + ["--r108-finals-candidate"])
    assert pilot.main() == 0
    state = tmp_path / "state"
    settings = json.loads((state / "settings.json").read_text())
    manifest = json.loads((state / "pilot.json").read_text())
    assert settings["r108_profile"] == manifest["r108_profile"] == pilot.FINALS_CANDIDATE
    assert all(manifest[name] for name in pilot.FINALS_CANDIDATE_FLAGS)
    assert settings["tagging_settings"]["model_profile"] == "upstage-compact-element-consistency-v6"
    assert settings["extraction_profile"] == asdict(
        _profile_with_options(
            "openai/gpt-6-luna",
            source_ids=True,
            extraction_context=True,
            extraction_table_context=True,
            assertion_prompt=True,
            position_order=True,
            wire_policy_version=2,
            display_text_profile="glyph-joined-display-v1",
            extraction_linewrap_join=True,
            extraction_table_rows=True,
            extraction_recall_prompt=True,
        )
    )
    from proofops.adapters.local import openrouter, upstage_parse
    from proofops_worker import composition
    from proofops_worker.composition import build_composition

    class NoDispatchProbe(Probe):
        def __init__(self, *args, **kwargs):
            pass

        def complete(self, *args, **kwargs):
            pytest.fail("candidate construction must not dispatch")

    monkeypatch.setattr(openrouter, "OpenRouterProbe", NoDispatchProbe)
    monkeypatch.setattr(upstage_parse, "UpstageParseProbe", NoDispatchProbe)
    monkeypatch.setattr(
        composition, "__file__", str(tmp_path / "apps/worker/src/proofops_worker/composition.py")
    )
    ledger = tmp_path / ".local/upstage/budget.sqlite3"
    ledger.parent.mkdir(parents=True)
    ledger.touch()
    runner = build_composition(stage="extract")
    try:
        assert asdict(runner.extractor.profile) == settings["extraction_profile"]
        assert runner.extractor._linewrap_join is True
        assert runner.extractor._table_rows is True
        assert runner.extractor._recall_prompt is True
    finally:
        runner.uploads.close()
        runner.uploads.registry.close()
    before = {p.name: p.read_bytes() for p in (state / "pilot.json", state / "settings.json")}
    for flags in ([], ["--r108-finals-candidate"]):
        monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)] + flags)
        assert pilot.main() == 0
        assert all((state / name).read_bytes() == raw for name, raw in before.items())
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    legacy_argv = create_argv(legacy)
    monkeypatch.setattr(sys, "argv", legacy_argv)
    assert pilot.main() == 0
    old = json.loads((legacy / "state/settings.json").read_text())
    assert "r108_profile" not in old and "extraction_table_rows" not in old
    assert old["extraction_profile"] == asdict(
        _profile_with_options(
            "openai/gpt-6-luna",
            wire_policy_version=2,
        )
    )
    monkeypatch.setattr(sys, "argv", legacy_argv + ["--r108-finals-candidate"])
    with pytest.raises(SystemExit):
        pilot.main()


@pytest.mark.parametrize(
    "flag",
    [
        "--extraction-atomic",
        "--preliminary-p2",
        "--preliminary-goal-role",
        "--verify-tables",
        "--raster-ocr",
    ],
)
def test_candidate_rejects_conflicts_before_creating_state(tmp_path, monkeypatch, flag):
    monkeypatch.setattr(sys, "argv", create_argv(tmp_path) + ["--r108-finals-candidate", flag])
    with pytest.raises(SystemExit):
        pilot.main()
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize(
    "flags",
    [
        ["--parser", "local"],
        ["--llm-provider", "upstage"],
        ["--relation-profile", "occurrence-v2"],
        ["--vision-parse", "off"],
    ],
)
def test_candidate_rejects_incompatible_profiles(tmp_path, monkeypatch, flags):
    monkeypatch.setattr(sys, "argv", create_argv(tmp_path) + ["--r108-finals-candidate"] + flags)
    with pytest.raises(SystemExit):
        pilot.main()
    assert not (tmp_path / "state").exists()


def test_candidate_refuses_modified_frozen_bundle(tmp_path, monkeypatch):
    argv = create_argv(tmp_path)
    monkeypatch.setattr(sys, "argv", argv + ["--r108-finals-candidate"])
    assert pilot.main() == 0
    path = tmp_path / "state/pilot.json"
    saved = json.loads(path.read_text())
    saved["extraction_linewrap_join"] = False
    path.write_text(json.dumps(saved))
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(path.parent)])
    with pytest.raises(SystemExit):
        pilot.main()


def test_each_extraction_policy_has_an_independent_hash():
    profiles = [
        _profile_with_options(
            source_ids=True,
            extraction_linewrap_join=join,
            extraction_table_rows=rows,
            extraction_recall_prompt=recall,
        )
        for join, rows, recall in product((False, True), repeat=3)
    ]
    assert len({p.rule_sha256 for p in profiles}) == 8
    assert len({p.model_sha256 for p in profiles}) == 1
    assert len({p.prompt_sha256 for p in profiles}) == 4  # Q1 is a local postprocessor.


def test_combined_policies_join_prose_and_keep_table_rows_separate(tmp_path):
    extractor = UpstageClaimExtractor(
        Probe(),
        tmp_path,
        extraction_source_ids=True,
        extraction_linewrap_join=True,
        extraction_table_rows=True,
        extraction_recall_prompt=True,
    )
    for text, kind, expected in (
        (
            "온실가스 감축 평가를 진\n행하고 있습니다.",
            "paragraph",
            ["온실가스 감축 평가를 진\n행하고 있습니다."],
        ),
        (
            "지표\t단위\t2024년\n온실가스 배출량\ttCO2e\t123\n용수 사용량\t㎥\t456",
            "table",
            ["온실가스 배출량\ttCO2e\t123", "용수 사용량\t㎥\t456"],
        ),
    ):
        data = packet(text, kind)
        data["extraction_profile"] = asdict(extractor.profile)
        result = extractor.extract(data)
        assert [s["quote"] for s in result["spans"]] == expected
        assert extractor.extract(data) == result


def test_finals_launcher_forwards_only_the_requested_bundle():
    template = [
        "pilot",
        "--pdf",
        "old.pdf",
        "--state",
        "old",
        "--pages",
        "1,2",
        "--claim-pages",
        "1",
        "--report-year",
        "2025",
        "--period-start",
        "2024-01-01",
        "--period-end",
        "2024-12-31",
        "--relation-profile",
        "occurrence-v3",
        "--claim-source-profile",
        "glyph-alignment-v1",
        "--display-text-profile",
        "glyph-joined-display-v1",
    ]
    kwargs = dict(pdf=Path("new.pdf"), state=Path("new"), port=8800, root=Path("/local"))
    base = pilot_argv(template, **kwargs)
    combined = pilot_argv(template, **kwargs, r108_finals_candidate=True)
    assert combined == base + ["--r108-finals-candidate"]
    assert "--r108-finals-candidate" not in template
