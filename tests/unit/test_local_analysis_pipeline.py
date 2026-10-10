import io

import pytest
from pypdf import PdfWriter

from evaluation import local_analysis_pipeline as pipeline
from evaluation import local_dart


def block(text="2024 energy 1,200 kWh", page=1):
    return dict(
        index=0,
        page=page,
        text=text,
        raw_text=text,
        bbox=[0, 0, 100, 30],
        key="run/block",
        kind="paragraph",
        table=None,
        row=None,
        column=None,
    )


def test_full_document_uses_physical_pages_and_rejects_bad_mapping():
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(200, 200)
    out = io.BytesIO()
    writer.write(out)
    pipeline.validate_pdf(out.getvalue(), [2, 3])
    for pages in ([4], [True], [1, 1], [], [0]):
        with pytest.raises(ValueError):
            pipeline.validate_pdf(out.getvalue(), pages)


def test_numeric_substrings_and_invented_fields_are_rejected():
    b = block()
    fields = {
        "value": dict(value="200", block=0, quote=b["text"]),
        "entity": dict(value="NAVER", block=0, quote=b["text"]),
        "year": dict(value="2025", block=0, quote=b["text"]),
    }
    result = pipeline.normalize_fields(fields, [b], b)
    assert all(result[name]["value"] is None for name in fields)
    fields["value"]["value"] = "1200"
    assert pipeline.normalize_fields(fields, [b], b)["value"]["value"] == "1200"


def test_citation_cannot_bind_unrelated_page_or_nonliteral_text():
    first, other = block(), block(page=2)
    assert (
        pipeline.resolve_citation(dict(block=1, quote=other["text"]), [first, other], first) is None
    )
    assert pipeline.resolve_citation(dict(block=0, quote="invented"), [first], first) is None


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("consensus", "consensus"),
        ("invalid_text_control_character", "consensus"),
        ("parse_conflict", "review_required"),
        ("table_grid_overlap", "review_required"),
    ],
)
def test_independent_quote_match_does_not_erase_table_conflict(reason, expected):
    b = block("\x07Energy 1200 kWh")
    b["text"] = b["raw_text"].replace("\x07", "")
    parsed = {"1": {"chars": [{"text": b["text"], "bbox": b["bbox"]}]}}
    independent = dict(
        parser_name="upstage_async_standard",
        blocks=[
            dict(
                source=dict(
                    raw_text=b["text"],
                    physical_page=1,
                    native_bbox=b["bbox"],
                    parser_run_id="standard",
                    source_native_id="independent",
                )
            )
        ],
    )
    result = pipeline.verify(b["text"], b, parsed, [{}, independent], {b["key"]: reason})
    assert result["native_verified"] is True
    assert result["status"] == expected
    assert result["original_audit"] == reason
    parsed["1"]["chars"][0]["bbox"] = [200, 200, 300, 230]
    assert not pipeline.verify(b["text"], b, parsed, [{}, independent], {})["native_verified"]


def test_dart_off_does_not_call_client(monkeypatch):
    monkeypatch.setattr(local_dart, "client", lambda: pytest.fail("OFF must not connect"))
    assert local_dart.collect({"enabled": False})["status"] == "off"


def test_dart_rejects_missing_scope_and_wrong_receipt_before_statement_call(monkeypatch):
    config = dict(enabled=True, corp_code="00266961", year="2024", rcept_no="20250318000645")
    with pytest.raises(ValueError, match="BASIS_REQUIRED"):
        local_dart.collect(config, dart=object())
    monkeypatch.setattr(
        local_dart, "lookup", lambda *args, **kwargs: dict(status="complete", filings=[])
    )
    with pytest.raises(ValueError, match="RECEIPT_YEAR_MISMATCH"):
        local_dart.collect(dict(config, fs_div="OFS"), dart=object())


def test_filing_candidates_only_include_requested_year(monkeypatch):
    monkeypatch.setattr(
        local_dart,
        "list_annual_filings",
        lambda *args, **kwargs: dict(
            status="complete",
            filings=[
                dict(report_period="2024.12", rcept_no="a"),
                dict(report_period="2025.12", rcept_no="b"),
            ],
        ),
    )
    result = local_dart.lookup(dict(corp_code="00266961", year="2024"), dart=object())
    assert [f["rcept_no"] for f in result["filings"]] == ["a"]
    assert result["selection_is_approval"] is False


def test_goals_energy_ratios_and_capacity_are_not_financial_conflicts():
    report = dict(status="retrieved", config=dict(year="2024"))
    claim = dict(
        quote="2025년 6MW PPA, 재생에너지 60% 목표", normalized=dict(year=dict(value="2025"))
    )
    result = local_dart.compare(claim, report)
    assert result["checks"][1]["status"] == "different_year_observed"
    assert [c["status"] for c in result["checks"][2:]] == ["not_applicable", "not_applicable"]
    assert result["final_status"] == "blocked_policy_unapproved"


