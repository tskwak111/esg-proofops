"""PB4 original NAVER row/column regressions and unchanged v6 prose behavior."""

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from proofops.adapters.parsing.upstage_document import candidate_batch
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact, fuse_candidates

FIXTURE = Path(__file__).parents[1] / "fixtures/pb4"
BAD_QUOTES = (
    "• PUE(전력사용효율지수)2) 1.1x 유지\t에너지 효율화",
    "• PUE(전력사용효율지수)2) 1.1x 유지\t그린팩토리",
)


def naver_case():
    data = (FIXTURE / "naver-p88.pdf").read_bytes()
    source = SourceArtifact(
        str(uuid4()), str(uuid4()), str(uuid4()), sha256(data).hexdigest(), "v1", data
    )
    profile = ParserProfile(str(uuid4()), parser_mode="upstage", table_claims_profile="pb1-v1")
    elements = json.loads((FIXTURE / "naver-p88-table.json").read_bytes())["elements"]
    batch, _ = candidate_batch(
        source,
        profile,
        (1,),
        [dict(model="document-parse-260128", usage=dict(pages=1, enhanced=[1]), elements=elements)],
        mode="enhanced",
        config_hash=profile.config_hash(),
    )
    graph = fuse_candidates((batch,), tenant_id=source.tenant_id)
    table = next(b for b in graph.blocks if b.kind == "table")
    return graph, source, table


@pytest.mark.parametrize("quote", BAD_QUOTES)
def test_original_naver_pue_cannot_borrow_another_native_row_or_column(quote):
    from proofops.adapters.local import upstage_ocr_profile_v8 as old
    from proofops.adapters.local import upstage_ocr_profile_v9 as current

    graph, source, table = naver_case()
    start = table.normalized_text.index(quote)
    ref = table.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))
    assert (
        old.cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]["status"]
        == "verified"
    )  # Reproduce the exact old admission before asserting the fix.
    proof = current.cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]
    assert proof["status"] == "unresolved"
    assert proof["reason"] == "cell_native_order_unresolved"


def test_pb4_keeps_attested_current_value_unit_and_explicit_headers():
    from proofops.adapters.local.upstage_ocr_profile_v9 import cell_proof

    from tests.unit.test_pb1_source import fixture

    graph, source, ref = fixture()
    proof = cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]
    assert proof["status"] == "verified"
    assert {c["source_ref"]["quote"] for c in proof["cell_proofs"]} >= {
        "15",
        "tCO2eq",
        "2024",
        "10",
        "2023",
    }
    assert asdict(ref) == proof["ref"]


def test_non_table_attestation_is_an_unchanged_v6_receipt(monkeypatch):
    from dataclasses import replace

    from proofops.adapters.local import upstage_ocr_profile_v6 as v6
    from proofops.adapters.local import upstage_ocr_profile_v9 as current
    from proofops.domain.provenance import canonical_hash

    from tests.unit.test_pb1_source import fixture

    graph, source, ref = fixture()
    graph = replace(
        graph,
        blocks=tuple(
            replace(b, kind="paragraph") if b.source_id == ref.source_id else b
            for b in graph.blocks
        ),
    )
    run_id = str(uuid4())
    baseline = dict(
        tenant_id=source.tenant_id,
        document_version_id=source.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        run_id=run_id,
        source_sha256=source.sha256,
        graph_sha256=canonical_hash(asdict(graph)),
        policy=v6.claim_source_policy(),
        records=[dict(ref=asdict(ref), status="verified", reason=None)],
    )
    before = v6.claim_source_policy()
    calls = []

    def attest(self, g, s, refs, *, tenant_id):
        calls.append((g, s, refs, tenant_id))
        return baseline

    monkeypatch.setattr(v6.Reader, "attest_claim_spans", attest)
    monkeypatch.setattr(current, "cell_proof", lambda *a, **k: pytest.fail("prose table path"))
    receipt = current.Reader(object(), run_id=run_id).attest_claim_spans(
        graph, source.content, [ref], tenant_id=source.tenant_id
    )
    assert calls == [(graph, source.content, (ref,), source.tenant_id)]
    assert receipt["baseline_receipt"] == baseline
    assert receipt["records"] == baseline["records"]
    assert receipt["pb1_cell_proofs"] == []
    assert v6.claim_source_policy() == before


def test_approved_v9_can_be_requested_by_hosted_operator():
    from proofops_api.hosted_analysis import operator_profiles

    result = operator_profiles({"rendered_reader_profile": "upstage-ocr-page-v9"})
    assert result["source_reader"] == "upstage-ocr-page-v9"
    assert result["claim_source"] == "upstage-ocr-page-v9"
    assert len(result["rendered_reader_gate_report_sha256"]) == 64
