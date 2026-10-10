"""Opt-in table claims retain original row ownership and literal crop checks."""

from copy import deepcopy
from dataclasses import replace

import pytest
from proofops.application.evidence import span_citations
from proofops.domain.provenance import canonical_hash

from tests.acceptance.test_parsing import TENANT
from tests.integration.test_native_table_admission import fixture
from tests.unit.test_table_span_source_verification import crop_ocr, ref_for


def reader():
    from proofops.adapters.local import table_claim_source_verification

    return table_claim_source_verification


def test_opt_in_attests_row_cell_and_single_row_table_span(monkeypatch):
    from proofops.adapters.local import claim_source_verification as strict
    from proofops.adapters.local import table_span_source_verification as tables

    source, graph = fixture()
    monkeypatch.setattr(tables, "_rendered_text", crop_ocr)
    row = next(b for b in graph.blocks if b.kind == "table_row" and b.raw_text.startswith("MWh"))
    cell = next(b for b in graph.blocks if b.kind == "table_cell" and b.raw_text == "79")
    table = next(b for b in graph.blocks if b.kind == "table")
    refs = (ref_for(row, row.raw_text), ref_for(cell, "79"), ref_for(table, row.raw_text))
    assert all(
        r["status"] == "unresolved"
        for r in strict.attest_claim_spans(graph, source, refs, tenant_id=TENANT)["records"]
    )
    receipt = reader().attest_claim_spans(graph, source, refs, tenant_id=TENANT)
    assert [r["status"] for r in receipt["records"]] == ["verified"] * 3
    assert all(b.quality == "unverified" for b in graph.blocks)


@pytest.mark.parametrize(
    "mutation", ["forged_cell", "other_row", "borrowed_header", "wrong_location"]
)
def test_forged_cells_other_rows_and_headers_cannot_be_attested(monkeypatch, mutation):
    from proofops.adapters.local import table_span_source_verification as tables

    source, graph = fixture()
    monkeypatch.setattr(tables, "_rendered_text", crop_ocr)
    row = next(b for b in graph.blocks if b.kind == "table_row" and b.raw_text.startswith("MWh"))
    table = next(b for b in graph.blocks if b.kind == "table")
    ref = ref_for(row, row.raw_text)
    if mutation == "forged_cell":
        ref = replace(ref, quote="MWh\t25\t99")
    elif mutation == "other_row":
        # Both rows really exist, but joining their numbers is not one row claim.
        ref = ref_for(table, "2025\nMWh\t25")
    elif mutation == "borrowed_header":
        ref = replace(ref, quote="MWh\t2024\t79")
    else:
        ref = replace(ref, bbox=(20, 30, 320, 60))
    receipt = reader().attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    assert receipt["records"][0]["status"] == "unresolved"


