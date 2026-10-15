"""D2 regressions: replay saved OCR collections and hold failed OCR blocks."""

from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from proofops.adapters.local import upstage_ocr_profile_d2_v21 as d2_reader
from proofops.adapters.local import upstage_ocr_profile_v20 as p3_reader


def _reader_for_replay(module, receipt, graph, page_collections):
    nested = SimpleNamespace(_saved_collections=None)
    active = SimpleNamespace(
        _saved_collections=None,
        previous=nested,
        replay_tables=lambda *args, **kwargs: graph,
    )
    instance = object.__new__(module.Reader)
    instance.run_id = "d2-replay-test"
    instance.previous = active
    instance._large = lambda *args, **kwargs: False
    instance.attest_tables = lambda *args, **kwargs: (
        receipt if active._saved_collections == page_collections else {}
    )
    return instance, active


def test_d2_binds_saved_collection_to_the_active_reader_and_replays_table_receipt():
    collection = {"manifest": {"physical_page": 1}, "request_id": "saved"}
    receipt = {"base_receipt": {"page_collections": [collection]}}
    graph = object()
    instance, active = _reader_for_replay(d2_reader, receipt, graph, [collection])

    assert (
        d2_reader.Reader.replay_tables(instance, receipt, graph, b"source", tenant_id="tenant")
        is graph
    )
    assert getattr(active, "_saved_collections", None) is None


def test_p3_table_replay_mismatch_is_reproducible_when_saved_collection_is_not_bound():
    collection = {"manifest": {"physical_page": 1}, "request_id": "saved"}
    receipt = {"base_receipt": {"page_collections": [collection]}}
    graph = object()
    instance, active = _reader_for_replay(p3_reader, receipt, graph, [collection])
    with pytest.raises(ValueError, match="OCR_TABLE_RECEIPT_MISMATCH"):
        p3_reader.Reader.replay_tables(instance, receipt, graph, b"source", tenant_id="tenant")

    assert active._saved_collections is None


def test_replay_receipt_hash_rejects_a_rehashed_forgery():
    collection = {"manifest": {"physical_page": 1}, "request_id": "saved"}
    receipt = {"base_receipt": {"page_collections": [collection]}}
    forged = deepcopy(receipt)
    forged["base_receipt"]["page_collections"][0]["request_id"] = "forged"
    graph = object()
    instance, _ = _reader_for_replay(d2_reader, receipt, graph, [collection])

    with pytest.raises(ValueError, match="OCR_TABLE_RECEIPT_MISMATCH"):
        d2_reader.Reader.replay_tables(instance, forged, graph, b"source", tenant_id="tenant")


def test_d2_replays_the_pinned_historical_table_policy_with_a_full_receipt_match(monkeypatch):
    graph = object()
    historical_policy = {"profile": "legacy-v21-reader-policy-test"}
    monkeypatch.setattr(
        d2_reader,
        "_HISTORICAL_READER_POLICY_SHA256",
        {d2_reader.canonical_hash(historical_policy)},
    )
    collection = {"manifest": {"physical_page": 1}, "request_id": "saved"}
    expected = {
        "schema": "native_selected_cell_table_source_v3",
        "rendered_reader_profile": d2_reader.PROFILE,
        "run_id": "d2-legacy-table-test",
        "reader_policy": d2_reader.native_policy(),
        "policy_sha256": d2_reader.table_policy_sha256(),
        "base_receipt": {"page_collections": [collection], "records": [{"status": "verified"}]},
    }
    expected["artifact_sha256"] = d2_reader.canonical_hash(
        {key: value for key, value in expected.items() if key != "artifact_sha256"}
    )
    historical = deepcopy(expected)
    historical["reader_policy"] = historical_policy
    historical["policy_sha256"] = next(iter(d2_reader._HISTORICAL_TABLE_POLICY_SHA256))
    historical["artifact_sha256"] = d2_reader.canonical_hash(
        {key: value for key, value in historical.items() if key != "artifact_sha256"}
    )
    instance, _active = _reader_for_replay(d2_reader, expected, graph, [collection])
    instance.run_id = expected["run_id"]
    instance.attest_tables = lambda *args, **kwargs: expected

    assert (
        d2_reader.Reader.replay_tables(instance, historical, graph, b"source", tenant_id="tenant")
        is graph
    )


