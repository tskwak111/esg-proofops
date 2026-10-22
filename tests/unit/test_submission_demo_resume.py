"""Offline regression for the submission-demo resume metadata reconstruction.

These cover ``apply_resume_metadata``: the pure helper that lets the local
competition demo re-serve a stored pilot run from ``pilot.json`` alone, without
re-typing document metadata or policy flags. No model, network, or filesystem
side effects are exercised.
"""

from argparse import Namespace
from pathlib import Path

import pytest

from evaluation.local_upstage_pilot import apply_resume_metadata


def _fresh_args() -> Namespace:
    """A namespace mirroring argparse defaults before resume reconstruction."""
    return Namespace(
        pdf=None,
        report_year=None,
        period_start=None,
        period_end=None,
        pages="1",
        model="solar-pro3",
        verify_paragraphs=False,
        verify_tables=False,
        verify_merged_tables=False,
        repair_table_headers=False,
        verify_claim_spans=False,
        raster_ocr=False,
        raster_max_pages=4,
        raster_max_calls=1,
        live_tagging=False,
        live_relations=False,
        preliminary_context=False,
        tagging_max_calls=12,
    )


def test_resume_reconstructs_extraction_only_run() -> None:
    args = _fresh_args()
    saved = {
        "source_path": "/reports/kakao.pdf",
        "selected_pages": [47],
        "model": "solar-pro3",
    }
    apply_resume_metadata(args, saved)
    assert args.pdf == Path("/reports/kakao.pdf")
    assert args.pages == "47"
    # Absent metadata resolves to inert defaults; resume never re-registers.
    assert args.report_year == 0
    assert args.period_start == ""
    assert args.period_end == ""
    # Extraction-only run leaves every optional pipeline stage disabled.
    assert args.live_tagging is False
    assert args.verify_paragraphs is False
    assert args.verify_selected_cells is False
    assert args.native_quote_typography is False


def test_resume_preserves_new_source_policy_choices() -> None:
    args = _fresh_args()
    apply_resume_metadata(
        args,
        dict(
            source_path="/reports/report.pdf",
            verify_paragraphs=True,
            verify_selected_cells=True,
            native_quote_typography=True,
        ),
    )
    assert args.verify_selected_cells is args.native_quote_typography is True
    from proofops_worker.composition import build_composition

    with pytest.raises(ValueError, match="NATIVE_TYPOGRAPHY_REQUIRE_NATIVE_PARSE"):
        build_composition(stage="tag", native_typography_tolerance=True)
    with pytest.raises(ValueError, match="NATIVE_TYPOGRAPHY_REQUIRE_NATIVE_PARSE"):
        build_composition(
            stage="parse", verify_paragraphs=True, raster_ocr=True, native_typography_tolerance=True
        )


def test_resume_restores_all_policy_flags() -> None:
    args = _fresh_args()
    saved = {
        "source_path": "/reports/kb.pdf",
        "selected_pages": [30, 31],
        "model": "solar-pro4",
        "report_year": 2024,
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
        "verify_paragraphs": True,
        "verify_tables": True,
        "verify_claim_spans": True,
        "live_tagging": True,
        "live_relations": True,
        "tagging_max_calls": 18,
    }
    apply_resume_metadata(args, saved)
    assert args.pages == "30,31"
    assert args.model == "solar-pro4"
    assert args.report_year == 2024
    assert (args.period_start, args.period_end) == ("2024-01-01", "2024-12-31")
    assert args.verify_paragraphs is True
    assert args.verify_tables is True
    assert args.verify_claim_spans is True
    assert args.live_tagging is True
    assert args.live_relations is True
    assert args.tagging_max_calls == 18


def test_resume_restores_raster_limits_from_policy() -> None:
    args = _fresh_args()
    saved = {
        "source_path": "/reports/doosan.pdf",
        "selected_pages": [27],
        "raster_ocr": True,
        "raster_policy": {"max_pages": 8, "max_calls": 3},
    }
    apply_resume_metadata(args, saved)
    assert args.raster_ocr is True
    assert args.raster_max_pages == 8
    assert args.raster_max_calls == 3


def test_resume_rejects_conflicting_explicit_pdf() -> None:
    args = _fresh_args()
    args.pdf = Path("/reports/other.pdf")
    saved = {"source_path": "/reports/kakao.pdf", "selected_pages": [47]}
    with pytest.raises(ValueError, match="conflicting explicit"):
        apply_resume_metadata(args, saved)


def test_resume_keeps_explicit_page_override() -> None:
    args = _fresh_args()
    args.pages = "12,13"
    saved = {"source_path": "/reports/kakao.pdf", "selected_pages": [47]}
    apply_resume_metadata(args, saved)
    # An explicit non-default --pages is preserved rather than overwritten.
    assert args.pages == "12,13"