def test_profile_dispatch_cli_replay_and_tamper(monkeypatch):
    from argparse import Namespace

    from proofops.adapters.local import claim_source_policies as policies
    from proofops.adapters.local import table_span_source_verification as tables
    from proofops.application.claims import Claim, ClaimDiscovery, ClaimScope

    from evaluation.local_upstage_pilot import claim_source_policy_for

    source, graph = fixture()
    monkeypatch.setattr(tables, "_rendered_text", crop_ocr)
    wrapper = reader()
    policy = wrapper.claim_source_policy()
    assert policies.publication_reader(policy) is wrapper
    assert policies.claim_source_reader(policy) is wrapper
    assert claim_source_policy_for(Namespace(claim_source_profile=wrapper.PROFILE)) == policy
    row = next(b for b in graph.blocks if b.kind == "table_row" and b.raw_text.startswith("MWh"))
    ref = ref_for(row, row.raw_text)
    receipt = policies.attest_claims(
        reader=wrapper, graph=graph, source=source, refs=(ref,), tenant_id=TENANT, cache=True
    )
    # Use the exact production discovery type without manufacturing source quality.
    claim = Claim(
        claim_id="11111111-1111-4111-8111-111111111111",
        tenant_id=TENANT,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        quote=ref.quote,
        source_refs=(ref,),
        source_quality="unverified",
        topic_ids=(),
        receipt=None,
    )
    discovery = ClaimDiscovery(
        scope=ClaimScope(TENANT, graph.document_version_id, graph.parse_manifest_id, "full", ()),
        source_sha256=graph.source_sha256,
        claims=(claim,),
        exclusions=(),
        receipts=(),
        processed_source_ids=(),
        synthetic=False,
        quality_issues=(),
    )
    checked, scoped = wrapper.replay_claim_spans(
        receipt, graph, source, discovery, tenant_id=TENANT
    )
    assert checked.claims[0].source_quality == "verified"
    assert all(b.quality == "unverified" for b in scoped.blocks)
    header = next(b for b in graph.blocks if b.kind == "table_cell" and b.raw_text == "2024")
    assert (
        span_citations.verify_source_ref(
            ref_for(header, "2024"), scoped, tenant_id=TENANT
        ).verification_state
        != "verified"
    )
    tampered = deepcopy(receipt)
    tampered["records"][0]["ref"]["quote"] = "MWh 25 99"
    tampered["artifact_sha256"] = canonical_hash(
        {k: v for k, v in tampered.items() if k != "artifact_sha256"}
    )
    with pytest.raises(ValueError, match="TABLE_CLAIM_RECEIPT_MISMATCH"):
        wrapper.replay_claim_spans(tampered, graph, source, discovery, tenant_id=TENANT)
    with pytest.raises(ValueError):
        policies.publication_reader(policy | {"wrapper_sha256": "0" * 64})


def flat_fixture():
    from proofops.application.ingest.graph_fusion import fuse_candidates

    source, original = fixture()
    batch = original.candidates[0]
    row_ids = {b.source.source_native_id for b in batch.blocks if b.kind == "table_row"}
    # Real ODL table shape: cells have table owners and grid indices, no row blocks.
    batch = replace(
        batch,
        blocks=tuple(b for b in batch.blocks if b.kind != "table_row"),
        edges=tuple(
            e
            for e in batch.edges
            if e.source_native_id not in row_ids and e.target_native_id not in row_ids
        ),
    )
    return source, fuse_candidates((batch,), tenant_id=TENANT)


def test_flat_grid_uses_selected_values_and_their_exact_row_context(monkeypatch):
    from proofops.adapters.local import selected_cell_table_verification as selected

    source, graph = flat_fixture()
    monkeypatch.setattr(selected, "_rendered_cell", crop_ocr)
    table = next(b for b in graph.blocks if b.kind == "table")
    receipt = reader().attest_claim_spans(
        graph, source, (ref_for(table, "MWh\t25\t79"),), tenant_id=TENANT
    )
    assert receipt["records"][0]["status"] == "verified"


@pytest.mark.parametrize("mutation", ["number", "header", "swapped_rows"])
def test_flat_grid_does_not_borrow_or_forge(monkeypatch, mutation):
    from proofops.adapters.local import selected_cell_table_verification as selected
    from proofops.application.ingest.graph_fusion import fuse_candidates

    source, graph = flat_fixture()
    if mutation == "swapped_rows":
        batch = graph.candidates[0]
        batch = replace(
            batch,
            blocks=tuple(
                replace(b, row_number=1 - b.row_number) if b.kind == "table_cell" else b
                for b in batch.blocks
            ),
        )
        graph = fuse_candidates((batch,), tenant_id=TENANT)

    def read(page, box, **kwargs):
        result = crop_ocr(page, box, **kwargs)
        if mutation == "number":
            result["text"] = result["text"].replace("79", "99")
        if mutation == "header":
            result["text"] = result["text"].replace("2025", "2026")
        return result

    monkeypatch.setattr(selected, "_rendered_cell", read)
    table = next(b for b in graph.blocks if b.kind == "table")
    receipt = reader().attest_claim_spans(
        graph, source, (ref_for(table, "MWh\t25\t79"),), tenant_id=TENANT
    )
    assert receipt["records"][0]["status"] == "unresolved"


