"""Normal OCR acquisition and exact fresh replay retain all H7/HX3 guards."""

from copy import deepcopy
from types import SimpleNamespace

from proofops.domain.provenance import canonical_hash

from tests.integration.test_claim_source_v3 import synthetic


def test_normal_reader_retains_authorized_store_and_historical_store_stays_local():
    from proofops.adapters.local import upstage_ocr_profile_rg1_v17 as fixed
    from proofops.adapters.local import upstage_ocr_profile_v16 as old

    supplied = SimpleNamespace(ledger=None)
    assert fixed.Reader(supplied, run_id="rg1").store is supplied
    assert old.Reader(supplied, run_id="rg1").store is not supplied


def test_fresh_claim_reuse_requires_whole_original_receipt(monkeypatch):
    from proofops.adapters.local import upstage_ocr_profile_rg1_v17 as reader
    from proofops.adapters.local import verified_read_cache as cache
    from proofops.application.analysis_profile import VERIFIED_READ_V9_POLICY
    from proofops.application.claims import (
        Claim,
        ClaimDiscovery,
        ClaimScope,
        ExtractionProfile,
        ExtractionReceipt,
    )

    source, graph, ref = synthetic("ESG policy 10% achieved")
    policy = reader.claim_source_policy()
    profile = ExtractionProfile("a" * 64, "b" * 64, "c" * 64, False)
    extraction = ExtractionReceipt(
        ref.source_id, "a" * 64, canonical_hash({}), "{}", profile, "success"
    )

    # A real source attestation is required even when the negative verdict is reusable.
    def missing(*args, **kwargs):
        raise ValueError("OCR_COLLECTION_UNTRUSTED")

    receipt = reader.Reader(SimpleNamespace(fetch=missing), run_id="rg1").attest_claim_spans(
        graph, source, (ref,), tenant_id=graph.tenant_id
    )
    discovery = ClaimDiscovery(
        ClaimScope(graph.tenant_id, graph.document_version_id, graph.parse_manifest_id),
        graph.source_sha256,
        (
            Claim(
                "rg1",
                graph.tenant_id,
                graph.document_version_id,
                graph.parse_manifest_id,
                graph.source_sha256,
                ref.quote,
                (ref,),
                "unverified",
                (),
                extraction,
            ),
        ),
        (),
        (ref.source_id,),
        (extraction,),
        False,
        (),
    )
    monkeypatch.setenv("PROOFOPS_VERIFIED_READ_CACHE", VERIFIED_READ_V9_POLICY["profile"])
    cache.remember_fresh_attestation(
        reader=reader,
        policy=policy,
        receipt=receipt,
        graph=graph,
        source=source,
        refs=(ref,),
        tenant_id=graph.tenant_id,
    )
    assert (
        cache.reuse_fresh_attestation(
            reader=reader,
            policy=policy,
            receipt=receipt,
            graph=graph,
            source=source,
            discovery=discovery,
            tenant_id=graph.tenant_id,
        )
        is not None
    )
    for changed in (dict(receipt, run_id="other"), dict(receipt, records=[])):
        assert (
            cache.reuse_fresh_attestation(
                reader=reader,
                policy=policy,
                receipt=changed,
                graph=graph,
                source=source,
                discovery=discovery,
                tenant_id=graph.tenant_id,
            )
            is None
        )
    forged = deepcopy(receipt)
    forged["records"][0]["reason"] = "forged"
    forged["artifact_sha256"] = canonical_hash(
        {k: v for k, v in forged.items() if k != "artifact_sha256"}
    )
    assert (
        cache.reuse_fresh_attestation(
            reader=reader,
            policy=policy,
            receipt=forged,
            graph=graph,
            source=source,
            discovery=discovery,
            tenant_id=graph.tenant_id,
        )
        is None
    )
    assert (
        cache.reuse_fresh_attestation(
            reader=reader,
            policy=policy,
            receipt=receipt,
            graph=graph,
            source=source + b"x",
            discovery=discovery,
            tenant_id=graph.tenant_id,
        )
        is None
    )


