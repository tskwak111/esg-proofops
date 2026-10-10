import io
import json
from types import SimpleNamespace

import pytest
from proofops.adapters.parsing.openai_vision import MAX_OUTPUT, MODEL, OpenAIVisionProbe
from pypdf import PdfWriter

from evaluation.local_analysis_server import SCHEMA, select_blocks, validate_input


def test_page_mapping_cannot_claim_unsubmitted_pages():
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    output = io.BytesIO()
    writer.write(output)
    validate_input(output.getvalue(), [105])
    for pages in ([100, 105], [True], [0], [105, 105]):
        with pytest.raises(ValueError):
            validate_input(output.getvalue(), pages)


def test_selection_excludes_charts_and_preserves_submitted_page_numbers():
    def block(kind, page, text):
        return SimpleNamespace(
            kind=kind,
            bbox=(0, 0, 50, 50),
            source=SimpleNamespace(
                raw_text=text, physical_page=page, source_native_id=f"{page}-{kind}"
            ),
        )

    raw = "\x07Renewable energy usage 20 GWh"
    batch = SimpleNamespace(
        blocks=[
            block("paragraph", 1, raw),
            block("table_cell", 2, "2025 target 14 GWh"),
            block("figure", 2, "emissions 120000"),
        ]
    )
    selected = select_blocks(batch, [100, 105])
    assert [b["page"] for b in selected] == [100, 105]
    assert "\x07" not in selected[0]["text"]
    assert batch.blocks[0].source.raw_text == raw


def test_text_requests_share_vision_ledger_and_cache(tmp_path):
    calls = []

    def post(path, payload, key):
        calls.append(path)
        if path.endswith("input_tokens"):
            return {"input_tokens": 500}
        return dict(
            id="text-response",
            model=MODEL,
            status="completed",
            usage=dict(input_tokens=500, output_tokens=100),
            output=[
                dict(
                    type="message",
                    content=[dict(type="output_text", text=json.dumps({"claims": []}))],
                )
            ],
        )

    probe = OpenAIVisionProbe(tmp_path / "shared.sqlite3", post=post)
    payload = dict(
        model=MODEL,
        store=False,
        max_output_tokens=MAX_OUTPUT,
        input=[{"role": "user", "content": "source"}],
        text={
            "format": {"type": "json_schema", "name": "claims", "strict": True, "schema": SCHEMA}
        },
    )
    first = probe.request(payload, "test-key")
    assert probe.request(payload, "test-key") == first
    assert first["document"] == {"claims": []}
    assert len(calls) == 2
    assert probe.summary()["states"]["completed"] == 1
    with pytest.raises(ValueError, match="POLICY_MISMATCH"):
        probe.request(dict(payload, model="other"), "test-key")
