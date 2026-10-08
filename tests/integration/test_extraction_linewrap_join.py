"""Selected PDF line continuations, never unselected text or cross-source evidence."""

from dataclasses import asdict

import pytest
from proofops_agent.upstage_extraction import UpstageClaimExtractor, _profile_with_options

from tests.integration.test_upstage_extraction import FakeProbe, packet


def resolve(tmp_path, text, indices, *, enabled=True, kind="paragraph"):
    extractor = UpstageClaimExtractor(
        FakeProbe(), tmp_path, extraction_source_ids=True, extraction_linewrap_join=enabled
    )
    data = packet(text)
    data["untrusted_document_data"]["kind"] = kind
    source = data["untrusted_document_data"]["source_id"]
    ids = extractor._sentence_index(text, source)
    spans, rejected = extractor._resolve_payload(
        {"sentence_ids": [ids[i][0] for i in indices]}, text, source, packet=data
    )
    assert not rejected["rejected_sentence_ids"]
    return spans


def test_selected_line_continuations_restore_one_exact_sentence(tmp_path):
    text = "회사는 온실가스 사용량을 줄이기 위한 평가를 진\n행하고 양산 적용을 추진하고 있습니다."
    spans = resolve(tmp_path, text, [1, 0])
    assert [(s.char_start, s.char_end, s.quote) for s in spans] == [(0, len(text), text)]
    assert len(resolve(tmp_path / "legacy", text, [0, 1], enabled=False)) == 2


@pytest.mark.parametrize(
    "text,indices,kind",
    [
        ("온실가스를 감축했습니다.\n재생에너지로 전환했습니다.", [0, 1], "paragraph"),
        ("탄소 감축을 위한 평가를 진\n\n행하고 있습니다.", [0, 1], "paragraph"),
        ("온실가스 감축\n· 별도 신규 목표", [0, 1], "paragraph"),
        ("온실가스 감축\n20%", [0, 1], "table_cell"),
        ("온실가스 감축\n20%", [0, 1], "paragraph"),
        ("선택한 탄소 감축\n선택하지 않은 문구\n별도 선택 문구", [0, 2], "paragraph"),
    ],
)
def test_join_does_not_cross_semantic_or_selection_boundaries(tmp_path, text, indices, kind):
    assert len(resolve(tmp_path, text, indices, kind=kind)) == 2


def test_profile_is_opt_in_and_pins_the_join_policy(tmp_path):
    legacy = _profile_with_options(source_ids=True)
    joined = _profile_with_options(source_ids=True, extraction_linewrap_join=True)
    assert legacy != joined
    assert legacy.prompt_sha256 == joined.prompt_sha256
    assert legacy.rule_sha256 != joined.rule_sha256
    with pytest.raises(ValueError, match="LINEWRAP_JOIN"):
        UpstageClaimExtractor(FakeProbe(), tmp_path, extraction_linewrap_join=True)
    with pytest.raises(ValueError):
        _profile_with_options(
            source_ids=True, extraction_atomic=True, extraction_linewrap_join=True
        )


def test_new_profile_receipt_replays_without_provider_and_rejects_legacy_pin(tmp_path):
    import json

    text = "온실가스 감축 평가를 진\n행하고 있습니다."
    source = packet(text)["untrusted_document_data"]["source_id"]
    ids = UpstageClaimExtractor._sentence_index(text, source)
    probe = FakeProbe(json.dumps({"sentence_ids": [sid for sid, _ in ids]}))
    extractor = UpstageClaimExtractor(
        probe, tmp_path, extraction_source_ids=True, extraction_linewrap_join=True
    )
    data = packet(text)
    data["extraction_profile"] = asdict(extractor.profile)
    first = extractor.extract(data)
    assert len(first["spans"]) == 1
    assert extractor.extract(data) == first
    assert len(probe.calls) == 1
    data["extraction_profile"] = asdict(_profile_with_options(source_ids=True))
    with pytest.raises(ValueError, match="EXTRACTION_PACKET_IDENTITY_INVALID"):
        extractor.extract(data)
    assert len(probe.calls) == 1


