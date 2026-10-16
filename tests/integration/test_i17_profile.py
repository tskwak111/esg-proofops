"""I17 composes the hotfixes without reinterpreting any historical reader pin."""

from argparse import Namespace
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest
from proofops.adapters.local import evidence_source_i17 as evidence
from proofops.adapters.local import upstage_ocr_profile_v18 as reader
from proofops.adapters.local.claim_source_policies import (
    claim_source_reader,
    page_ocr_profile,
    publication_reader,
)
from proofops.application import analysis_profile as profiles
from proofops.domain.provenance import canonical_hash


def test_v17_default_composes_all_hotfixes_and_hosted_reader():
    policy = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I17_POLICY)
    )
    assert policy == profiles.FINALS_I17_POLICY
    assert policy["integration_profile"] == "finals-20261014-v17"
    assert policy["source"] == reader.PROFILE
    for key in ("result_outcome_projection", "failure_diagnostics"):
        assert policy[key] == profiles.FINALS_I16_POLICY[key]
    for key in (
        "parser_failure_policy",
        "parser_block_failure",
        "page_recovery_policy",
        "page_recovery_policy_sha256",
        "display_failure_policy",
        "auxiliary_native_failure",
    ):
        assert policy[key] == profiles.FINALS_HX6_RESILIENT_POLICY[key]
    assert policy["input_failure_policy"] == profiles.FINALS_HX5_POLICY["input_failure_policy"]
    args = Namespace(
        analysis_profile=profiles.V2_PROFILE,
        resume=False,
        analysis_policy_sha256=canonical_hash(policy),
    )
    profiles.apply_pilot_profile(args)
    assert args.analysis_policy_sha256 == canonical_hash(policy)
    assert args.claim_source_profile == reader.PROFILE
    assert args.extraction_qc_native_figures
    assert publication_reader(reader.claim_source_policy()) is reader
    assert policy["general_certification"]["enabled"] is False
    assert policy["replicas"] == 3


@pytest.mark.parametrize(
    "name,alias",
    [
        ("FINALS_I16_POLICY", "upstage-ocr-page-v16"),
        ("FINALS_HX4_POLICY", "upstage-ocr-page-v16-hx4"),
        ("FINALS_HX5_POLICY", "upstage-ocr-page-v16-hx5"),
        ("FINALS_HX4_COMPLETE_POLICY", "upstage-ocr-page-v17"),
        ("FINALS_HX6_RESILIENT_POLICY", "upstage-ocr-page-v17"),
    ],
)
def test_historical_analysis_and_colliding_reader_pins(name, alias):
    policy = getattr(profiles, name)
    pin = canonical_hash(policy)
    assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
    assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=pin) == policy
    module = page_ocr_profile(alias)
    assert claim_source_reader(module.claim_source_policy()) is module
    assert page_ocr_profile(module.PROFILE, policy=module.native_policy(), native=True) is module
    tampered = deepcopy(module.claim_source_policy())
    tampered["verifier_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="POLICY_UNKNOWN"):
        claim_source_reader(tampered)


def test_empty_scope_and_large_source_holds_replay_without_admission(monkeypatch):
    from tests.integration.test_claim_source_v3 import synthetic

    source, graph, ref = synthetic("Environmental policy 10%")
    monkeypatch.setattr(reader._size, "LEGACY_PROOF_BYTES", 1)
    instance = reader.for_run("55555555-5555-4555-8555-555555555555")
    table = instance.attest_table_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    assert table["policy"] == reader.table_span_policy()
    assert table["records"][0]["status"] == "unresolved"
    assert (
        instance.recompute_table_span_receipt(
            table, graph, source, (ref,), tenant_id=graph.tenant_id
        )
        == table
    )
    altered_table = deepcopy(table)
    altered_table["records"][0]["status"] = "verified"
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        instance.recompute_table_span_receipt(
            altered_table, graph, source, (ref,), tenant_id=graph.tenant_id
        )
    graph = replace(graph, blocks=(), edges=(), issues=())
    proof = evidence.attest_evidence_sources(graph, source, tenant_id=graph.tenant_id)
    assert proof["records"] == []
    assert (
        evidence.replay_evidence_sources(proof, graph, source, tenant_id=graph.tenant_id) == graph
    )
    native = instance.attest_native_sources(graph, source, tenant_id=graph.tenant_id)
    assert native["records"] == []
    assert native["source_sha256"] == sha256(source).hexdigest()
    assert instance.replay_native_sources(native, graph, source, tenant_id=graph.tenant_id) == graph
    altered = deepcopy(native)
    altered["tenant_id"] = "22222222-2222-4222-8222-222222222222"
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        instance.replay_native_sources(altered, graph, source, tenant_id=graph.tenant_id)


def test_native_heading_only_page_does_not_suppress_claim_parser():
    from types import SimpleNamespace

    from proofops.adapters.parsing.hx6_upstage import native_pages

    from deploy.public.offline_fixture import TEXT, source_pdf

    source = SimpleNamespace(content=source_pdf())
    block = SimpleNamespace(kind="heading", source=SimpleNamespace(raw_text=TEXT, physical_page=1))
    batch = SimpleNamespace(blocks=(block,))
    assert native_pages(source, [1], [batch]) == []
    block.kind = "paragraph"
    assert native_pages(source, [1], [batch]) == [1]
