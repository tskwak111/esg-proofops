import json
from pathlib import Path

import pytest
from proofops.application.evidence.assurance_boundaries_c2 import discover_segments

DATA = Path(__file__).resolve().parents[1] / "fixtures/c2"


def test_reviewed_original_boundaries_and_shared_page_are_separate():
    inventory = json.loads((DATA / "source-inventory.json").read_text())
    expected = {
        "kakao": [[130, 131], [132], [133], [134, 135], [136, 137, 138]],
        "lg": [[117, 118], [118, 119]],
    }
    for source in inventory:
        texts = {
            int(p): t
            for p, t in json.loads(
                (DATA / f"{source['company']}-native-discovery.json").read_text()
            ).items()
        }
        result = discover_segments(
            texts, page_count=source["pages"], source_sha256=source["source_sha256"]
        )
        assert [b["pages"] for b in result["bundles"]] == expected[source["company"]]
        assert all(b["source_quality"] == "unverified" for b in result["bundles"])
        if source["company"] == "lg":
            a, b = result["bundles"]
            assert a["segments"][-1]["char_end"] == b["segments"][0]["char_start"]
            assert a["statement_id"] != b["statement_id"]
        else:
            assert result["reviewed_exclusions"][0]["physical_page"] == 139


def test_unknown_blank_continuation_is_not_a_back_cover():
    result = discover_segments(
        {1: "Independent Assurance Statement\nScope\nISAE 3000", 2: "Signed on 2026-06-01", 3: ""},
        page_count=3,
        source_sha256="a" * 64,
    )
    assert result["reviewed_exclusions"] == []
    assert result["bundles"][0]["pages"] == [1, 2, 3]
    assert result["bundles"][0]["boundary_state"] == "incomplete"


def test_reviewed_boundary_drift_is_rejected():
    source = json.loads((DATA / "source-inventory.json").read_text())[0]
    texts = {
        int(p): t for p, t in json.loads((DATA / "kakao-native-discovery.json").read_text()).items()
    }
    texts[133] = ""
    with pytest.raises(ValueError, match="REVIEWED_BOUNDARY"):
        discover_segments(texts, page_count=139, source_sha256=source["source_sha256"])