def test_resume_rejects_paid_invocation_before_reading_state(monkeypatch, capsys, tmp_path):
    from evaluation.local_upstage_pilot import main

    monkeypatch.setattr("sys.argv", ["pilot", "--resume", "--invoke", "--state", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "--resume is read-only for model calls" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_resume_restores_preliminary_context_flag() -> None:
    args = _fresh_args()
    saved = {
        "source_path": "/reports/kb.pdf",
        "selected_pages": [30],
        "live_tagging": True,
        "preliminary_context": True,
    }
    apply_resume_metadata(args, saved)
    assert args.preliminary_context is True


def test_resume_rejects_ai_project_review_before_reading_state(monkeypatch, capsys, tmp_path):
    """--ai-project-review only makes sense for a brand-new run's rulepack
    promotion; a --resume never re-promotes or changes an old snapshot."""
    from evaluation.local_upstage_pilot import main

    monkeypatch.setattr(
        "sys.argv",
        ["pilot", "--resume", "--ai-project-review", "--state", str(tmp_path)],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "--ai-project-review only applies to a NEW run" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_preliminary_context_requires_live_tagging_before_reading_state(
    monkeypatch, capsys, tmp_path
):
    from evaluation.local_upstage_pilot import main

    monkeypatch.setattr(
        "sys.argv",
        [
            "pilot",
            "--pdf",
            "/reports/does-not-matter.pdf",
            "--pages",
            "1",
            "--report-year",
            "2024",
            "--period-start",
            "2024-01-01",
            "--period-end",
            "2024-12-31",
            "--preliminary-context",
            "--state",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "--preliminary-context requires --live-tagging" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_resume_restores_frozen_extraction_allowance_without_increasing_it():
    saved = dict(
        source_path=str(Path("/reports/report.pdf").resolve()),
        extraction_batch_calls=4,
        extraction_total_calls=40,
    )
    args = _fresh_args()
    apply_resume_metadata(args, saved)
    assert args.max_calls == 4 and args.extraction_total_calls == 40
    args.extraction_total_calls = 80
    with pytest.raises(ValueError, match="cannot change extraction total"):
        apply_resume_metadata(args, saved)


def test_resume_retains_frozen_parser_output_limit():
    import pytest

    saved = {
        "source_path": str(Path("/reports/kia.pdf").resolve()),
        "parser_max_output_bytes": 67108864,
    }
    args = _fresh_args()
    apply_resume_metadata(args, saved)
    assert args.parser_max_output_bytes == 67108864
    args.parser_max_output_bytes = 20000000
    with pytest.raises(ValueError, match="cannot change parser-max-output-bytes"):
        apply_resume_metadata(args, saved)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ([], "--pdf, --report-year, --period-start and --period-end are required"),
        (["--resume"], "--resume requires an existing pilot.json under"),
        (["--resume", "--invoke"], "--resume is read-only for model calls; omit --invoke"),
        (["--serve-worker"], "--serve-worker requires --serve"),
        (
            ["--parser-max-output-bytes", "0"],
            "--parser-max-output-bytes must be an integer in 1..134217728",
        ),
        (
            ["--parser-memory-bytes", "0"],
            "--parser-memory-bytes must be an integer in 1..4294967296",
        ),
        (["--vision-parse", "all"], "--vision-parse all requires --parser local"),
        (["--model", "solar-pro3"], "--model requires --llm-provider upstage"),
    ],
)
def test_pilot_cli_error_equivalence(options, message, tmp_path, monkeypatch, capsys):
    from evaluation.local_upstage_pilot import main

    state = tmp_path / "new-state"
    monkeypatch.setattr("sys.argv", ["pilot", "--state", str(state), *options])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    if options == ["--resume"]:
        message += " " + str(state.resolve())
    assert capsys.readouterr().err.splitlines()[-1] == "pilot: error: " + message
    assert not state.exists()


def test_pilot_cli_help_equivalence(monkeypatch, capsys):
    import hashlib

    from evaluation.local_upstage_pilot import main

    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr("sys.argv", ["pilot", "--help"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert (
        hashlib.sha256(output.out.encode()).hexdigest()
        == "bc394b13d0d866652dc6fc35d35e2eafa97d2bc7088c0605b23515b28c219e59"
    )


@pytest.mark.parametrize("current", [False, True])
def test_resume_metadata_equivalence(current):
    import hashlib
    import json

    saved = dict(source_path="/synthetic/report.pdf", selected_pages=[2, 5])
    if current:
        saved.update(
            model="gpt-6-luna",
            report_year=2025,
            period_start="2024-01-01",
            period_end="2024-12-31",
            claim_pages=[2],
            parser_mode="mixed-v1",
            vision_parse="auto",
            mixed_ocr_max_pages=3,
            extraction_batch_calls=4,
            extraction_total_calls=40,
            parser_memory_bytes=1024**3,
            parser_max_output_bytes=64 * 1024**2,
            live_tagging=True,
            live_relations=True,
            tagging_max_calls=18,
            extraction_source_ids=True,
            extraction_context=True,
            preliminary_context=True,
            preliminary_table_context=True,
            preliminary_table_role=True,
            compact_element_wire=True,
            claim_span_render_resolution=True,
            claim_span_bullet_spacing=True,
            claim_span_typography=True,
            verify_claim_spans=True,
        )
    args = _fresh_args()
    apply_resume_metadata(args, saved)
    expected = {
        False: "1b30ef4ec76fb377808ebcd203f793e891b2809407bb9bbb1f76994437dc17dd",
        True: "0154eb748f9b21927a826c0e3d34aadad3c2d337e610598fc035edeb7b9717b7",
    }
    result = json.dumps(vars(args), sort_keys=True, default=str)
    assert hashlib.sha256(result.encode()).hexdigest() == expected[current]


def test_pilot_module_entrypoint_error_equivalence(tmp_path):
    import subprocess
    import sys

    from evaluation.local_upstage_pilot import ROOT

    state = tmp_path / "new-state"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "evaluation.local_upstage_pilot",
            "--state",
            str(state),
            "--resume",
            "--invoke",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.splitlines()[-1] == (
        "local_upstage_pilot.py: error: --resume is read-only for model calls; omit --invoke"
    )
    assert not state.exists()
