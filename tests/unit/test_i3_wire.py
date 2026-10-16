"""The compact selection wire keeps every literal and parent while fitting the cap."""

import json

from proofops.adapters.local.openai import WIRE_POLICY, OpenAIProbe
from proofops.application.ingest.i3_wire import compact


def test_repeated_context_is_losslessly_shared_and_offsets_remain_in_original(tmp_path):
    parents = [{"role": "same_source_column_header", "text": "환경 관리체계 " * 60}]
    entries = [
        dict(
            sentence_id=f"cell-{i}",
            text="에너지 절감 기술 적용",
            char_start=i,
            char_end=i + 1,
            row=i,
            column=1,
            candidate_role="cell_item",
            cell_source_id="server-id",
            parent_context=parents,
        )
        for i in range(20)
    ]
    original = dict(source_sentences=entries)
    before = json.dumps(original, ensure_ascii=False)
    reduced = compact(original)
    assert json.dumps(original, ensure_ascii=False) == before
    for old, new in zip(entries, reduced["source_sentences"], strict=True):
        assert new["text"] == old["text"] and new["sentence_id"] == old["sentence_id"]
        assert [reduced["candidate_contexts"][i] for i in new["parent_context_ids"]] == old[
            "parent_context"
        ]
    probe = OpenAIProbe("offline-test-key", tmp_path / "unused.sqlite3")
    body = probe.request_body(
        "selection guidance " * 200,
        json.dumps(reduced, ensure_ascii=False),
        request_id="offline-size",
        json_mode=True,
    )
    assert (
        len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
        <= WIRE_POLICY["max_request_bytes"]
        == 16384
    )
