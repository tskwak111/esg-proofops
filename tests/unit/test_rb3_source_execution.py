"""RB3's S4-derived cache preserves source proof, policy pins and replay guards."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from proofops.adapters.local import fxh_claim_source, rb3_claim_source
from proofops.adapters.local.rb3_policy_evaluation import evaluate
from proofops.domain.provenance import canonical_hash

from tests.integration.test_claim_source_v3 import synthetic


def test_policy_dag_evaluation_is_exact_and_does_not_retain_stale_values(monkeypatch):
    from proofops.adapters.local import source_fxe

    before = fxh_claim_source.claim_source_policy()
    assert evaluate(fxh_claim_source.claim_source_policy) == before
    original = source_fxe.policy
    monkeypatch.setattr(source_fxe, "policy", lambda: original() | dict(changed=True))
    assert evaluate(fxh_claim_source.claim_source_policy) == fxh_claim_source.claim_source_policy()
    assert evaluate(fxh_claim_source.claim_source_policy) != before


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setattr(
        fxh_claim_source.PageOCRStore,
        "from_env",
        lambda: SimpleNamespace(fetch=lambda *a, **k: pytest.fail("unexpected OCR acquisition")),
    )
    return synthetic("ESG policy 10% achieved")


def test_all_nested_proof_bytes_match_fxh_and_forgery_is_rejected(source):
    content, graph, ref = source
    arguments = dict(tenant_id=graph.tenant_id, run_id="rb3-test")
    old = fxh_claim_source.attest_claim_spans(graph, content, (ref,), **arguments)
    new = rb3_claim_source.attest_claim_spans(graph, content, (ref,), **arguments)
    # Only the deliberately new outer execution policy and its artifact hash differ.
    assert {k: v for k, v in old.items() if k not in {"policy", "artifact_sha256"}} == {
        k: v for k, v in new.items() if k not in {"policy", "artifact_sha256"}
    }
    reader = rb3_claim_source.for_run("rb3-test")
    assert (
        reader.recompute_claim_receipt(new, graph, content, (ref,), tenant_id=graph.tenant_id)
        == new
    )
    forged = deepcopy(new)
    forged["previous_receipt"]["records"][0]["status"] = "forged"
    forged["artifact_sha256"] = canonical_hash(
        {k: v for k, v in forged.items() if k != "artifact_sha256"}
    )
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        reader.recompute_claim_receipt(forged, graph, content, (ref,), tenant_id=graph.tenant_id)
    with pytest.raises(ValueError):
        reader.attest_claim_spans(graph, content + b"changed", (ref,), tenant_id=graph.tenant_id)
    with pytest.raises(ValueError):
        reader.attest_claim_spans(graph, content, (ref,), tenant_id="other-tenant")


def test_policy_change_after_reader_creation_fails_closed(source, monkeypatch):
    content, graph, ref = source
    reader = rb3_claim_source.for_run("rb3-test")
    original = rb3_claim_source.claim_source_policy
    monkeypatch.setattr(
        rb3_claim_source, "claim_source_policy", lambda: original() | dict(changed=1)
    )
    with pytest.raises(ValueError, match="RB3_READER_POLICY_CHANGED"):
        reader.attest_claim_spans(graph, content, (ref,), tenant_id=graph.tenant_id)


def test_policy_change_during_read_discards_completed_proof(source, monkeypatch):
    content, graph, ref = source
    reader = rb3_claim_source.for_run("rb3-test")
    attest = reader.reader.attest_claim_spans
    policy = rb3_claim_source.claim_source_policy
    completed = []

    def change_after_proof(*args, **kwargs):
        result = attest(*args, **kwargs)
        completed.append(result)
        monkeypatch.setattr(
            rb3_claim_source, "claim_source_policy", lambda: policy() | dict(changed=1)
        )
        return result

    monkeypatch.setattr(reader.reader, "attest_claim_spans", change_after_proof)
    with pytest.raises(ValueError, match="RB3_READER_POLICY_CHANGED"):
        reader.attest_claim_spans(graph, content, (ref,), tenant_id=graph.tenant_id)
    assert completed


def test_rb3_hosted_child_accepts_only_registered_pin(tmp_path):
    from proofops.application.analysis_profile import RB3_POLICY

    from evaluation.hosted_r108 import prepare_argv
    from tests.test_hosted_analysis import source_pdf

    pdf = tmp_path / "original.pdf"
    pdf.write_bytes(source_pdf())
    pin = canonical_hash(RB3_POLICY)
    config = dict(
        analysis_profile="finals-unattended-v2",
        analysis_policy_sha256=pin,
        llm_provider="openai",
        report_year=2025,
        period_start="2025-01-01",
        period_end="2025-12-31",
    )
    argv = prepare_argv(
        pdf, tmp_path / "state", "tenant", config, dict(analysis_profile_sha256=pin)
    )
    assert argv[argv.index("--analysis-policy-sha256") + 1] == pin
    with pytest.raises(ValueError, match="PIN_MISMATCH"):
        prepare_argv(
            pdf, tmp_path / "state", "tenant", config, dict(analysis_profile_sha256="0" * 64)
        )