def test_real_worker_publishes_and_claim_store_replays_new_profile(tmp_path, monkeypatch):
    import json

    from proofops.adapters.local import claim_source_verification as strict
    from proofops.adapters.local.claim_store import LocalClaimStore
    from proofops.adapters.local.run_artifacts import load_run_graph
    from proofops.adapters.local.run_store import LocalSQLiteRunStore
    from proofops.application.ingest.graph_fusion import fuse_candidates
    from proofops.application.ports.jobs import JobMessage

    from tests.acceptance.test_parsing import candidate
    from tests.integration import test_run_lifecycle as lifecycle
    from tests.integration.test_real_extract_runner import FakeProbe, real_setup

    wrapper = reader()
    original = lifecycle.setup

    def configured(path):
        service, body = original(path)
        service.claim_source_policy = wrapper.claim_source_policy()
        return service, body

    monkeypatch.setattr(lifecycle, "setup", configured)
    monkeypatch.setattr(strict, "_rendered_text", crop_ocr)
    quote, native = "emissions 1234 tCO2e", "Page 1 emissions 1234 tCO2e"
    probe = FakeProbe(json.dumps({"claims": [quote]}))
    service, run_id, runner, now, probe = real_setup(tmp_path, monkeypatch, limit=1, probe=probe)
    real = load_run_graph(
        service.store, service.uploads, runner.parser, tenant_id=TENANT, run_id=run_id
    )
    batch = candidate("Q8-runtime", [("P", "paragraph", native, (70, 710, 300, 740), ())])
    batch = replace(
        batch,
        document_version_id=real.document_version_id,
        parse_manifest_id=real.parse_manifest_id,
        source_sha256=real.source_sha256,
        blocks=tuple(
            replace(
                b,
                source=replace(
                    b.source,
                    document_version_id=real.document_version_id,
                    parse_manifest_id=real.parse_manifest_id,
                ),
            )
            for b in batch.blocks
        ),
    )
    graph_input = fuse_candidates((batch,), tenant_id=TENANT)
    for module in ("proofops_worker.extract_runner", "proofops.adapters.local.claim_store"):
        monkeypatch.setattr(module + ".load_run_graph", lambda *a, **k: graph_input)
    run = service.store.jobs.get_run(TENANT, run_id)
    parse_before = service.store.jobs.read_checkpoint(JobMessage(**run["parse_job"]))
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    envelope, discovery, graph = runner.claims.load_evidence(TENANT, run_id)
    assert envelope["claim_source_attestation"]["schema"] == wrapper.SCHEMA
    assert envelope["claim_source_attestation"]["policy"] == wrapper.claim_source_policy()
    assert discovery.claims[0].source_quality == "verified"
    reopened = LocalClaimStore(
        LocalSQLiteRunStore(service.store.path), service.uploads, runner.parser
    )
    assert reopened.load(TENANT, run_id) == discovery
    assert service.store.jobs.read_checkpoint(JobMessage(**run["parse_job"])) == parse_before
    assert all(b.quality != "verified" for b in graph.blocks)


@pytest.mark.parametrize("substitute", ["99", "2025"])
def test_flat_forged_parser_cell_with_valid_refs_stays_unresolved(monkeypatch, substitute):
    from proofops.adapters.local import selected_cell_table_verification as selected
    from proofops.application.ingest.graph_fusion import fuse_candidates

    source, graph = flat_fixture()
    batch = graph.candidates[0]
    changed = []
    for b in batch.blocks:
        raw = b.source.raw_text
        if b.kind == "table" or b.kind == "table_cell" and raw == "79":
            raw = raw.replace("79", substitute)
            b = replace(b, source=replace(b.source, raw_text=raw, char_end=len(raw)))
        changed.append(b)
    graph = fuse_candidates((replace(batch, blocks=tuple(changed)),), tenant_id=TENANT)
    monkeypatch.setattr(selected, "_rendered_cell", crop_ocr)
    table = next(b for b in graph.blocks if b.kind == "table")
    ref = ref_for(table, f"MWh\t25\t{substitute}")
    receipt = reader().attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    assert receipt["records"][0]["status"] == "unresolved"