def test_real_financial_triggers_require_evidence_and_do_not_auto_pass():
    result = local_dart.compare(
        dict(quote="설비 투자 100억원, 녹색 매출 30%", normalized={}),
        dict(status="retrieved", config=dict(year="2024")),
    )
    assert [c["status"] for c in result["checks"][2:]] == ["input_required", "input_required"]


def test_facility_name_ending_in_won_is_not_money():
    result = local_dart.compare(
        dict(quote="커넥트원 발전설비 52.8kW", normalized={}),
        dict(status="retrieved", config=dict(year="2024")),
    )
    assert result["checks"][2]["status"] == "not_applicable"


def test_chart_numbers_not_in_native_text_are_rejected(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(pipeline, "_render", lambda *a: b"image")
    points = [
        dict(metric="energy", unit="MWh", series="actual", role="actual", value=v, year="2024")
        for v in ("10.5", "999")
    ]
    monkeypatch.setattr(
        pipeline,
        "OpenAIVisionProbe",
        lambda: SimpleNamespace(
            request=lambda payload, key: dict(document=dict(points=points), response_id="fake")
        ),
    )
    result = pipeline.chart_points(
        SimpleNamespace(content=b"pdf", sha256="a" * 64),
        1,
        {"1": {"chars": [{"text": "energy 10.5 MWh"}]}},
        "test",
    )
    assert [p["number_present_in_pdf"] for p in result["points"]] == [True, False]
    assert result["points"][1]["status"] == "rejected_number_not_in_pdf"
    assert result["status"] == "candidate_only"


def test_tampered_registered_manifest_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "SNAPSHOT", "snapshot")
    directory = tmp_path / pipeline.SNAPSHOT
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text("{}")
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "SOURCE_HASH", pipeline.sha256(b"pdf").hexdigest())
    with pytest.raises(ValueError, match="INTEGRITY_MISMATCH"):
        pipeline.snapshot(b"pdf")


def test_unknown_pdf_cannot_reuse_registered_naver_snapshot():
    assert pipeline.snapshot(b"different pdf") is None


def test_approximate_values_half_year_and_unrelated_denominator():
    b = block("2025년 하반기 예상 약 7.4GWh. 일반전기 78%, 심야 포함 65%")
    fields = dict(
        year=dict(value="2025년 하반기", block=0, quote="2025년 하반기"),
        value=dict(value="약 7.4", block=0, quote="약 7.4GWh"),
    )
    result = pipeline.normalize_fields(fields, [b], b)
    assert result["year"]["value"] == "2025"
    assert result["year"]["raw_value"] == "2025년 하반기"
    assert result["value"]["value"] == "7.4"
    fields.update(
        value=dict(value="65%", block=0, quote="심야 포함 65%"),
        denominator=dict(value="일반전기", block=0, quote="일반전기 78%"),
    )
    result = pipeline.normalize_fields(fields, [b], b)
    assert result["denominator"]["value"] is None
    assert result["denominator"]["status"] == "binding_conflict"


def test_korean_year_and_number_units_normalize_without_inventing_values():
    b = block("2024년 감축량 3만톤, 재생에너지 20%")
    fields = dict(
        year=dict(value="2024년", block=0, quote="2024년"),
        value=dict(value="3만", block=0, quote="3만톤"),
    )
    result = pipeline.normalize_fields(fields, [b], b)
    assert result["year"]["value"] == "2024"
    assert result["value"]["value"] == "30000"
    assert result["value"]["raw_value"] == "3만"
    fields["value"]["value"] = "3"
    assert pipeline.normalize_fields(fields, [b], b)["value"]["value"] is None


def test_provider_region_can_support_native_verified_quote_only():
    b = block()
    independent = dict(
        parser_name="upstage_async_standard",
        blocks=[
            dict(
                geometry=dict(height_pt=100),
                context=["provider_bbox=0,70,100,100", "vision_only"],
                source=dict(
                    raw_text=b["text"],
                    physical_page=1,
                    native_bbox=None,
                    parser_run_id="standard",
                    source_native_id="s",
                ),
            )
        ],
    )
    parsed = {"1": {"chars": [{"text": b["text"], "bbox": b["bbox"]}]}}
    assert pipeline.verify(b["text"], b, parsed, [{}, independent], {})["status"] == "consensus"
    parsed["1"]["chars"] = []
    assert (
        pipeline.verify(b["text"], b, parsed, [{}, independent], {})["status"] == "review_required"
    )
