"""K3 regression: actual worker routing and strict native column ownership."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from proofops.domain.provenance import canonical_hash
from proofops_worker.extract_runner import _is_text_candidate

from tests.unit.test_pb4_source import naver_case

CASES = json.loads((Path(__file__).parents[1] / "fixtures/w9/cr2-tables.json").read_text())


def test_worker_routes_all_83_w9_numeric_rows_and_preserves_legacy_filter():
    from proofops.application.ingest.w9_tables import observations

    before = after = 0
    for case in CASES.values():
        if case["expected_rows"] is None:
            continue
        text = case["text"]
        block = SimpleNamespace(
            kind="table",
            normalized_text=text,
            source_id="table",
            quality="unverified",
            winner=0,
            page_num=1,
            bbox=(0, 0, 100, 100),
            candidates=(),
        )
        graph = SimpleNamespace(blocks=(block,), edges=())
        rows = observations(text, cells=case["cells"])
        routed = _is_text_candidate(
            "table",
            text,
            extraction_table_rows=True,
            extraction_k3=True,
            graph=graph,
            source_id="table",
            cells=case["cells"],
        )
        assert routed
        before += case["baseline_rows"]
        after += len(rows)
    assert (before, after) == (52, 83)
    vehicle = next(c for c in CASES.values() if "644,685" in c["text"])
    assert not _is_text_candidate("table", vehicle["text"], extraction_table_rows=True)


def test_native_column_recovery_keeps_quantity_and_facility_separate():
    from proofops.adapters.local import upstage_ocr_profile_v11 as source

    graph, original, _ = naver_case()
    for quote in (
        "• 2025년 16,673 tCO2eq의 온실가스 절감",
        "• 지열에너지를 본관 및 숙소동 냉난방에서 활용하여 1,838 MWh 에너지 절감",
    ):
        table = next(b for b in graph.blocks if b.kind == "table" and quote in b.raw_text)
        start = table.normalized_text.index(quote)
        ref = table.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))
        proof = source.cell_proof(graph, original.content, [ref], tenant_id=graph.tenant_id)[0]
        assert proof["status"] == "verified", proof
        assert proof["ownership"] == "native-column-k3-v1"


@pytest.mark.parametrize(
    "quote",
    [
        "• PUE(전력사용효율지수)2) 1.1x 유지\t그린팩토리",
        "• 태양광: 2025년 전력 발전량 21.3 MWh 커넥트원",
    ],
)
def test_wrong_native_row_or_facility_stays_unresolved(quote):
    from proofops.adapters.local import upstage_ocr_profile_v11 as source

    graph, original, _ = naver_case()
    table = next(b for b in graph.blocks if b.kind == "table" and quote in b.raw_text)
    start = table.normalized_text.index(quote)
    ref = table.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))
    assert (
        source.cell_proof(graph, original.content, [ref], tenant_id=graph.tenant_id)[0]["status"]
        == "unresolved"
    )


def test_k3_policy_is_distinct_and_i1_pins_remain_readable():
    from proofops.adapters.local import upstage_ocr_profile_v11 as source
    from proofops.adapters.local.claim_source_policies import publication_reader
    from proofops.application.analysis_profile import FINALS_I1_POLICY, K3_POLICY, policy_for

    assert canonical_hash(K3_POLICY) != canonical_hash(FINALS_I1_POLICY)
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I1_POLICY))
        == FINALS_I1_POLICY
    )
    assert publication_reader(source.claim_source_policy()) is source


@pytest.mark.parametrize("change", ["tenant", "bytes", "offset", "native_order"])
def test_k3_cannot_verify_tampered_source_or_native_order(change):
    from dataclasses import replace
    from uuid import uuid4

    from proofops.adapters.local import upstage_ocr_profile_v11 as source

    graph, original, table = naver_case()
    quote = "• 2025년 16,673 tCO2eq의 온실가스 절감"
    start = table.normalized_text.index(quote)
    ref = table.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))
    tenant, data = graph.tenant_id, original.content
    if change == "tenant":
        tenant = str(uuid4())
    elif change == "bytes":
        data = b"not the original PDF"
    elif change == "offset":
        ref = replace(ref, char_start=ref.char_start + 1)
    else:

        class Page:
            chars = [
                dict(text="•", x0=0, x1=2, top=100, bottom=110),
                dict(text="15", x0=0, x1=2, top=10, bottom=20),
            ]

        from unittest.mock import patch

        with patch.object(source.previous, "_literal", return_value=(0, 0, 10, 120)):
            with pytest.raises(ValueError, match="cell_native_order_unresolved"):
                source._column_literal(Page(), (0, 0, 10, 120), "•15")
        return
    assert source.cell_proof(graph, data, [ref], tenant_id=tenant)[0]["status"] == "unresolved"


def test_k3_receipt_replay_rejects_edited_proof_and_policy(monkeypatch):
    from copy import deepcopy
    from dataclasses import asdict
    from uuid import uuid4

    from proofops.adapters.local import upstage_ocr_profile_v6 as v6
    from proofops.adapters.local import upstage_ocr_profile_v11 as source

    graph, original, table = naver_case()
    quote = "• 2025년 16,673 tCO2eq의 온실가스 절감"
    start = table.normalized_text.index(quote)
    ref = table.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))
    run = str(uuid4())
    baseline = dict(
        tenant_id=graph.tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        run_id=run,
        source_sha256=graph.source_sha256,
        graph_sha256=canonical_hash(asdict(graph)),
        records=[dict(ref=asdict(ref), status="unresolved", reason="unsupported_block_kind")],
    )
    # Mock only the unchanged v6 prose receipt; the column proof reads the real PDF.
    monkeypatch.setattr(v6.Reader, "attest_claim_spans", lambda *a, **k: deepcopy(baseline))
    monkeypatch.setattr(v6.Reader, "recompute_claim_receipt", lambda *a, **k: deepcopy(baseline))
    reader = source.Reader(object(), run_id=run)
    receipt = reader.attest_claim_spans(graph, original.content, [ref], tenant_id=graph.tenant_id)
    assert receipt["records"][0]["status"] == "verified"
    assert (
        reader.recompute_claim_receipt(
            receipt, graph, original.content, [ref], tenant_id=graph.tenant_id
        )
        == receipt
    )
    bad = deepcopy(receipt)
    proof = bad["pb1_cell_proofs"][0]["cell_proofs"][0]
    proof["native_bbox"] = (proof["native_bbox"][0] + 1, *proof["native_bbox"][1:])
    with pytest.raises(ValueError, match="OCR_CLAIM_RECEIPT_MISMATCH"):
        reader.recompute_claim_receipt(
            bad, graph, original.content, [ref], tenant_id=graph.tenant_id
        )
    bad = deepcopy(receipt)
    bad["policy"]["wrapper_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="OCR_POLICY_OR_RUN_MISMATCH"):
        reader.recompute_claim_receipt(
            bad, graph, original.content, [ref], tenant_id=graph.tenant_id
        )
