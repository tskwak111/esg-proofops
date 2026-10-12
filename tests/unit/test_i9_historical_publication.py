"""A new default cannot remove v8's occurrence metadata during historical reads."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

from proofops.application.analysis_profile import FINALS_I8_POLICY
from proofops.domain.provenance import canonical_hash
from proofops_api import hosted_results

from tests.unit.test_pb1_source import fixture


def test_v8_duplicate_occurrences_survive_v9_default(tmp_path, monkeypatch):
    graph, source, ref = fixture()
    claims = [
        SimpleNamespace(
            claim_id=f"claim-{i}",
            tenant_id=source.tenant_id,
            quote=ref.quote,
            source_refs=(ref,),
            source_quality="unverified",
        )
        for i in (1, 2)
    ]
    discovery = SimpleNamespace(claims=claims)
    claim_store = SimpleNamespace(
        store=SimpleNamespace(
            jobs=SimpleNamespace(get_run=lambda *a: dict(extract_job={}, tag_job={}))
        ),
        current_tag=lambda *a: None,
        summary=lambda claim, current: dict(
            claim_id=claim.claim_id,
            page_num=1,
            track=None,
            quote=claim.quote,
        ),
        missing_evidence=lambda *a, **kw: [],
    )
    tags = SimpleNamespace(
        _load_snapshot_with_evidence=lambda *a: (
            dict(analysis_profile_policy_sha256=canonical_hash(FINALS_I8_POLICY), claims=[]),
            (None, discovery, graph),
        )
    )
    reviews = SimpleNamespace(store=SimpleNamespace(page=lambda *a, **kw: dict(items=[])))

    @contextmanager
    def services(*a):
        yield "run", claim_store, tags, reviews

    monkeypatch.setattr(hosted_results, "services", services)
    (tmp_path / "pilot.json").write_text("{}")
    (tmp_path / "outcome.json").write_text(json.dumps(dict(status="completed", reason=None)))
    result = hosted_results.read_result(tmp_path, source.tenant_id, [1])
    assert [c["duplicate_occurrences"] for c in result["claims"]] == [
        ["claim-1", "claim-2"],
        ["claim-1", "claim-2"],
    ]
    assert all(
        c["table_observation"]["verification_state"] == "unresolved" for c in result["claims"]
    )
