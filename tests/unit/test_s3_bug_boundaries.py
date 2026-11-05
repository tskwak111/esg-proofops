"""B1/B5: corrupt persisted identities fail closed; valid replay bytes stay fixed.

Publication fixtures isolate PDF admission and C3's reviewed identity allowlist.
Receipt parsing, assembly, replay, Python decisions and SQLite revisions are real;
all provider records are explicitly fabricated offline test data.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from proofops.adapters.local import c3_publication, c4_publication
from proofops.adapters.local.analysis_store import LocalAnalysisStore
from proofops.adapters.local.review_store import LocalSQLiteReviewStore
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.reviews import ReviewInputs
from proofops.application.tagging import fact_assembly_c3, fact_assembly_c4
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import RuleContext

from tests.acceptance.test_upload import TENANT
from tests.integration.test_analysis_api import _http
from tests.integration.test_local_extract_runner import extraction_setup
from tests.integration.test_run_lifecycle import validate
from tests.unit.test_c2_assembly import case, seal
from tests.unit.test_c4_assembly import prepared

RUN = "44444444-4444-4444-8444-444444444444"


def _bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _publication(
    path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> tuple[c3_publication.LocalC3Publication | c4_publication.LocalC4Publication, ReviewInputs]:
    data, votes = case() if kind == "C3" else prepared()
    policy = fact_assembly_c3 if kind == "C3" else fact_assembly_c4
    adapter = c3_publication if kind == "C3" else c4_publication
    graph = replace(
        data["graph"],
        candidates=tuple(replace(c, synthetic=False) for c in data["graph"].candidates),
    )
    pack = replace(
        data["rulepack"], status="active", approved_by="offline-fixture", approved_at="2026-01-01"
    )
    original = data["packet"]
    packet = freeze_packet(
        {k: v for k, v in original.to_dict().items() if k != "packet_sha256"}
        | dict(
            run_id=RUN,
            graph_sha256=canonical_hash(asdict(graph)),
            retrieval_packet_sha256=original.packet_sha256,
        )
    )
    claim = data["context"].claim
    for vote in votes:
        vote["identity"].update(
            graph_sha256=canonical_hash(asdict(graph)),
            packet_sha256=packet.packet_sha256,
            rulepack_sha256=pack.sha256,
        )
        vote.update(
            simulated=False,
            response_sha256="f" * 64,
            cache_identity=dict(
                tenant_id=claim.tenant_id,
                source_sha256=graph.source_sha256,
                replica=vote["replicate_id"],
                role="elements",
            ),
        )
    if kind == "C3":
        monkeypatch.setattr(fact_assembly_c3, "REVIEWED_IDENTITY", dict(votes[0]["identity"]))
    receipt = policy.assemble(
        [seal(v) for v in votes],
        context=data["context"],
        graph=graph,
        packet=packet,
        rulepack=pack,
    )
    assert receipt.to_dict()["public_auto_confirmed"]
    consensus, decision = policy.publication_values(
        receipt.to_dict(), rulepack=pack, tag_revision=1
    )
    inputs = ReviewInputs(
        RUN,
        data["context"],
        graph,
        pack,
        RuleContext(
            claim.tenant_id, claim.document_version_id, claim.claim_id, packet.packet_sha256
        ),
        packet,
        original,
        (),
        consensus,
        {},
        decision=decision,
        fact_assembly_profile=policy.PROFILE,
        fact_assembly_receipt=receipt,
    )
    inputs.validate()
    publication = (
        c3_publication.LocalC3Publication(path)
        if kind == "C3"
        else c4_publication.LocalC4Publication(path)
    )
    evidence = dict(
        parser_artifact=dict(
            candidates=[asdict(c) for c in graph.candidates],
            issues=[asdict(i) for i in graph.issues],
        ),
        source_receipt={"offline_fixture": True},
    )
    (path / f"{kind.lower()}-evidence.json").write_bytes(_bytes(evidence))
    (path / "original.pdf").write_bytes(b"offline PDF admission boundary")
    monkeypatch.setattr(adapter, "replay_source", lambda *args, **kwargs: graph)
    snapshot = dict(
        tenant_id=claim.tenant_id,
        run_id=RUN,
        document=dict(version_id=claim.document_version_id, sha256=graph.source_sha256),
        rulepack=asdict(pack),
        analysis_profile_policy=policy.POLICY,
        analysis_profile_policy_sha256=policy.POLICY_HASH,
        **{f"{kind.lower()}_evidence_sha256": canonical_hash(evidence)},
    )
    snapshot["input_hash"] = canonical_hash(snapshot)
    with publication.runs.jobs._transaction() as db:
        db.execute(
            "INSERT INTO run_snapshots VALUES (?, ?, ?)",
            (claim.tenant_id, RUN, json.dumps(snapshot)),
        )
    publication.runs.jobs.create_run(claim.tenant_id, RUN, claim.document_version_id)
    publication.service.publish(inputs)
    return publication, inputs


@pytest.mark.parametrize("kind", ["C3", "C4"])
def test_valid_publication_replays_identical_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    publication, inputs = _publication(tmp_path, monkeypatch, kind)
    claim = inputs.context.claim
    args = (claim.tenant_id, RUN, claim.claim_id)
    before = _bytes(publication.store.history(*args))
    artifacts = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
    reopened = publication.load_inputs(*args)
    assert _bytes(reopened.snapshot()) == _bytes(inputs.snapshot())
    assert _bytes(publication.store.history(*args)) == before
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.json")} == artifacts
    # Fixed before the implementation change: includes the entire public result.
    assert sha256(_bytes(publication.result(*args))).hexdigest() == PUBLICATION_HASHES[kind]


PUBLICATION_HASHES = {
    "C3": "8e573437f5d8cfad2bf9c848850d4c621a52f3bc6e4b17b29eee758d9babad0c",
    "C4": "7e6909d5765229ad71181aba46c863020216004f49749070382593fbc656d4df",
}


@pytest.mark.parametrize("kind", ["C3", "C4"])
@pytest.mark.parametrize("missing", ["null", "key"])
def test_missing_publication_receipt_is_an_integrity_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, missing: str
) -> None:
    publication, inputs = _publication(tmp_path, monkeypatch, kind)
    claim = inputs.context.claim
    args = (claim.tenant_id, RUN, claim.claim_id)
    with publication.runs.jobs._transaction() as db:
        record_id = f"{claim.claim_id}:0000000001"
        tag = publication.runs.jobs._get(db, claim.tenant_id, RUN, "tag_revision", record_id)
        if missing == "null":
            tag["inputs"]["fact_assembly_receipt"] = None
        else:
            del tag["inputs"]["fact_assembly_receipt"]
        # Simulate damaged legacy storage only in this disposable test database.
        # Normal writers correctly refuse to overwrite immutable revisions.
        db.execute("DROP TRIGGER review_immutable_update")
        db.execute(
            "UPDATE job_records SET value=? WHERE tenant_id=? AND run_id=? "
            "AND kind='tag_revision' AND record_id=?",
            (_bytes(tag), claim.tenant_id, RUN, record_id),
        )
    publication.store = LocalSQLiteReviewStore(publication.runs.jobs)  # Restore the guard.
    before = _bytes(publication.store.history(*args))
    with pytest.raises(ValueError, match=f"^{kind}_PUBLICATION_RECEIPT_REQUIRED$"):
        publication.load_inputs(*args)
    assert _bytes(publication.store.history(*args)) == before


@pytest.mark.parametrize("identity", ["claim_id", "tenant_id", "document_version_id"])
def test_invalid_assurance_identity_is_rejected_before_snapshot_or_matching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity: str
) -> None:
    service, run_id, runner, now, _ = extraction_setup(tmp_path, monkeypatch)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    discovery = runner.claims.load(TENANT, run_id)
    corrupt = replace(discovery.claims[0], **{identity: "not-a-uuid"})
    monkeypatch.setattr(
        runner.claims,
        "load",
        lambda *args: replace(discovery, claims=(corrupt, *discovery.claims[1:])),
    )
    store = LocalAnalysisStore(service.store, service.uploads, runner.parser, runner.claims)
    with pytest.raises(ValueError, match="^invalid assurance claim identity$"):
        store.assurance(TENANT, run_id, cursor=None, limit=50, now=now[0])
    http, _ = _http(service, runner, now, role="viewer")
    response = http.get(f"/v1/runs/{run_id}/assurance")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ARTIFACT_UNAVAILABLE"
    validate("Error", response.json())


def test_valid_assurance_identity_keeps_unknown_response_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, run_id, runner, now, _ = extraction_setup(tmp_path, monkeypatch)
    assert runner.run_once(tenant_id=TENANT, run_id=run_id) == "committed"
    http, _ = _http(service, runner, now, role="viewer")
    response = http.get(f"/v1/runs/{run_id}/assurance")
    assert response.status_code == 200
    assert (
        sha256(response.content).hexdigest()
        == "e2edb6d40c65b7ec77b235a69f4cf3d12a30941091ac9fd407b2e58903e0e9bf"
    )
    validate("AssuranceMatchPage", response.json())
