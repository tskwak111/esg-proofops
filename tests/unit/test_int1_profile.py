def test_profile_bundles_optins_and_preserves_defaults():
    from types import SimpleNamespace

    from proofops.application.analysis_profile import PROFILE, apply_pilot_profile

    old = SimpleNamespace(analysis_profile=None, parser="local")
    apply_pilot_profile(old)
    assert vars(old) == {"analysis_profile": None, "parser": "local"}
    new = SimpleNamespace(analysis_profile=PROFILE, resume=False, claim_pages="2", pages="2,3")
    apply_pilot_profile(new)
    assert new.parser == "mixed-v1"
    assert new.pipeline_profile == PROFILE
    assert new.claim_source_profile == "claim-source-v3"
    assert new.extraction_linewrap_join


def test_display_range_is_rules_only_without_confirming_unknown(tmp_path):
    from proofops.domain.rulepacks import canonical_json
    from proofops.domain.rules.engine import display_grade_range

    from tests.acceptance.test_tagging import setup

    inputs = setup(tmp_path)
    pack = inputs["rulepack"]
    before = canonical_json(pack.to_dict()) if hasattr(pack, "to_dict") else repr(pack)
    result = display_grade_range(pack)
    assert (result["floor"], result["ceiling"]) == ("E0", "E3")
    assert result["assumptions"]["display_only"] is True
    assert (canonical_json(pack.to_dict()) if hasattr(pack, "to_dict") else repr(pack)) == before


def test_rate_headers_never_increase_workers_when_unobserved():
    from proofops.adapters.local.profile_runtime import workers_from_headers

    assert workers_from_headers({}) == 8
    assert (
        workers_from_headers(
            {
                "x-ratelimit-limit-requests": "1000",
                "x-ratelimit-remaining-requests": "999",
                "x-ratelimit-limit-tokens": "2000000",
                "x-ratelimit-remaining-tokens": "1900000",
            }
        )
        == 16
    )
    assert (
        workers_from_headers(
            {
                "x-ratelimit-limit-requests": "100",
                "x-ratelimit-remaining-requests": "2",
                "x-ratelimit-limit-tokens": "2000000",
                "x-ratelimit-remaining-tokens": "1900000",
            }
        )
        == 1
    )


def test_completed_page_callback_precedes_slow_extraction():
    from threading import Event

    from proofops_worker.extract_runner import prefetch_packets

    early = Event()
    packets = [
        dict(untrusted_document_data=dict(source_id="a", page_num=1)),
        dict(untrusted_document_data=dict(source_id="b", page_num=2)),
    ]

    def extract(packet):
        if packet["untrusted_document_data"]["page_num"] == 2:
            assert early.wait(2), "tagging cannot start until all extraction finishes"
        return {"spans": []}

    def ready(page, responses):
        if page == 1:
            assert set(responses) == {"a"}
            early.set()

    assert set(prefetch_packets(packets, extract, max_workers=2, on_page=ready)) == {"a", "b"}


def test_range_projection_does_not_widen_when_serialized_again():
    from proofops.application.tagging.unattended import empty_provisional, ensure_range

    from tests.acceptance.test_rules import inputs, pack

    tags, context = inputs(
        "performance", comparison_baseline="unknown", calculation_boundary="unknown"
    )
    before = tuple(tags.facts)
    result = ensure_range(empty_provisional("blocked_evidence"), pack(), tags=tags, context=context)
    assert result["grade_range"]["floor"] == "E1"
    assert result["grade_range"]["ceiling"] == "E3"
    assert ensure_range(result, pack()) == result
    assert tags.facts == before


def test_finals_profile_uses_bounded_scope_and_matching_provider_key(monkeypatch, tmp_path):
    from scripts.finals_demo import pilot_argv, selected_provider

    monkeypatch.setenv("PROOFOPS_ANALYSIS_PROFILE", "finals-unattended-v1")
    monkeypatch.setenv("PROOFOPS_LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(
        "evaluation.report_scope.inspect", lambda _: dict(source_sha256="a" * 64, page_count=87)
    )
    monkeypatch.setattr(
        "evaluation.report_scope.validate_selection",
        lambda *a: dict(pages=[4, 11, 77], claim_pages=[4, 11]),
    )
    template = [
        "pilot",
        "--pdf",
        "old",
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
    args = pilot_argv(
        template, pdf=tmp_path / "new.pdf", state=tmp_path / "state", port=1, root=tmp_path
    )
    assert selected_provider() == "openai"
    assert args[args.index("--key-file") + 1] == str(tmp_path / ".env.openai.local")
    assert args[args.index("--pages") + 1] == "4,11,77"
    assert args[args.index("--claim-pages") + 1] == "4,11"
    assert args[args.index("--analysis-profile") + 1] == "finals-unattended-v1"
