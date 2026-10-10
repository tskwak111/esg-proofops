import io
import json

import pytest
from pypdf import PdfWriter

from evaluation import local_analysis_pipeline as pipeline
from evaluation import report_decisions as rd
from tests.unit.test_report_decisions import setup_case


@pytest.mark.parametrize("blocked", [False, True])
def test_actual_pipeline_keeps_verified_facts_and_engine_output(tmp_path, monkeypatch, blocked):
    pack, source, blocks, _ = setup_case()
    text = blocks[0]["text"]
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    buf = io.BytesIO()
    writer.write(buf)
    calls = []

    class Probe:
        def preflight(self, **kwargs):
            if blocked and kwargs.get("calls") == 3:
                raise ValueError("OPENAI_BUDGET_EXHAUSTED")

        def summary(self):
            return dict(committed_or_reserved_usd="0")

        def request(self, payload, key):
            name = payload["text"]["format"]["name"]
            calls.append(name)
            if name == "local_claims_v3":
                return dict(
                    response_id="extract",
                    document=dict(claims=[dict(block=0, quote=text, track="performance")]),
                )
            return dict(
                response_id=name,
                document=dict(
                    claims=[
                        dict(
                            index=0,
                            fields={},
                            elements=[
                                dict(
                                    name="quantitative_or_qualified_ordinal", block=0, quote="100"
                                ),
                                dict(name="unit_or_qualified_ordinal", block=0, quote="kWh"),
                            ],
                        )
                    ]
                ),
            )

    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(rd, "load_pack", lambda _: pack)
    parsed = {"1": dict(chars=[dict(text=text, bbox=blocks[0]["bbox"])])}
    monkeypatch.setattr(pipeline, "load_source", lambda *_: (source, parsed, [], [], {}))
    monkeypatch.setattr(pipeline, "catalog", lambda *_: blocks)
    monkeypatch.setattr(
        pipeline, "charts", lambda *_: dict(status="not_applicable", pages=[], notice="No chart")
    )
    out = pipeline.analyze_full(buf.getvalue(), [1], key="fake", probe=Probe())
    if blocked:
        assert len(calls) == 1
        assert out["runtime"]["tagging_blocked"] == "OPENAI_BUDGET_EXHAUSTED"
        assert out["claims"][0]["decision"]["grade_range"] is None
        assert any(s["status"] == "일부 완료" for s in out["stages"])
    else:
        assert len(calls) == 4
        assert out["claims"][0]["decision"]["grade_range"]["floor"] == "E1"
        assert sum(e["state"] == "present" for e in out["claims"][0]["elements"]) == 2
    path = tmp_path / ".local/web-analysis" / out["run_id"]
    result = json.loads((path / "result.json").read_text(encoding="utf-8"))
    inputs = json.loads((path / "decision-inputs.json").read_text(encoding="utf-8"))
    assert result["decision_inputs_sha256"] == rd.digest(inputs)
    assert out["claims"][0]["review_handle"]["result_sha256"] == rd.digest(result)