def test_adaptive_parser_batches_normal_pages_and_bounds_large_pages():
    import io

    from proofops.adapters.parsing.h6_local_pages_v2 import batches
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(13):
        writer.add_blank_page(width=600, height=800)
    stream = io.BytesIO()
    writer.write(stream)
    assert batches(stream.getvalue(), list(range(1, 14))) == [list(range(1, 14))]
    writer = PdfWriter()
    for _ in range(8):
        writer.add_blank_page(width=3543, height=2362)
    stream = io.BytesIO()
    writer.write(stream)
    assert batches(stream.getvalue(), list(range(1, 9))) == [[1, 2, 3, 4], [5, 6, 7, 8]]


def test_new_policy_keeps_v16_pin_and_domain_improvements():
    from proofops.adapters.local import upstage_ocr_profile_rg1_v17
    from proofops.adapters.local.claim_source_policies import claim_source_reader
    from proofops.application.analysis_profile import (
        FINALS_I16_POLICY,
        FINALS_RG1_POLICY,
        V2_PROFILE,
        policy_for,
        publication_policy_for,
    )

    pin = canonical_hash(FINALS_I16_POLICY)
    assert pin == "0ba34ae8e874be60abff3d86a8414e3d8c13464c944f6359e27eb08543bd3f20"
    assert policy_for(V2_PROFILE, pinned_hash=pin) == FINALS_I16_POLICY
    assert publication_policy_for(V2_PROFILE, pinned_hash=pin) == FINALS_I16_POLICY
    assert (
        policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_RG1_POLICY)) == FINALS_RG1_POLICY
    )
    assert canonical_hash(FINALS_RG1_POLICY) != pin
    for key in (
        "structural_quality_policy",
        "native_figure_policy",
        "result_outcome_projection",
        "failure_diagnostics",
        "replicas",
        "general_certification",
    ):
        assert FINALS_RG1_POLICY[key] == FINALS_I16_POLICY[key]
    assert (
        claim_source_reader(upstage_ocr_profile_rg1_v17.claim_source_policy())
        is upstage_ocr_profile_rg1_v17
    )


def test_adaptive_parser_retains_memory_bisection_and_bad_page_hold(tmp_path, monkeypatch):
    from proofops.adapters.parsing import h6_local_pages_v2

    from tests.unit import test_h6_robustness as old

    monkeypatch.setattr(old, "h6_local_pages", h6_local_pages_v2)
    old.test_batch_memory_failure_bisects_and_only_bad_page_is_unreadable(tmp_path)


def test_cold_claim_replay_never_fetches_page_ocr():
    from proofops.adapters.local import upstage_ocr_profile_rg1_v17 as module

    source, graph, ref = synthetic("ESG policy 10% achieved")
    calls = []

    def missing(*args, **kwargs):
        calls.append(1)
        raise ValueError("OCR_COLLECTION_UNTRUSTED")

    reader = module.Reader(SimpleNamespace(fetch=missing), run_id="rg1-replay")
    receipt = reader.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    assert calls  # Normal acquisition tried the supplied, authorized store.
    calls.clear()
    assert (
        reader.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=graph.tenant_id)
        == receipt
    )
    assert calls == []


def test_hosted_prepare_keeps_explicit_v16_pin(tmp_path):
    from proofops.application.analysis_profile import FINALS_I16_POLICY

    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf

    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(source_pdf())
    config = dict(
        analysis_profile="finals-unattended-v2",
        llm_provider="openai",
        report_year=2025,
        period_start="2025-01-01",
        period_end="2025-12-31",
    )
    pin = canonical_hash(FINALS_I16_POLICY)
    argv = prepare_argv(
        pdf,
        tmp_path / "state",
        "11111111-1111-4111-8111-111111111111",
        config,
        dict(analysis_profile_sha256=pin),
    )
    assert argv[argv.index("--analysis-policy-sha256") + 1] == pin
