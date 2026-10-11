from hashlib import sha256

import pytest
from pypdf import PdfWriter

from evaluation.report_scope import build_plan
from evaluation.report_sections import build_map
from scripts import analyze_report as ar


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    pdf = tmp_path / "new.pdf"
    writer = PdfWriter()
    for _ in range(15):
        writer.add_blank_page(600, 800)
    writer.write(pdf)
    source = build_map(
        15,
        [
            dict(page=3, title="Environment", path=["Environment"]),
            dict(page=12, title="Appendix", path=["Appendix"]),
        ],
    )
    source.update(
        source_path=str(pdf),
        source_sha256=sha256(pdf.read_bytes()).hexdigest(),
        page_count=15,
        method="test",
        issues=[],
    )
    texts = {
        p: "Climate carbon emissions renewable energy water waste. " * 15 for p in range(3, 16)
    }
    texts[2] = "CEO Message\n" + texts[3]
    proposal = build_plan(source, texts)
    monkeypatch.setattr("evaluation.report_scope.inspect", lambda *a, **k: proposal)
    monkeypatch.setattr(ar, "AUTO_SCOPE_DIR", tmp_path / "plans")
    args = [
        "--pdf",
        str(pdf),
        "--report-year",
        "2025",
        "--period-start",
        "2024-01-01",
        "--period-end",
        "2024-12-31",
        "--state",
        str(tmp_path / "state"),
    ]
    return args, proposal, tmp_path


def test_bounded_scope_delegates_exact_claim_and_evidence_sets_without_paid_calls(inputs):
    args, proposal, tmp_path = inputs
    plan = ar.plan_run(
        ar.build_parser().parse_args(args + ["--auto-scope", "--auto-scope-policy", "bounded-v1"])
    )
    assert plan["claim_pages"] == proposal["selected_claim_pages"]
    assert plan["pages"] == proposal["selected_evidence_pages"]
    assert len(plan["claim_pages"]) <= 10
    assert set(plan["pages"]) - set(plan["claim_pages"]) == {12, 13, 14, 15}
    assert "--invoke" not in plan["argv"]
    assert not (tmp_path / "state").exists()
    assert plan["auto_scope_artifact"].exists()


def test_editable_plan_is_imported_as_new_frozen_selection(inputs):
    import json

    args, proposal, tmp_path = inputs
    proposal["selected_claim_pages"] = [2, 3]
    proposal["selected_evidence_pages"] = [2, 3, 12]
    path = tmp_path / "edited.json"
    path.write_text(json.dumps(proposal))
    plan = ar.plan_run(ar.build_parser().parse_args(args + ["--scope-plan", str(path)]))
    assert plan["claim_pages"] == [2, 3]
    assert plan["pages"] == [2, 3, 12]
    assert plan["auto_scope_applied"]["selection_sha256"]
    assert path.read_text() == json.dumps(proposal)


def test_failed_scope_writes_reviewable_front_suggestion_and_never_runs(inputs, monkeypatch):
    args, proposal, tmp_path = inputs
    source = build_map(15, [])
    source.update(
        source_path=proposal["source_path"],
        source_sha256=proposal["source_sha256"],
        page_count=15,
        method="test",
        issues=[],
    )
    failed = build_plan(source, {p: "" for p in range(1, 16)})
    monkeypatch.setattr("evaluation.report_scope.inspect", lambda *a, **k: failed)
    with pytest.raises(ar.PlanError, match="NO_READABLE_ENVIRONMENTAL_NARRATIVE.*1, 2, 3"):
        ar.plan_run(
            ar.build_parser().parse_args(
                args + ["--auto-scope", "--auto-scope-policy", "bounded-v1"]
            )
        )
    assert list((tmp_path / "plans").glob("*.json"))
    assert not (tmp_path / "state").exists()


def test_bounded_scope_does_not_use_legacy_page_limit(inputs):
    args, _, _ = inputs
    with pytest.raises(ar.PlanError, match="evidence-pages"):
        ar.plan_run(
            ar.build_parser().parse_args(
                args
                + [
                    "--auto-scope",
                    "--auto-scope-policy",
                    "bounded-v1",
                    "--auto-scope-max-pages",
                    "15",
                ]
            )
        )


def test_scope_plan_conflicts_with_manual_pages(inputs):
    args, _, tmp_path = inputs
    with pytest.raises(ar.PlanError, match="scope-plan"):
        ar.plan_run(
            ar.build_parser().parse_args(
                args + ["--pages", "1", "--scope-plan", str(tmp_path / "absent.json")]
            )
        )


def test_mixed_parser_delegates_source_bound_page_routing(inputs):
    args, proposal, _ = inputs
    result = ar.plan_run(
        ar.build_parser().parse_args(
            args + ["--auto-scope", "--auto-scope-policy", "bounded-v1", "--mixed-parser"]
        )
    )
    argv = result["argv"]
    assert argv[argv.index("--parser") + 1] == "mixed-v1"
    assert argv[argv.index("--claim-pages") + 1] == ",".join(
        map(str, proposal["selected_claim_pages"])
    )
    assert "--invoke" not in argv


def test_mixed_parser_requires_explicit_bounded_claim_scope(inputs):
    args, _, _ = inputs
    with pytest.raises(ar.PlanError, match="mixed-parser"):
        ar.plan_run(ar.build_parser().parse_args(args + ["--pages", "1,2", "--mixed-parser"]))


@pytest.mark.parametrize("policy, expected", [("bounded-v1", "AS1-v1"), ("bounded-v2", "W4-v2")])
def test_launcher_passes_explicit_ranking_policy(inputs, monkeypatch, policy, expected):
    args, proposal, _ = inputs
    seen = []

    def inspect(*args, **kwargs):
        seen.append(kwargs["ranking_policy"])
        return proposal

    monkeypatch.setattr("evaluation.report_scope.inspect", inspect)
    result = ar.plan_run(
        ar.build_parser().parse_args(args + ["--auto-scope", "--auto-scope-policy", policy])
    )
    assert seen == [expected]
    assert result["claim_pages"] == proposal["selected_claim_pages"]


def test_finals_profile_keeps_explicit_new_ranking(inputs, monkeypatch):
    args, proposal, _ = inputs
    seen = []

    def inspect(*args, **kwargs):
        seen.append(kwargs["ranking_policy"])
        return proposal

    monkeypatch.setattr("evaluation.report_scope.inspect", inspect)
    ar.plan_run(
        ar.build_parser().parse_args(
            args
            + ["--analysis-profile", "finals-unattended-v2", "--auto-scope-policy", "bounded-v2"]
        )
    )
    assert seen == ["W4-v2"]
