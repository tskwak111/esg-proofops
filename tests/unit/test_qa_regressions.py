import io
import json
import sqlite3
from types import SimpleNamespace

import pytest
from proofops.adapters.parsing.openai_vision import (
    LEGACY_POLICY,
    MODEL,
    PREVIOUS_BUDGET_POLICY,
    PREVIOUS_MODEL_POLICY,
    OpenAIVisionProbe,
)
from pypdf import PdfWriter

from evaluation import local_analysis_pipeline as pipeline
from evaluation.dart_candidates import candidates


@pytest.mark.parametrize(
    "old_policy", [LEGACY_POLICY, PREVIOUS_BUDGET_POLICY, PREVIOUS_MODEL_POLICY]
)
def test_luna_migration_keeps_old_spend_and_pending_reservations(tmp_path, old_policy):
    ledger = tmp_path / "budget.sqlite3"
    with sqlite3.connect(ledger) as db:
        db.execute("CREATE TABLE policy (id INTEGER PRIMARY KEY, body TEXT)")
        db.execute("INSERT INTO policy VALUES (1,?)", (json.dumps(old_policy, sort_keys=True),))
        db.execute(
            "CREATE TABLE calls (signature TEXT PRIMARY KEY, "
            "committed TEXT, state TEXT, result TEXT)"
        )
        db.execute("INSERT INTO calls VALUES ('sol-request','3.895','pending',NULL)")
    probe = OpenAIVisionProbe(ledger)
    assert MODEL == "gpt-6-sol"
    assert probe.summary()["committed_or_reserved_usd"] == "3.895"
    assert probe.summary()["states"]["pending"] == 1
    assert probe.summary()["limit_usd"] == "10.00"
    probe.preflight()
    with sqlite3.connect(ledger) as db:
        assert db.execute("SELECT count(*) FROM policy_history").fetchone()[0] == 1
    OpenAIVisionProbe(ledger)


def test_exhausted_budget_stops_before_docling(monkeypatch, tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    stream = io.BytesIO()
    writer.write(stream)
    probe = OpenAIVisionProbe(tmp_path / "budget.sqlite3")
    with sqlite3.connect(probe.ledger) as db:
        db.execute("INSERT INTO calls VALUES ('old','10','pending',NULL)")
    monkeypatch.setattr(pipeline, "load_source", lambda *_: pytest.fail("GPU must not run"))
    with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
        pipeline.analyze_full(stream.getvalue(), [1], key="fake", probe=probe)


def test_three_distinct_requests_require_matching_literal_evidence():
    calls = []
    good = dict(name="metric", block=0, quote="10 tons")

    def request(payload, key):
        calls.append(payload)
        return dict(
            response_id=str(len(calls)),
            document=dict(
                claims=[
                    dict(
                        index=0,
                        fields={"value": dict(block=0, quote="10 tons", value="10")},
                        elements=[good if len(calls) != 2 else dict(good, quote="invented")],
                    )
                ]
            ),
        )

    response = pipeline.invoke(
        SimpleNamespace(request=request),
        "fake",
        pipeline.TAGGING,
        "local_fields_elements_v2",
        "inspect",
        dict(claims=[dict(index=0, names=["metric"])]),
    )
    assert len(calls) == 3
    assert len({json.dumps(c, sort_keys=True) for c in calls}) == 3
    assert response["document"]["claims"][0]["elements"] == [good]
    assert len(response["replicas"]) == 3


def test_dart_generates_drafts_without_inventing_financial_inputs():
    report = dict(
        config=dict(year="2024", fs_div="CFS"),
        receipt="receipt",
        source_sha256="a" * 64,
        revenue_candidates=[dict(account_id="ifrs-full_Revenue", thstrm_amount="1000")],
    )
    result = candidates(dict(quote="2024년 환경 설비 투자 100억원, 녹색 매출 30%", page=45), report)
    assert set(result) == {"C3", "C4"}
    assert result["C3"]["amount"] is None
    assert result["C4"]["context"]["definition_source_ids"] == []
    assert result["C4"]["status"] == "candidate_only"
    assert candidates(dict(quote="재생에너지 30%, 발전설비 10MW"), report) == {}
