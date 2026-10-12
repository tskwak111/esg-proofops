import json
from copy import deepcopy

import pytest

from tests.unit.test_pa9_source import fixture as pa9_fixture


def hyundai_case(elements=None):
    from pathlib import Path

    from tests.unit import test_pa9_source

    old = test_pa9_source.FIXTURE
    test_pa9_source.FIXTURE = Path(__file__).parents[1] / "fixtures/k7"
    try:
        return pa9_fixture("hyundai", elements)
    finally:
        test_pa9_source.FIXTURE = old


def test_k7_real_hyundai_rows_require_native_units_and_observed_headers():
    from proofops.adapters.local import upstage_ocr_profile_v11 as old
    from proofops.adapters.local.upstage_ocr_profile_v13 import cell_proof
    from proofops.application.ingest.k6_coverage import observations_for

    graph, source = hyundai_case()
    table = next(b for b in graph.blocks if b.kind == "table")
    refs = [
        table.source_ref(normalized_char_start=o["start"], normalized_char_end=o["end"])
        for o in observations_for(table, graph)
    ]
    assert len(refs) == 4
    assert all(
        p["status"] == "unresolved"
        for p in old.cell_proof(graph, source.content, refs, tenant_id=graph.tenant_id)
    )
    proofs = cell_proof(graph, source.content, refs, tenant_id=graph.tenant_id)
    assert all(p["status"] == "verified" for p in proofs), proofs
    for proof in proofs:
        quotes = {p["source_ref"]["quote"] for p in proof["cell_proofs"]}
        assert {"2024년\t실적", "2023년\t실적", "2022년\t실적"} <= quotes
        assert "tCO2-eq" in quotes or "%" in quotes


@pytest.mark.parametrize("change", ["unit", "year", "value", "foreign_tenant", "header_order"])
def test_k7_native_proof_rejects_changed_source(change):
    from pathlib import Path

    from proofops.adapters.local.upstage_ocr_profile_v13 import cell_proof

    graph, source = hyundai_case()
    if change != "foreign_tenant":
        batches = json.loads((Path(__file__).parents[1] / "fixtures/k7/hyundai.json").read_text())
        before, after = {
            "unit": ("tCO2-eq", "tCO2-xx"),
            "year": ("2024", "2025"),
            "value": ("679,822", "679,823"),
            "header_order": ("2024", "2023"),
        }[change]
        for batch in batches:
            for b in batch["blocks"]:
                b["source"]["raw_text"] = b["source"]["raw_text"].replace(before, after)
                b["source"]["char_end"] = len(b["source"]["raw_text"])
        graph, source = hyundai_case(batches)
    table = next(b for b in graph.blocks if b.kind == "table")
    quote = table.raw_text.split("\n")[1]
    start = table.raw_text.index(quote)
    ref = table.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))
    tenant = (
        graph.tenant_id if change != "foreign_tenant" else "00000000-0000-4000-8000-000000000099"
    )
    assert cell_proof(graph, source.content, [ref], tenant_id=tenant)[0]["status"] == "unresolved"


def test_wire_budget_preserves_focal_and_evidence_removes_context_uuids_and_records_cut():
    from proofops.application.tagging.k7_wire import fit_context

    user = {
        "untrusted_document_data": {
            "atomic_quote": "온실가스를 줄였습니다.",
            "evidence_catalog": {"e0": {"quote": "원문", "page_num": 19}},
            "sentence_context": {
                "text": "가" * 2000,
                "source_refs": [
                    {
                        "quote": "가" * 2000,
                        "source_id": "forbidden-uuid",
                        "page_num": 19,
                        "verification_state": "verified",
                    }
                ],
                "rule_credit": False,
            },
        }
    }
    original = deepcopy(user)

    def body(system, wire):
        if len(wire.encode()) > 1100:
            raise ValueError("PROBE_REQUEST_TOO_LARGE")

    result = fit_context("system", user, body)
    assert len(result.encode()) <= 1100
    assert "forbidden-uuid" not in result
    data = json.loads(result)["untrusted_document_data"]
    assert data["atomic_quote"] == original["untrusted_document_data"]["atomic_quote"]
    assert data["evidence_catalog"] == original["untrusted_document_data"]["evidence_catalog"]
    assert data["interpretation_budget"]["truncated"]
    assert user == original


def test_wire_contextless_fallback_and_other_errors_propagate():
    from proofops.application.tagging.k7_wire import fit_context

    user = {
        "untrusted_document_data": {
            "atomic_quote": "focal",
            "sentence_context": {
                "text": "parent",
                "source_refs": [{"quote": "parent", "page_num": 1}],
            },
        }
    }

    def contextless(_, wire):
        if "sentence_context" in json.loads(wire)["untrusted_document_data"]:
            raise ValueError("PROBE_REQUEST_TOO_LARGE")

    data = json.loads(fit_context("sys", user, contextless))["untrusted_document_data"]
    assert "sentence_context" not in data
    assert data["interpretation_budget"]["fallback"] == "atomic_without_context"

    def failure(*args):
        raise ValueError("INVALID_PROBE_REQUEST")

    with pytest.raises(ValueError, match="INVALID_PROBE_REQUEST"):
        fit_context("sys", user, failure)


