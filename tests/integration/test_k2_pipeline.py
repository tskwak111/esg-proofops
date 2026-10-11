"""New K2 pin passes real local run/worker wiring; no external transport."""

import json

import pytest
from proofops.application.analysis_profile import FINALS_K2_POLICY
from proofops.application.runs import RunService
from proofops.domain.provenance import canonical_hash

from tests.integration.test_local_tag_runner import TENANT, verified_setup


def test_opt_in_k2_worker_explains_unanalyzed_claim_without_confirming(tmp_path, monkeypatch):
    init = RunService.__init__

    def profile(self, *args, **kwargs):
        kwargs.update(
            pipeline_profile="finals-unattended-v2",
            analysis_policy_sha256=canonical_hash(FINALS_K2_POLICY),
        )
        init(self, *args, **kwargs)

    monkeypatch.setattr(RunService, "__init__", profile)
    service, run_id, runner, _, _ = verified_setup(tmp_path, monkeypatch)
    runner.preliminary = lambda *_: None
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "completed"
    snapshot = service.store.snapshot(TENANT, run_id)
    assert snapshot["analysis_profile_policy"] == FINALS_K2_POLICY
    items = runner.tags.load_snapshot(TENANT, run_id)["claims"]
    assert items
    for item in items:
        assert item["decision"] is None
        assert item["provisional_grade"]["display_type"] == "hold"
        assert item["provisional_grade"]["hold_reasons"]
        assert "근거 없음" not in item["provisional_grade"]["hold_reasons"]


def test_preliminary_transport_accepts_exact_k2_policy_before_dispatch(tmp_path, monkeypatch):
    from proofops.application.tagging.k2_recovery import POLICY

    from tests.integration.test_glyph_display_text import fixture_catalog
    from tests.integration.test_upstage_preliminary_transport import configured

    adapter, _, calls, request, envelope, claim, graph = configured(tmp_path, monkeypatch)
    catalog = fixture_catalog(graph, {})
    adapter._display_catalog = catalog
    envelope["display_text"] = catalog.preliminary_pins(envelope, claim.source_refs)
    envelope["preliminary_recovery_policy"] = POLICY
    request.update(packet_sha256=canonical_hash(envelope), user_json=json.dumps(envelope))
    _, wire, _, _, _ = adapter._wire_request(request)
    assert "preliminary_recovery_policy" not in json.loads(wire)
    assert not calls
    envelope["preliminary_recovery_policy"] = POLICY | dict(profile="tampered")
    request.update(packet_sha256=canonical_hash(envelope), user_json=json.dumps(envelope))
    with pytest.raises(ValueError, match="K2_RECOVERY_POLICY_MISMATCH"):
        adapter._wire_request(request)
