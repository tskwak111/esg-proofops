"""A new execution pin must retain the existing table/occurrence presentation."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

from proofops.application.analysis_profile import S2_POLICY
from proofops.domain.provenance import canonical_hash
from proofops_api import hosted_results

from tests.integration.test_batch_attestation_cache import discovery_for
from tests.unit.test_pb1_source import fixture


def test_s2_result_keeps_occurrence_metadata(tmp_path, monkeypatch):
    graph, source, ref = fixture()
    discovery = discovery_for(graph, (ref,))
    (tmp_path / "outcome.json").write_text(json.dumps(dict(status="completed")))
    (tmp_path / "pilot.json").write_text("{}")
    claims = SimpleNamespace(
        store=SimpleNamespace(
            jobs=SimpleNamespace(get_run=lambda *a: dict(extract_job={}, tag_job={}))
        ),
        current_tag=lambda *a: None,
        summary=lambda claim, current: claim.to_summary(),
        missing_evidence=lambda *a, **kw: [],
    )
    tags = SimpleNamespace(
        _load_snapshot_with_evidence=lambda *a: (
            dict(analysis_profile_policy_sha256=canonical_hash(S2_POLICY), claims=[]),
            ({}, discovery, graph),
        )
    )
    reviews = SimpleNamespace(store=SimpleNamespace(page=lambda *a, **kw: dict(items=[])))

    @contextmanager
    def services(*a):
        yield "run", claims, tags, reviews

    monkeypatch.setattr(hosted_results, "services", services)
    result = hosted_results.read_result(tmp_path, source.tenant_id, [1])
    assert result["claims"][0]["duplicate_occurrences"] == [discovery.claims[0].claim_id]
