"""D2 regressions: replay saved OCR collections and hold failed OCR blocks."""

from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest
from proofops.adapters.local import upstage_ocr_profile_v20 as p3_reader
from proofops.adapters.local import upstage_ocr_profile_v21 as d2_reader


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

    assert d2_reader.Reader.replay_tables(
        instance, receipt, graph, b"source", tenant_id="tenant"
    ) is graph
    assert getattr(active, "_saved_collections", None) is None


def test_p3_table_replay_mismatch_is_reproducible_when_saved_collection_is_not_bound():
    collection = {"manifest": {"physical_page": 1}, "request_id": "saved"}
    receipt = {"base_receipt": {"page_collections": [collection]}}
    graph = object()
    instance, active = _reader_for_replay(p3_reader, receipt, graph, [collection])
    with pytest.raises(ValueError, match="OCR_TABLE_RECEIPT_MISMATCH"):
        p3_reader.Reader.replay_tables(
            instance, receipt, graph, b"source", tenant_id="tenant"
        )

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


def test_attestation_holds_only_the_page_with_a_known_ocr_acquisition_failure():
    from tests.integration.test_claim_source_verification import inputs

    source, graph, ref = inputs()
    second = replace(ref, page_num=2)

    class Previous:
        _saved_collections = None

        def attest_claim_spans(self, graph, source, refs, *, tenant_id):
            refs = tuple(refs)
            if refs[0].page_num == 2:
                raise ValueError(
                    "OCR_COLLECTION_FAILED_RESERVATION_RETAINED:UPSTAGE_HTTP_429"
                )
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
    receipt = instance.attest_claim_spans(
        graph, source, (ref, second), tenant_id=graph.tenant_id
    )
    assert [record["status"] for record in receipt["records"]] == ["verified", "unresolved"]
    assert receipt["records"][1]["reason"] == "ocr_acquisition_unresolved:UPSTAGE_HTTP_429"

    replay = object.__new__(d2_reader.Reader)
    replay.run_id = instance.run_id
    replay.previous = Previous()
    assert replay.recompute_claim_receipt(
        receipt, graph, source, (ref, second), tenant_id=graph.tenant_id
    ) == receipt


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
    continuing = _ContinuingExtractor(
        DeferredLive(), object(), {}, {"source-1"}, 1
    )
    continuing.extract(packet)
    assert continuing.deferred == {
        "source-1": "ocr_acquisition_unresolved:UPSTAGE_HTTP_504"
    }
    assert not continuing.processed


def test_versioned_transport_exposes_only_fixed_timeout_and_format_codes():
    with pytest.raises(ValueError, match="^UPSTAGE_OCR_TIMEOUT$"):
        d2_reader._checked_transport(
            lambda _: (_ for _ in ()).throw(TimeoutError("private transport detail"))
        )(b"png")
    with pytest.raises(ValueError, match="^UPSTAGE_OCR_INVALID_RESPONSE$"):
        d2_reader._checked_transport(lambda _: (b"not-json", "request-id"))(b"png")