def test_d2_rejects_a_rehashed_historical_table_receipt_forgery(monkeypatch):
    graph = object()
    historical_policy = {"profile": "legacy-v21-reader-policy-test"}
    monkeypatch.setattr(
        d2_reader,
        "_HISTORICAL_READER_POLICY_SHA256",
        {d2_reader.canonical_hash(historical_policy)},
    )
    expected = {
        "schema": "native_selected_cell_table_source_v3",
        "rendered_reader_profile": d2_reader.PROFILE,
        "run_id": "d2-legacy-table-test",
        "reader_policy": d2_reader.native_policy(),
        "policy_sha256": d2_reader.table_policy_sha256(),
        "base_receipt": {"page_collections": [], "records": [{"status": "verified"}]},
    }
    expected["artifact_sha256"] = d2_reader.canonical_hash(
        {key: value for key, value in expected.items() if key != "artifact_sha256"}
    )
    forged = deepcopy(expected)
    forged["reader_policy"] = historical_policy
    forged["policy_sha256"] = next(iter(d2_reader._HISTORICAL_TABLE_POLICY_SHA256))
    forged["base_receipt"]["records"][0]["status"] = "unresolved"
    forged["artifact_sha256"] = d2_reader.canonical_hash(
        {key: value for key, value in forged.items() if key != "artifact_sha256"}
    )
    instance, _ = _reader_for_replay(d2_reader, expected, graph, [])
    instance.run_id = expected["run_id"]
    instance.attest_tables = lambda *args, **kwargs: expected

    with pytest.raises(ValueError, match="OCR_TABLE_RECEIPT_MISMATCH"):
        d2_reader.Reader.replay_tables(instance, forged, graph, b"source", tenant_id="tenant")


def test_table_rendered_read_holds_and_replays_only_known_acquisition_failures():
    page = SimpleNamespace(page_number=2)
    box = [0, 0, 1, 1]
    holds = {}
    failed_read = d2_reader._hold_table_acquisition_failure(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("OCR_PAGE_ACQUISITION_FAILED:UPSTAGE_HTTP_429")
        ),
        holds,
        {},
    )
    with pytest.raises(
        ValueError,
        match="^ocr_acquisition_unresolved:UPSTAGE_HTTP_429$",
    ):
        failed_read(page, box)
    assert holds[(2, (0.0, 0.0, 1.0, 1.0))] == ("ocr_acquisition_unresolved:UPSTAGE_HTTP_429")

    replay_holds = d2_reader._saved_table_acquisition_holds(
        {
            "table_acquisition_holds": [
                dict(page=2, box=box, reason="ocr_acquisition_unresolved:UPSTAGE_HTTP_429")
            ]
        }
    )
    replayed_holds = {}
    missing_replay_read = d2_reader._hold_table_acquisition_failure(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("OCR_REPLAY_PAGE_MISSING")),
        replayed_holds,
        replay_holds,
    )
    with pytest.raises(ValueError, match="^ocr_acquisition_unresolved:UPSTAGE_HTTP_429$"):
        missing_replay_read(page, box)
    assert replayed_holds == holds

    integrity_failure = d2_reader._hold_table_acquisition_failure(
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("OCR_COLLECTION_UNTRUSTED")),
        {},
        {},
    )
    with pytest.raises(ValueError, match="^OCR_COLLECTION_UNTRUSTED$"):
        integrity_failure(page, box)


def test_attestation_holds_only_the_page_with_a_known_ocr_acquisition_failure():
    from tests.integration.test_claim_source_verification import inputs

    source, graph, ref = inputs()
    second = replace(ref, page_num=2)

    class Previous:
        _saved_collections = None

        def attest_claim_spans(self, graph, source, refs, *, tenant_id):
            refs = tuple(refs)
            if refs[0].page_num == 2:
                raise ValueError("OCR_COLLECTION_FAILED_RESERVATION_RETAINED:UPSTAGE_HTTP_429")
            return dict(
                tenant_id=tenant_id,
                document_version_id=graph.document_version_id,
                parse_manifest_id=graph.parse_manifest_id,
                source_sha256=graph.source_sha256,
                schema="claim_source_hx5_attestation_v1",
                pb1_cell_proofs=[],
                records=[dict(ref=asdict(item), status="verified") for item in refs],
            )

    instance = object.__new__(d2_reader.Reader)
    instance.run_id = "d2-page-hold-test"
    instance.previous = Previous()
    receipt = instance.attest_claim_spans(graph, source, (ref, second), tenant_id=graph.tenant_id)
    assert [record["status"] for record in receipt["records"]] == ["verified", "unresolved"]
    assert receipt["records"][1]["reason"] == "ocr_acquisition_unresolved:UPSTAGE_HTTP_429"

    replay = object.__new__(d2_reader.Reader)
    replay.run_id = instance.run_id
    replay.previous = Previous()
    assert (
        replay.recompute_claim_receipt(
            receipt, graph, source, (ref, second), tenant_id=graph.tenant_id
        )
        == receipt
    )