def test_truncated_table_keeps_origin_cell_before_column_header():
    from proofops.application.tagging.k7_wire import fit_context

    user = {
        "untrusted_document_data": {
            "sentence_context": {
                "_source_kind": "table",
                "text": "header\nparent",
                "source_refs": [
                    {"quote": "header" * 200, "page_num": 1},
                    {"quote": "parent" * 200, "page_num": 1},
                ],
            }
        }
    }

    def check(_, wire):
        if len(wire.encode()) > 1000:
            raise ValueError("PROBE_REQUEST_TOO_LARGE")

    data = json.loads(fit_context("sys", user, check))["untrusted_document_data"]
    assert data["sentence_context"]["blocks"][0]["text"].startswith("parent")
    assert data["interpretation_budget"]["truncated"]


def test_new_policy_is_explicit_and_keeps_v6_hash():
    from proofops.application.analysis_profile import (
        FINALS_I6_POLICY,
        FINALS_K7_POLICY,
        FINALS_K7_V1_POLICY,
        policy_for,
        publication_policy_for,
    )
    from proofops.domain.provenance import canonical_hash

    assert canonical_hash(FINALS_K7_V1_POLICY) == (
        "eca80367e46767c1d6dd3a91a2977e2c47c40e3bd796b56428b1b3cb3119e97f"
    )

    assert (
        canonical_hash(FINALS_I6_POLICY)
        == "568a110f32d723be3e569b14f12e676035175f19413c855e61d99d02870845b8"
    )
    assert (
        policy_for("finals-unattended-v2", pinned_hash=canonical_hash(FINALS_I6_POLICY))
        == FINALS_I6_POLICY
    )
    digest = canonical_hash(FINALS_K7_POLICY)
    assert policy_for("finals-unattended-v2", pinned_hash=digest) == FINALS_K7_POLICY
    assert publication_policy_for("finals-unattended-v2", pinned_hash=digest) == FINALS_K7_POLICY


def test_verified_observed_rows_supply_only_attested_current_and_comparison_cells():
    from dataclasses import replace

    from proofops.adapters.local.upstage_ocr_profile_v13 import cell_proof
    from proofops.application.evidence.span_citations import span_verified_graph
    from proofops.application.ingest.k6_coverage import observations_for
    from proofops.application.tagging.pb2_table_evidence import observation_sources

    from tests.unit.test_k4_contracts import prose_case

    graph, source = hyundai_case()
    table = next(b for b in graph.blocks if b.kind == "table")
    o = observations_for(table, graph)[0]
    row = table.source_ref(normalized_char_start=o["start"], normalized_char_end=o["end"])
    proof = cell_proof(graph, source.content, [row], tenant_id=graph.tenant_id)[0]
    from proofops.domain.values import SourceRef

    refs = [row] + [SourceRef(**p["source_ref"]) for p in proof["cell_proofs"]]
    scoped = span_verified_graph(
        graph, tuple(replace(r, verification_state="verified") for r in refs), "a" * 64
    )
    _, template = prose_case()
    claim = replace(
        template,
        tenant_id=graph.tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        quote=row.quote,
        source_refs=(row,),
        source_quality="verified",
    )
    assert observation_sources(claim, scoped, tenant_id=graph.tenant_id) is None
    sources = observation_sources(claim, scoped, tenant_id=graph.tenant_id, observed_headers=True)
    assert sources["value"]["ref"].quote == "679,822"
    assert sources["unit"]["ref"].quote == "tCO2-eq"
    assert sources["year"].quote == "2024년\t실적"
    assert len(sources["comparisons"]) == 2


def test_wire_enum_and_context_scope_share_one_catalog(tmp_path, monkeypatch):
    from proofops.application.tagging.k7_wire import POLICY

    from tests.integration.test_upstage_tagging_v4 import configured

    adapter, _, _, request = configured(tmp_path, monkeypatch)
    user = json.loads(request["user_json"])
    user["untrusted_document_data"].update(
        tagging_wire_policy=POLICY,
        sentence_context={
            "text": "parent",
            "source_refs": [
                {
                    "quote": "parent",
                    "page_num": 19,
                    "source_id": "8e8e5a93-de85-5e4f-bbd2-6e5004a1fe45",
                }
            ],
        },
    )
    request["user_json"] = json.dumps(user)
    system, wire, refs, _, schema = adapter._wire_request(request)
    assert json.loads(schema)["$defs"]["SourceRef"]["properties"]["id"]["enum"] == list(refs)
    assert "8e8e5a93-de85-5e4f-bbd2-6e5004a1fe45" not in wire
    assert "Every present element requires a non-empty" in system
