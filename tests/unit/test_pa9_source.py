"""Real PDF regressions: cell ownership before recovery of missing locations."""

import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from proofops.adapters.local import upstage_ocr_profile_v9 as old
from proofops.application.ingest.graph_fusion import SourceArtifact, fuse_candidates

FIXTURE = Path(__file__).parents[1] / "fixtures/pa9"
CASES = json.loads((FIXTURE / "cases.json").read_text())


def test_new_source_policy_preserves_pa8_pins_and_every_other_contract():
    from proofops.application.analysis_profile import V2_PA9_POLICY, V2_PRE_PA9_POLICY, policy_for
    from proofops.domain.provenance import canonical_hash

    old_hash = "639ba0a01ebde2856deef9d5811195417bb13e369d57d7568fe3c8399634b12d"
    assert canonical_hash(V2_PRE_PA9_POLICY) == old_hash
    assert policy_for("finals-unattended-v2", pinned_hash=old_hash) == V2_PRE_PA9_POLICY
    assert V2_PA9_POLICY == V2_PRE_PA9_POLICY | dict(
        source="upstage-ocr-page-v10", table_native_ownership="native-grid-pa9-v1"
    )
    assert canonical_hash(V2_PA9_POLICY) == (
        "2ff0d5c654fec0aa80c70c3a5be0da601becdf5eae92980a766ae4fcdac7495e"
    )


def fixture(name, elements=None):
    data = (FIXTURE / (name + ".pdf")).read_bytes()
    source = SourceArtifact(
        str(uuid4()), str(uuid4()), str(uuid4()), sha256(data).hexdigest(), "v1", data
    )
    from proofops.application.ingest.graph_fusion import candidates_from_snapshot

    batches = (
        elements if elements is not None else json.loads((FIXTURE / (name + ".json")).read_text())
    )
    manifest = str(uuid4())
    for batch in batches:
        parser = str(uuid4())
        batch.update(
            tenant_id=source.tenant_id,
            document_version_id=source.document_version_id,
            parse_manifest_id=manifest,
            parser_run_id=parser,
            source_sha256=source.sha256,
        )
        for block in batch["blocks"]:
            block["source"].update(
                document_version_id=source.document_version_id,
                parse_manifest_id=manifest,
                parser_run_id=parser,
            )
    return fuse_candidates(candidates_from_snapshot(batches), tenant_id=source.tenant_id), source


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["company"] + "-" + c["quote"][:24])
def test_real_missing_or_multiline_cells_recover_only_in_native_owned_grid(case):
    from proofops.adapters.local import upstage_ocr_profile_v10 as current

    graph, source = fixture(case["company"])
    table = next(
        b for b in graph.blocks if b.kind == "table" and case["quote"] in b.normalized_text
    )
    start = table.normalized_text.index(case["quote"])
    ref = table.source_ref(
        normalized_char_start=start, normalized_char_end=start + len(case["quote"])
    )
    assert (
        old.cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]["status"]
        == "unresolved"
    )
    proof = current.cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]
    assert proof["status"] == "verified", proof
    assert proof["ownership"] == "native-grid-pa9-v1"
    assert all(p["owner_bbox"] for p in proof["cell_proofs"])


@pytest.mark.parametrize(
    "quote",
    [
        "• PUE(전력사용효율지수)2) 1.1x 유지\t에너지 효율화",
        "• PUE(전력사용효율지수)2) 1.1x 유지\t그린팩토리",
    ],
)
def test_pb4_false_row_column_combinations_stay_unresolved(quote):
    from proofops.adapters.local import upstage_ocr_profile_v10 as current

    from tests.unit.test_pb4_source import naver_case

    graph, source, table = naver_case()
    start = table.normalized_text.index(quote)
    ref = table.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))
    assert (
        current.cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]["status"]
        == "unresolved"
    )


