"""V20's actual default wiring, combined extraction and bounded publication guards."""

from argparse import Namespace
from dataclasses import asdict

import pytest
from proofops.adapters.local.claim_source_policies import page_ocr_profile, publication_reader
from proofops.application import analysis_profile as profiles
from proofops.application.tagging import fact_assembly_c3_v2_legacy as c3
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor
from proofops_api.hosted_analysis import operator_profiles

from tests.integration.test_extraction_atomic import SelectAll
from tests.integration.test_upstage_extraction import packet


def test_v20_default_and_old_v19_pin_are_both_dispatchable():
    policy = profiles.policy_for(
        profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I20_POLICY)
    )
    assert policy == profiles.FINALS_I20_POLICY
    assert policy["integration_profile"] == "finals-20261015-v20"
    assert policy["source"] == "upstage-ocr-page-v21"
    assert policy["scope_ranking"] == "W5-v1"
    assert policy["fact_assembly_profile"] == "grade-relevant-unanimity-v1"
    assert policy["direct_certification_policy"] == c3.POLICY
    assert not policy["general_certification"]["enabled"]
    assert policy["replicas"] == 3
    assert canonical_hash(policy) != canonical_hash(profiles.FINALS_I19_POLICY)
    for old in (
        profiles.FINALS_I20_INITIAL_POLICY,
        profiles.FINALS_I19_POLICY,
        profiles.FINALS_P2_POLICY,
        profiles.FINALS_I18_POLICY,
    ):
        digest = canonical_hash(old)
        assert profiles.policy_for(profiles.V2_PROFILE, pinned_hash=digest) == old
        assert profiles.publication_policy_for(profiles.V2_PROFILE, pinned_hash=digest) == old
    assert operator_profiles({})["analysis_profile"] == profiles.V2_PROFILE
    args = Namespace(
        analysis_profile=profiles.V2_PROFILE,
        resume=False,
        analysis_policy_sha256=canonical_hash(profiles.FINALS_I20_POLICY),
    )
    profiles.apply_pilot_profile(args)
    assert args.extraction_atomic_v3 and args.extraction_failure_diagnostics
    assert args.extraction_table_rows and args.extraction_linewrap_join
    assert args.claim_source_profile == "upstage-ocr-page-v21"


@pytest.mark.parametrize("dispatch_local_ids", [False, True])
def test_combined_atomic_prose_retains_table_mode_and_exact_selected_offsets(
    tmp_path, dispatch_local_ids
):
    text = (
        "또한 소비자시민모임에서 주최하는 에너지위너상을 수상하여 친환경 및 에너지 절감 운영을 "
        "인정받았으며, ISO 14001 인증을 통해 체계적인 환경 관리 역량을 유지하고 있습니다."
    )
    probe = SelectAll()
    extractor = UpstageClaimExtractor(
        probe,
        tmp_path,
        extraction_source_ids=True,
        extraction_table_rows=True,
        extraction_linewrap_join=True,
        extraction_atomic_v3=True,
        extraction_failure_diagnostics=True,
        extraction_i4_identity=dispatch_local_ids,
    )
    data = packet(text)
    data["extraction_profile"] = asdict(extractor.profile)
    result = extractor.extract(data)
    assert len(result["spans"]) == 2
    assert all(s["quote"] == text[s["char_start"] : s["char_end"]] for s in result["spans"])
    assert "에너지위너상" not in result["spans"][1]["quote"]
    assert "ISO 14001" in result["spans"][1]["quote"]
    assert extractor.extract(data) == result
    assert len(probe.calls) == 1


def test_historical_v21_keeps_v20_policies_and_current_publication_is_guarded():
    current = page_ocr_profile("upstage-ocr-page-v21")
    previous = page_ocr_profile("upstage-ocr-page-v20")
    assert publication_reader(current.claim_source_policy()) is current
    from proofops.adapters.local.historical_prose_replay import historical_pre_d2_reader

    historical = historical_pre_d2_reader()
    pinned = page_ocr_profile("upstage-ocr-page-v21", policy=historical.claim_source_policy())
    assert pinned.native_policy() == previous.native_policy()
    assert pinned.table_span_policy() == previous.table_span_policy()
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_MISMATCH"):
        publication_reader(pinned.claim_source_policy())
    altered = current.claim_source_policy() | dict(verifier_sha256="0" * 64)
    with pytest.raises(ValueError, match="CLAIM_SOURCE_POLICY_UNKNOWN"):
        publication_reader(altered)


def test_v21_attestation_preserves_worker_checkpoint_identity(monkeypatch):
    from types import SimpleNamespace

    from proofops.adapters.local import upstage_ocr_profile_v21 as reader

    from tests.integration.test_claim_source_v3 import synthetic

    monkeypatch.setattr(reader.PageOCRStore, "from_env", lambda: SimpleNamespace())
    source, graph, ref = synthetic("ESG policy 10% achieved")
    proof = reader.attest_claim_spans(
        graph,
        source,
        (ref,),
        tenant_id=graph.tenant_id,
        run_id="55555555-5555-4555-8555-555555555555",
    )
    assert proof["graph_sha256"] == canonical_hash(asdict(graph))
    assert proof["policy"] == reader.claim_source_policy()
    assert proof["records"][0]["status"] == "verified"
    assert proof["artifact_sha256"] == canonical_hash(
        {k: v for k, v in proof.items() if k != "artifact_sha256"}
    )
    with pytest.raises(ValueError, match="I20_CLAIM_RECEIPT_MISMATCH"):
        reader.for_run(proof["run_id"]).recompute_claim_receipt(
            proof | dict(artifact_sha256="0" * 64), graph, source, (ref,), tenant_id=graph.tenant_id
        )


@pytest.mark.parametrize(
    "policy",
    [
        profiles.FINALS_I19_POLICY,
        profiles.FINALS_I20_POLICY,
        profiles.FINALS_I20_INITIAL_POLICY,
        profiles.FINALS_S2_SPEED_POLICY,
    ],
)
def test_hosted_preparation_accepts_the_historical_v19_pin(tmp_path, policy):
    from pypdf import PdfWriter

    from evaluation.hosted_r108 import prepare_argv

    pdf = tmp_path / "selected.pdf"
    writer = PdfWriter()
    writer.add_blank_page(300, 300)
    writer.write(pdf)
    pin = canonical_hash(policy)
    argv = prepare_argv(
        pdf,
        tmp_path / "state",
        "11111111-1111-4111-8111-111111111111",
        dict(report_year=2025, period_start="2024-01-01", period_end="2024-12-31"),
        dict(
            pages=[36],
            claim_pages=[36],
            pipeline_profile=profiles.V2_PROFILE,
            analysis_profile_sha256=pin,
        ),
    )
    assert argv[argv.index("--analysis-policy-sha256") + 1] == pin
    assert "--analysis-profile" in argv