def test_page_attestations_keep_their_nested_receipt_hashes_independent():
    from proofops.domain.provenance import canonical_hash

    from tests.integration.test_claim_source_verification import inputs

    source, graph, ref = inputs()
    second = replace(ref, page_num=2)

    class Previous:
        _saved_collections = None

        def attest_claim_spans(self, graph, source, refs, *, tenant_id):
            ref = asdict(tuple(refs)[0])
            page = ref["page_num"]
            base = dict(
                tenant_id=tenant_id,
                document_version_id=graph.document_version_id,
                parse_manifest_id=graph.parse_manifest_id,
                source_sha256=graph.source_sha256,
                schema="claim_source_hx5_attestation_v1",
                pb1_cell_proofs=[],
                records=[dict(ref=ref, status="verified")],
                baseline_receipt=dict(
                    baseline_receipt=dict(
                        baseline_receipt=dict(bullet_alignment_attestation_sha256=f"page-{page}")
                    )
                ),
            )
            base["artifact_sha256"] = canonical_hash(base)
            return dict(base, base_receipt=base)

    reader = object.__new__(d2_reader.Reader)
    reader.run_id = "d2-page-receipt-test"
    reader.previous = Previous()
    receipt = reader.attest_claim_spans(graph, source, (ref, second), tenant_id=graph.tenant_id)

    pages = receipt["base_receipt"]["page_receipts"]
    assert [item["page_num"] for item in pages] == [ref.page_num, second.page_num]
    assert [
        item["receipt"]["baseline_receipt"]["baseline_receipt"]["baseline_receipt"][
            "bullet_alignment_attestation_sha256"
        ]
        for item in pages
    ] == [f"page-{ref.page_num}", "page-2"]
    assert [record["status"] for record in receipt["records"]] == ["verified", "verified"]
    assert (
        reader.recompute_claim_receipt(
            receipt, graph, source, (ref, second), tenant_id=graph.tenant_id
        )
        == receipt
    )


def test_historical_d2_policy_routes_to_the_byte_pinned_reader():
    from proofops.adapters.local.claim_source_policies import page_ocr_profile
    from proofops.adapters.local.historical_claim_replay import historical_upstage_ocr_v21_reader

    historical = historical_upstage_ocr_v21_reader()
    assert (
        page_ocr_profile(historical.PROFILE, policy=historical.claim_source_policy()) is historical
    )
    assert (
        page_ocr_profile(historical.PROFILE, policy=historical.native_policy(), native=True)
        is historical
    )


def test_only_known_acquisition_codes_are_classified_and_deferred():
    from proofops.adapters.local.claim_store import _deferred_reason
    from proofops.adapters.local.source_attestation_errors import ocr_acquisition_failure_code
    from proofops.domain.rulepacks import canonical_json
    from proofops_worker.extract_runner import _candidate_extract, _ContinuingExtractor

    assert ocr_acquisition_failure_code(ValueError("UPSTAGE_OCR_TIMEOUT")) == "UPSTAGE_OCR_TIMEOUT"
    assert ocr_acquisition_failure_code(ValueError("OCR_COLLECTION_UNTRUSTED")) is None

    class FailedExtractor:
        def extract(self, packet):
            raise ValueError("UPSTAGE_HTTP_504")

    packet = {"untrusted_document_data": {"text": "Emissions were 12 tonnes.", "kind": "paragraph"}}
    payload = _candidate_extract(
        FailedExtractor(), packet, {"analysis_profile_policy": {"provider_resilience": True}}
    )
    assert _deferred_reason(canonical_json(payload)) == (
        "ocr_acquisition_unresolved:UPSTAGE_HTTP_504"
    )

    class DeferredLive:
        def extract(self, packet):
            return _candidate_extract(
                FailedExtractor(),
                packet,
                {"analysis_profile_policy": {"provider_resilience": True}},
            )

    packet["untrusted_document_data"]["source_id"] = "source-1"
    continuing = _ContinuingExtractor(DeferredLive(), object(), {}, {"source-1"}, 1)
    continuing.extract(packet)
    assert continuing.deferred == {"source-1": "ocr_acquisition_unresolved:UPSTAGE_HTTP_504"}
    assert not continuing.processed


def test_versioned_transport_exposes_only_fixed_timeout_and_format_codes():
    with pytest.raises(ValueError, match="^UPSTAGE_OCR_TIMEOUT$"):
        d2_reader._checked_transport(
            lambda _: (_ for _ in ()).throw(TimeoutError("private transport detail"))
        )(b"png")
    with pytest.raises(ValueError, match="^UPSTAGE_OCR_INVALID_RESPONSE$"):
        d2_reader._checked_transport(lambda _: (b"not-json", "request-id"))(b"png")


def test_claim_replay_dispatches_through_the_current_d2_reader():
    assert d2_reader.replay_claim_spans.__globals__["for_run"] is d2_reader.for_run