def test_join_cannot_admit_unknown_or_duplicate_selected_ids(tmp_path):
    extractor = UpstageClaimExtractor(
        FakeProbe(), tmp_path, extraction_source_ids=True, extraction_linewrap_join=True
    )
    data = packet("온실가스 감축을 추\n진합니다.")
    source = data["untrusted_document_data"]["source_id"]
    sid = extractor._sentence_index(data["untrusted_document_data"]["text"], source)[0][0]
    for selected in ([sid, sid], [sid, "unknown-source:0"]):
        with pytest.raises(ValueError, match="unknown or repeated"):
            extractor._resolve_payload(
                {"sentence_ids": selected},
                data["untrusted_document_data"]["text"],
                source,
                packet=data,
            )


def test_pilot_pins_profile_and_resume_without_paid_calls(tmp_path, monkeypatch, capsys):
    import json
    import sys

    from pypdf import PdfWriter

    from evaluation import local_upstage_pilot as pilot

    pdf = tmp_path / "report.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(pdf)
    state = tmp_path / "run"
    argv = [
        "pilot",
        "--pdf",
        str(pdf),
        "--state",
        str(state),
        "--report-year",
        "2025",
        "--period-start",
        "2024-01-01",
        "--period-end",
        "2024-12-31",
        "--parser",
        "local",
        "--extraction-source-ids",
        "--extraction-linewrap-join",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    settings = json.loads((state / "settings.json").read_text())
    assert settings["extraction_linewrap_join"] is True
    assert settings["extraction_profile"] == asdict(
        _profile_with_options(
            "openai/gpt-6-luna",
            source_ids=True,
            extraction_linewrap_join=True,
            wire_policy_version=2,
        )
    )
    before = (state / "pilot.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert (state / "pilot.json").read_bytes() == before
    monkeypatch.setattr(sys, "argv", argv[:-1])
    with pytest.raises(ValueError, match="linewrap join policy changed"):
        pilot.main()
    monkeypatch.setattr(sys, "argv", argv[:-2] + ["--extraction-linewrap-join"])
    with pytest.raises(SystemExit):
        pilot.main()
    assert "requires --extraction-source-ids" in capsys.readouterr().err


def test_composition_and_runtime_require_frozen_opt_in(tmp_path, monkeypatch):
    import json

    from proofops.adapters.local import openrouter
    from proofops_api.local_runtime import load_local_runtime
    from proofops_worker.composition import build_composition

    from tests.integration.test_local_runtime_config import _budget_limits, _parser_snapshot

    profile = asdict(
        _profile_with_options(
            "openai/gpt-6-luna",
            source_ids=True,
            extraction_linewrap_join=True,
            wire_policy_version=2,
        )
    )
    settings = {
        "build_root": str(tmp_path),
        "budget_limits": _budget_limits(),
        "extraction_profile": profile,
        "extraction_limits": {"max_calls": 2, "max_output_tokens": 128},
        "extraction_source_ids": True,
        "extraction_linewrap_join": True,
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings))
    (tmp_path / "parser.json").write_text(json.dumps(_parser_snapshot()))
    env = {
        "LOCAL_DATABASE_PATH": str(tmp_path / "state.sqlite3"),
        "LOCAL_PARSER_PROFILE_PATH": str(tmp_path / "parser.json"),
        "LOCAL_RUN_SETTINGS_PATH": str(path),
        "LOCAL_EXTRACTION_MODE": "upstage_probe",
    }
    assert load_local_runtime(env)["extraction_mode"] == "upstage_probe"
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    class Probe(FakeProbe):
        model = "openai/gpt-6-luna"
        wire_policy_version = 2

        def __init__(self, *args, **kwargs):
            super().__init__()

    monkeypatch.setattr(openrouter, "OpenRouterProbe", Probe)
    runner = build_composition(stage="extract")
    try:
        assert runner.extractor._linewrap_join is True
        assert asdict(runner.extractor.profile) == profile
        settings["extraction_profile"]["rule_sha256"] = "0" * 64
        path.write_text(json.dumps(settings))
        with pytest.raises(ValueError, match="EXTRACTION_PROFILE_MISMATCH"):
            build_composition(stage="extract")
        settings["extraction_linewrap_join"] = "yes"
        path.write_text(json.dumps(settings))
        with pytest.raises(ValueError, match="LOCAL_RUNTIME_CONFIG_INVALID"):
            load_local_runtime(env)
    finally:
        runner.uploads.close()
        runner.uploads.registry.close()
