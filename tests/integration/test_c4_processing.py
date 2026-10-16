"""Report automatic orchestration, using synthetic source isolation and real matcher/engine."""

import json
from dataclasses import replace

import pytest
from proofops.adapters.local import c4_processing
from proofops.application.reviews import ReviewRejected
from proofops.application.tagging.fact_assembly_c4 import PROFILE

from tests.integration.test_c2_receipt_lifecycle import inputs_for
from tests.unit.test_c4_assembly import prepared


@pytest.mark.parametrize("receipt", ["missing", "old_c2"])
def test_c4_review_cannot_activate_missing_or_old_receipt(tmp_path, receipt):
    inputs = inputs_for(tmp_path)
    changed = replace(
        inputs,
        fact_assembly_profile=PROFILE,
        fact_assembly_receipt=None if receipt == "missing" else inputs.fact_assembly_receipt,
    )
    with pytest.raises(ReviewRejected, match="C4_PUBLICATION_REPLAY_MISMATCH"):
        changed.validate()


def test_report_automatically_freezes_one_packet_and_requests_three_separate_votes(
    tmp_path, monkeypatch
):
    inputs, votes = prepared()
    observed = []
    candidate = inputs["packet"].to_dict()["c4_candidate"]
    monkeypatch.setattr(
        c4_processing,
        "prepare_candidate",
        lambda *a, **kw: inputs | dict(candidate=candidate, status="ready", source_receipt={}),
    )

    def transport(request):
        observed.append(request)
        # Regression for the API failure: JSON mode must receive its exact wire schema.
        assert json.loads(request["system"].split("Output JSON schema:\n")[1]) == json.loads(
            request["schema_json"]
        )
        return dict(
            schema_valid=True,
            provider_request_id=f'fixture-{request["replica"]}',
            provider="codex-sim",
            simulated=True,
            model_binding_sha256="a" * 64,
            content=json.dumps(votes[request["replica"] - 1]["raw"]),
        )

    result = c4_processing.process_report(
        inputs["graph"],
        b"synthetic",
        inputs["rulepack"],
        run_id="fixture-run",
        output=tmp_path,
        transport=transport,
    )
    assert result["extra_calls"] == 3
    assert result["confirmed_count"] == 0
    assert result["rows"][0]["receipt"]["candidate_auto_confirmed"]
    assert len({r["id"] for r in observed}) == 3
    assert len({json.loads(r["user_json"])["packet_sha256"] for r in observed}) == 1
    assert [r["replica"] for r in observed] == [1, 2, 3]
    assert not (tmp_path / inputs["context"].claim.claim_id).exists()


def test_zero_candidate_report_never_calls_or_rewrites_existing_results(tmp_path):
    inputs, _ = prepared()
    graph = replace(inputs["graph"], blocks=())
    marker = tmp_path / "historical-result.json"
    marker.write_bytes(b'{"confirmed":0}')
    result = c4_processing.process_report(
        graph,
        b"synthetic",
        inputs["rulepack"],
        run_id="fixture-run",
        output=tmp_path,
        transport=lambda r: pytest.fail("unexpected paid call"),
    )
    assert result["confirmed_count"] == result["extra_calls"] == result["nomination_count"] == 0
    assert marker.read_bytes() == b'{"confirmed":0}'


def test_publication_replays_source_admission_before_accepting_verified_graph(tmp_path):
    from dataclasses import asdict

    from proofops.adapters.local.c4_publication import LocalC4Publication

    inputs, _ = prepared()
    publication = LocalC4Publication(tmp_path)
    parser_artifact = dict(
        candidates=[asdict(c) for c in inputs["graph"].candidates],
        issues=[asdict(i) for i in inputs["graph"].issues],
    )
    # Merely marking a graph verified cannot mint a genuine source receipt.
    with pytest.raises(ValueError, match="C4_SELECTED_SOURCE_POLICY_MISMATCH"):
        publication.initialize(
            inputs | dict(source_receipt={}),
            None,
            source=b"synthetic",
            parser_artifact=parser_artifact,
        )
    assert not (tmp_path / "pilot.json").exists()
