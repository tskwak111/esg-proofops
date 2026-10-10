from evaluation.odl_compare import anchor_matches
from evaluation.odl_pilot import compare_quotes, raw_nodes


def test_list_children_keep_original_page_without_inventing_geometry():
    nodes = raw_nodes(
        {
            "kids": [
                {
                    "id": 1,
                    "type": "list",
                    "page number": 105,
                    "bounding box": [0, 0, 500, 700],
                    "list items": [
                        {"id": 2, "content": "감축량 30,925 tCO2e"},
                        {"id": 3, "content": "목표 14GWh", "bounding box": [20, 30, 50, 60]},
                    ],
                }
            ]
        }
    )
    assert [node["page"] for node in nodes] == [105, 105]
    assert nodes[0]["bbox"] is None
    assert nodes[1]["bbox"] == [20, 30, 50, 60]


def test_lexical_match_is_page_bound_and_does_not_verify_claim():
    reference = {
        "rows": [
            {"id": "N09", "page": 105, "system_blocks": [{"text": "2024년 감축량 30,925 tCO2e"}]}
        ]
    }
    nodes = [
        {
            "id": "other-page",
            "page": 100,
            "text": "2024년 감축량 30,925 tCO2e",
            "bbox": [1, 2, 3, 4],
        },
        {
            "id": "wrong-number",
            "page": 105,
            "text": "2024년 감축량 30,926 tCO2e",
            "bbox": [1, 2, 3, 4],
        },
        {"id": "correct", "page": 105, "text": "2024년\n감축량 30,925 tCO2e", "bbox": None},
    ]
    result = compare_quotes(nodes, reference)[0]
    assert result["node_ids"] == ["correct"]
    assert result["located_quote_hits"] == 0
    assert result["semantic_verified"] is False


def test_nonfinite_or_reversed_box_is_not_located():
    for box in ([1, 2, float("nan"), 4], [3, 2, 1, 4], [True, 2, 3, 4]):
        assert (
            raw_nodes(
                {"kids": [{"id": 1, "content": "text", "page number": 1, "bounding box": box}]}
            )[0]["bbox"]
            is None
        )


def test_anchor_requires_both_denominators_and_exact_number_and_page():
    anchors = {
        "cases": [{"id": "N07", "page": 100, "quotes": ["일반전기 대비 78%", "심야전력 포함 65%"]}]
    }
    node = {
        "id": "a",
        "page": 100,
        "text": "일반전기 대비 78% 심야전력 포함 66%",
        "bbox": [1, 2, 3, 4],
    }
    assert not anchor_matches([node], anchors)[0]["all_text_found"]
    node["text"] = "일반전기 대비 78%\n심야전력 포함 65%"
    assert anchor_matches([node], anchors)[0]["all_located"]
    assert anchor_matches([node], anchors)[0]["semantic_binding"] == "not_evaluated"
    node["page"] = 101
    assert not anchor_matches([node], anchors)[0]["all_text_found"]


def test_failed_hybrid_start_reaps_only_owned_backend(tmp_path, monkeypatch):
    import json
    import socket

    from evaluation import odl_hybrid_pilot

    calls = []

    class Process:
        returncode = 7

        def poll(self):
            return 7

    class Owner:
        def spawn(self, command, *, cwd, env):
            assert "--receipt" in command and "--pages" in command
            assert env["DOCLING_DEVICE"] == "cpu"
            assert "AZURE_DOCUMENT_INTELLIGENCE_KEY" not in env
            return Process()

        def peak_memory_bytes(self, process):
            return 123

        def terminate_tree(self, process):
            calls.append("terminated")

        def close(self):
            calls.append("closed")

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    output = tmp_path / "experiment"
    monkeypatch.setattr(odl_hybrid_pilot, "process_isolation", lambda **kwargs: Owner())
    monkeypatch.setattr(odl_hybrid_pilot, "kill_and_reap", lambda process: calls.append("reaped"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "pilot",
            "--python",
            "python",
            "--pdf",
            "unused.pdf",
            "--output",
            str(output),
            "--port",
            str(port),
        ],
    )
    assert odl_hybrid_pilot.main() == 2
    assert calls == ["terminated", "reaped", "closed"]
    report = json.loads((output / "supervisor.json").read_text(encoding="utf-8"))
    assert report["client_status"] == "not_run"
    assert report["backend_stopped"]


def test_backend_receipt_refuses_unrequested_pages(tmp_path):
    import json

    import pytest

    from evaluation.odl_hybrid_backend import RecordingConverter

    class NeverCalled:
        def convert(self, *args, **kwargs):
            raise AssertionError("must not send unrequested pages to model")

    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"placeholder")
    receipt = tmp_path / "receipt.json"
    converter = RecordingConverter(NeverCalled(), receipt, {105})
    with pytest.raises(ValueError, match="UNEXPECTED_BACKEND_PAGE_RANGE"):
        converter.convert(pdf, page_range=(100, 105))
    assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "failed"


def test_missing_backend_range_is_pinned_to_explicit_selected_page(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from evaluation import odl_hybrid_backend

    class Converter:
        def convert(self, path, *, page_range):
            assert page_range == (105, 105)
            return SimpleNamespace(
                status=SimpleNamespace(value="success"),
                document=SimpleNamespace(export_to_dict=lambda: {"pages": {"105": {}}}),
            )

    monkeypatch.setattr(odl_hybrid_backend, "version", lambda name: "test")
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"placeholder")
    receipt = tmp_path / "receipt.json"
    converter = odl_hybrid_backend.RecordingConverter(Converter(), receipt, {105})
    converter.convert(pdf)
    value = json.loads(receipt.read_text(encoding="utf-8"))
    assert value["received_page_range"] is None
    assert value["page_range"] == [105, 105]
    assert value["pages"] == [105]
    assert value["status"] == "success"
