"""No paid dispatch: task budget fence and batching over a fake existing ledger."""

import json
import sqlite3
from types import SimpleNamespace

import pytest
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from evaluation import r108_perf_q4 as q4


class Offline:
    model = "openai/gpt-6-luna"
    wire_policy_version = 2

    def complete(self, *a, **k):
        raise AssertionError("HTTP forbidden")


@pytest.mark.parametrize(
    "initial,entries,expected", [("0", 260, "Q4_BUDGET_EXHAUSTED"), ("9.8", 1, "preflight")]
)
def test_paid_fence_reserves_r108_and_never_exceeds_task_cap(
    tmp_path, monkeypatch, initial, entries, expected
):
    from proofops.adapters.local import openrouter

    monkeypatch.setattr(q4, "ROOT", tmp_path)
    monkeypatch.setattr(q4, "LAB", tmp_path / "lab")
    monkeypatch.setattr(q4, "OUT", tmp_path / "out")
    q4.OUT.mkdir()
    ledger = tmp_path / ".local/openrouter/budget.sqlite3"
    ledger.parent.mkdir(parents=True)
    with sqlite3.connect(ledger) as db:
        db.execute("create table probe_calls(request_id text,committed text,receipt text)")
    spend = tmp_path / "lab/sprint3/E2E/r108-spend.json"
    q4.save(
        spend,
        {"initial_ledgers": {}, "limit_usd": "10", "cumulative_usd": initial, "executions": []},
    )
    (tmp_path / ".env.openrouter.local").write_text("OPENROUTER_API_KEY=test-only\n")
    calls = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        def complete(self, system, user, *, request_id, **kwargs):
            # The task's entire remaining allowance is booked in R108 before
            # any provider dispatch, so other writers cannot consume it.
            d = json.loads(spend.read_text())
            assert d["executions"][0]["r108_committed_usd"] == "0.40"
            assert d["cumulative_usd"] == "0.40"
            calls.append(request_id)
            with sqlite3.connect(ledger) as db:
                db.execute("insert into probe_calls values(?,?,?)", (request_id, "0.02", "{}"))
            return {"content": '{"sentence_ids":[]}'}

    monkeypatch.setattr(openrouter, "OpenRouterProbe", Fake)
    ex = UpstageClaimExtractor(
        Offline(),
        tmp_path / "receipts",
        extraction_source_ids=True,
        extraction_table_rows=True,
        extraction_recall_prompt=True,
    )
    candidates = [
        dict(
            page_num=1,
            source_id="source",
            kind="paragraph",
            entry={"sentence_id": f"s:{i}", "char_start": i, "char_end": i + 1, "text": "환경"},
            packet={},
        )
        for i in range(entries)
    ]
    data = {c: {"extractor": ex, "entries": candidates, "baseline": []} for c in q4.COMPANIES[:4]}
    matcher = SimpleNamespace(align=lambda *a, **k: ({}, {}), normalize_claim=lambda x: x)
    with pytest.raises((AssertionError, ValueError)) as error:
        q4.paid(data, [], matcher, {})
    if expected == "preflight":
        assert isinstance(error.value, AssertionError) and not calls
    else:
        assert str(error.value) == expected
        assert len(calls) == 20
        d = json.loads(spend.read_text())
        assert d["executions"][0]["status"] == "stopped"
        assert d["executions"][0]["delta_usd"] == "0.40"
        assert d["executions"][0]["reservation_usd"] == "0"
        assert d["cumulative_usd"] == "0.40"


def test_batching_is_bounded_and_supplement_deduplicates_exact_quotes():
    entries = [
        dict(
            page_num=1,
            source_id="s",
            kind="paragraph",
            packet={},
            entry={"sentence_id": str(i), "char_start": i, "text": "환경"},
        )
        for i in range(30)
    ]
    batches = q4.plan_batches(entries)
    assert [len(b) for b in batches] == [12, 12, 6]
    base = [{"page_num": 1, "quote": "환경", "claim_id": "old"}]
    fresh = [
        {"page_num": 1, "quote": "환경", "claim_id": "new"},
        {"page_num": 1, "quote": "기후", "claim_id": "extra"},
    ]
    assert q4.merge_proposals(base, fresh) == base + [fresh[1]]
