"""One bounded handler path with local PDF bytes and fake provider responses."""

import importlib.util
import io
from pathlib import Path

import pdfplumber
import pytest
from pypdf import PdfReader, PdfWriter

MODULE = Path(__file__).resolve().parents[1] / "api/live-report.py"
spec = importlib.util.spec_from_file_location("live_report", MODULE)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
KIA = Path(
    "/Users/ss020/Dev/ESG_ProofOps/outputs/data-manager-handoff-20260922/데이터관리자_2차검토_20260922/04_원문/기아_2025_지속가능경영보고서.pdf"
)


def test_source_gate_and_cost_boundary(monkeypatch):
    monkeypatch.setenv("DEMO_ACCESS_CODE", "secret")
    assert report.verify_quote("2040년", "2040년까지 전 사업장", "2040년까지 전 사업장")
    assert not report.verify_quote("2040년", "2040년까지 전 사업장", "204O년까지 전 사업장")
    with pytest.raises(report.LiveError) as error:
        report.run_report(
            b"%PDF",
            list(range(1, 12)),
            access_code="secret",
            parse=lambda _: {},
            model=lambda *_: ({}, 0),
        )
    assert error.value.code == "INVALID_PAGES"
    with pytest.raises(report.LiveError) as error:
        report.run_report(
            b"%PDF", [1], access_code="wrong", parse=lambda _: {}, model=lambda *_: ({}, 0)
        )
    assert error.value.code == "ACCESS_DENIED"


@pytest.mark.skipif(not KIA.exists(), reason="local Kia PDF unavailable")
def test_selected_kia_page_with_fake_transports(monkeypatch):
    monkeypatch.setenv("DEMO_ACCESS_CODE", "secret")
    writer = PdfWriter()
    writer.add_page(PdfReader(KIA).pages[25])
    stream = io.BytesIO()
    writer.write(stream)
    pdf = stream.getvalue()
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        page = document.pages[0]
        words = page.extract_words()
        start = next(i for i, word in enumerate(words) if word["text"] == "기아는")
        chosen = words[start : start + 7]
        quote = " ".join(word["text"] for word in chosen)
        box = (
            min(w["x0"] for w in chosen),
            min(w["top"] for w in chosen),
            max(w["x1"] for w in chosen),
            max(w["bottom"] for w in chosen),
        )
        coords = [
            {"x": x / page.width, "y": y / page.height}
            for x, y in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]))
        ]
    parsed = {
        "model": "document-parse-260128",
        "usage": {"standard": [1], "pages": 1},
        "elements": [
            {"page": 1, "category": "paragraph", "coordinates": coords, "content": {"text": quote}}
        ],
    }
    calls = []

    def model(system, user, cap):
        calls.append(cap)
        if cap == report.MAX_MODEL_TOKENS[0]:
            return {
                "claims": [
                    {
                        "block": 0,
                        "quote": quote,
                        "track": "management",
                        "safe_harbor_category": None,
                    }
                ]
            }, 0.0001
        return {"claims": [{"index": 0, "elements": []}]}, 0.0001

    result = report.run_report(pdf, [26], access_code="secret", parse=lambda _: parsed, model=model)
    assert result["claims"][0]["source_verified"] is True
    assert result["claims"][0]["page"] == 26
    assert result["claims"][0]["decision"] is not None
    assert calls == list(report.MAX_MODEL_TOKENS)
    assert result["cost_usd"] == pytest.approx(0.0112)

    def hallucinated(system, user, cap):
        assert cap == report.MAX_MODEL_TOKENS[0]  # no tagging without source verification
        return {
            "claims": [{"block": 0, "quote": "보고서에 없는 환경 주장", "track": "management"}]
        }, 0.0001

    unverified = report.run_report(
        pdf, [26], access_code="secret", parse=lambda _: parsed, model=hallucinated
    )["claims"][0]
    assert unverified["source_verified"] is False
    assert unverified["decision"] is None
    assert unverified["blocked_reason"] == "원문 대조 필요"


@pytest.fixture(autouse=True)
def fake_usage_check(monkeypatch):
    import _limits

    _limits._recent.clear()
    monkeypatch.setattr(_limits, "daily_usage", lambda: 0.0)


def test_integrated_public_profile_gives_unclassified_claim_a_range(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_ACCESS_CODE", "secret")
    writer = PdfWriter()
    writer.add_blank_page(600, 800)
    stream = io.BytesIO()
    writer.write(stream)
    monkeypatch.setenv("PROOFOPS_SPEND_LEDGER", str(tmp_path / "event.sqlite3"))
    quote = "환경 경영을 실천합니다."
    parsed = {
        "model": "document-parse-260128",
        "usage": {"standard": [1], "pages": 1},
        "elements": [
            {
                "page": 1,
                "category": "paragraph",
                "coordinates": [
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.9, "y": 0.1},
                    {"x": 0.9, "y": 0.2},
                    {"x": 0.1, "y": 0.2},
                ],
                "content": {"text": quote},
            }
        ],
    }

    def model(system, user, cap):
        return {"claims": [{"block": 0, "quote": quote, "track": None}]}, 0.0001

    result = report.run_report(
        stream.getvalue(),
        [1],
        access_code="secret",
        parse=lambda _: parsed,
        model=model,
        pipeline_profile="finals-unattended-v1",
    )
    item = result["claims"][0]
    assert item["decision"] is None and item["source_status"]["display"] == "원문 확인 필요"
    assert item["provisional_grade"]["display_type"] == "range"
    assert item["provisional_grade"]["grade_range"]["floor"] == "E0"
    assert item["provisional_grade"]["grade_range"]["ceiling"] == "E3"


def test_integrated_profile_refuses_dispatch_without_combined_ledger(monkeypatch):
    monkeypatch.setenv("DEMO_ACCESS_CODE", "secret")
    monkeypatch.delenv("PROOFOPS_SPEND_LEDGER", raising=False)
    writer = PdfWriter()
    writer.add_blank_page(600, 800)
    stream = io.BytesIO()
    writer.write(stream)

    def deny(*_):
        raise AssertionError("no dispatch without atomic ledger")

    with pytest.raises(report.LiveError) as error:
        report.run_report(
            stream.getvalue(),
            [1],
            access_code="secret",
            parse=deny,
            model=deny,
            pipeline_profile="finals-unattended-v1",
        )
    assert error.value.code == "COMBINED_BUDGET_NOT_CONFIGURED"