@pytest.mark.parametrize("change", ["unit", "value", "year", "header_order"])
def test_native_grid_never_repairs_changed_quantities_units_or_years(change):
    from proofops.adapters.local import upstage_ocr_profile_v10 as current

    batches = json.loads((FIXTURE / "kia.json").read_text())
    quote = "\t국내\t천tCO2eq\t266.0\t244.6\t238.6"
    before, after = {
        "unit": ("천tCO2eq", "kg"),
        "value": ("266.0", "266.9"),
        "year": ("2024", "2025"),
        "header_order": ("2022", "2024"),
    }[change]
    for batch in batches:
        for b in batch["blocks"]:
            if b["source"]["physical_page"] != 2:
                continue
            text = b["source"]["raw_text"]
            if change == "header_order":
                text = (
                    text.replace("2022", "YEAR_SWAP")
                    .replace("2024", "2022")
                    .replace("YEAR_SWAP", "2024")
                )
            else:
                text = text.replace(before, after)
            b["source"].update(raw_text=text, char_end=len(text))
    if change in ("unit", "value"):
        quote = quote.replace(before, after)
    graph, source = fixture("kia", batches)
    table = next(b for b in graph.blocks if b.kind == "table" and quote in b.raw_text)
    start = table.normalized_text.index(quote)
    ref = table.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))
    assert (
        current.cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]["status"]
        == "unresolved"
    )


def test_changed_tenant_and_source_bytes_cannot_get_native_grid_approval():
    from proofops.adapters.local import upstage_ocr_profile_v10 as current

    case = CASES[0]
    graph, source = fixture(case["company"])
    table = next(b for b in graph.blocks if b.kind == "table" and case["quote"] in b.raw_text)
    start = table.normalized_text.index(case["quote"])
    ref = table.source_ref(
        normalized_char_start=start, normalized_char_end=start + len(case["quote"])
    )
    assert (
        current.cell_proof(graph, source.content, [ref], tenant_id=str(uuid4()))[0]["status"]
        == "unresolved"
    )
    assert (
        current.cell_proof(graph, source.content + b"changed", [ref], tenant_id=source.tenant_id)[
            0
        ]["status"]
        == "unresolved"
    )


def test_recovered_row_cannot_approve_a_located_cell_with_wrong_declared_box():
    from proofops.adapters.local import upstage_ocr_profile_v10 as current

    batches = json.loads((FIXTURE / "kia.json").read_text())
    for batch in batches:
        for b in batch["blocks"]:
            if b["kind"] == "table_cell" and b["source"]["raw_text"] == "266.0":
                bbox = b["source"]["native_bbox"]
                b["source"]["native_bbox"] = [bbox[0], bbox[1] + 30, bbox[2], bbox[3] + 30]
    graph, source = fixture("kia", batches)
    quote = "\t국내\t천tCO2eq\t266.0\t244.6\t238.6"
    table = next(b for b in graph.blocks if b.kind == "table" and quote in b.raw_text)
    start = table.normalized_text.index(quote)
    ref = table.source_ref(normalized_char_start=start, normalized_char_end=start + len(quote))
    proof = current.cell_proof(graph, source.content, [ref], tenant_id=source.tenant_id)[0]
    assert proof["status"] == "unresolved"


def test_prose_receipt_is_exact_v6_and_historical_v9_file_is_unchanged(monkeypatch):
    from copy import deepcopy
    from dataclasses import asdict, replace

    from proofops.adapters.local import upstage_ocr_profile_v6 as v6
    from proofops.adapters.local import upstage_ocr_profile_v10 as current
    from proofops.domain.provenance import canonical_hash

    graph, source = fixture("naver")
    table = next(b for b in graph.blocks if b.kind == "table")
    ref = table.source_ref(normalized_char_start=0, normalized_char_end=10)
    graph = replace(
        graph,
        blocks=tuple(
            replace(b, kind="paragraph") if b.source_id == table.source_id else b
            for b in graph.blocks
        ),
    )
    run = str(uuid4())
    base = dict(
        tenant_id=source.tenant_id,
        document_version_id=source.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        run_id=run,
        source_sha256=source.sha256,
        graph_sha256=canonical_hash(asdict(graph)),
        policy=v6.claim_source_policy(),
        records=[dict(ref=asdict(ref), status="verified", reason=None)],
    )
    monkeypatch.setattr(v6.Reader, "attest_claim_spans", lambda *a, **k: deepcopy(base))
    monkeypatch.setattr(current, "cell_proof", lambda *a, **k: pytest.fail("prose table path"))
    receipt = current.Reader(object(), run_id=run).attest_claim_spans(
        graph, source.content, [ref], tenant_id=source.tenant_id
    )
    assert receipt["baseline_receipt"] == base and receipt["records"] == base["records"]
    assert receipt["pb1_cell_proofs"] == []
    assert (
        sha256(Path(old.__file__).read_bytes()).hexdigest()
        == "ce72e343558611cb48b873dbee7626c9bd277f7b8353a31f0ef93c20e48ea1fd"
    )
