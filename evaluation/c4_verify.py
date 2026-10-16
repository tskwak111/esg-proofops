"""C4 release evidence: real saved API receipt, SQLite lifecycle, HTTP and adverse fixtures."""

import json
import shutil
import time
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256

from fastapi.testclient import TestClient
from proofops.adapters.local.c4_publication import LocalC4Publication
from proofops.adapters.local.tag_store import _fact_assembly_reader
from proofops.application.authorization import AuthContext
from proofops.application.exports import REVISION_RECORDS_V2, decode_revision_record
from proofops.application.reviews import ReviewRejected
from proofops.application.tagging.fact_assembly_c4 import assemble
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted import HostedSettings, HostedStore, create_hosted_app
from proofops_api.hosted_results import read_result, result_snapshot

from evaluation.c4_general import OUT, graph_for, origin, prepare_candidate, rulepack, write
from tests.test_hosted_public import actor, login


def main():
    values = json.loads((OUT / "processing.json").read_text())
    active = values[0]["processing"]["rows"][0]
    path = OUT / "http-publication"
    path.mkdir(exist_ok=True)
    run = values[0]["processing"]["run_id"]
    data = prepare_candidate(
        graph_for("lg"), origin("lg"), active["candidate"], rulepack("lg"), run_id=run
    )
    receipt = _fact_assembly_reader(active["receipt"])
    publication = LocalC4Publication(path)
    graph = graph_for("lg")
    parser_artifact = dict(
        candidates=[asdict(c) for c in graph.candidates], issues=[asdict(i) for i in graph.issues]
    )
    review = publication.initialize(
        data, receipt, source=origin("lg"), parser_artifact=parser_artifact
    )
    claim = data["context"].claim
    before = publication.store.history(claim.tenant_id, run, claim.claim_id)
    original_history = canonical_hash(before)
    assert (
        publication.initialize(data, receipt, source=origin("lg"), parser_artifact=parser_artifact)
        == review
    )
    assert (
        canonical_hash(publication.store.history(claim.tenant_id, run, claim.claim_id))
        == original_history
    )
    publication = LocalC4Publication(path)
    inputs = publication.load_inputs(claim.tenant_id, run, claim.claim_id)
    result = read_result(path, claim.tenant_id, [36])
    assert result["claims"][0]["confirmed_grade"] == "E3"
    assert result["claims"][0]["confirmation_source"] == "auto_direct_certification_c3_v1"
    assert result["claims"][0]["confirmation_policy_sha256"] == active["receipt"]["policy_sha256"]
    assert result["claims"][0]["decision"]["semantic_hash"] == inputs.decision.semantic_hash
    assert "인증 유효기간: 미기재" in result["claims"][0]["confirmation_basis"]
    export = publication.export(claim.tenant_id, run, claim.claim_id)
    assert (
        decode_revision_record(export, encoding=REVISION_RECORDS_V2)["decision"]["decision"][
            "semantic_hash"
        ]
        == inputs.decision.semantic_hash
    )
    write("published-result.json", result)
    write("export.json", export)

    settings = HostedSettings(
        root=OUT / "http-surface",
        origin="https://app.example.com",
        secret="c4-local-test-" * 4,
        event_id="c4-local",
        run_usd=Decimal("0.50"),
        day_usd=Decimal("5"),
        event_usd=Decimal("5"),
        accept_uploads=True,
        consent_version="c4-local-integration-v1",
        backend="r108",
        accept_runs=True,
    )
    store = HostedStore(settings)
    auth = actor(store, tenant=claim.tenant_id)
    document = store.upload(auth, origin("lg"), "c4-original-http-upload", now=time.time())
    response = store.create_run(
        auth, document["document_id"], [36], "c4-http-local-run", now=time.time()
    )
    hosted_run = response["run_id"]
    hosted_path = (
        store.document_dir(claim.tenant_id, document["document_id"]) / "analysis" / hosted_run
    )
    hosted_path.parent.mkdir(exist_ok=True)
    if not hosted_path.exists():
        shutil.copytree(path, hosted_path)
    content = result_snapshot(path, claim.tenant_id, [36])
    with store.transaction() as db:
        store._publish_snapshot(db, hosted_run, hosted_path, content)
        db.execute(
            "UPDATE runs SET status='completed',error_code=NULL WHERE run_id=?", (hosted_run,)
        )
        db.execute("INSERT OR REPLACE INTO run_progress VALUES (?, 'result',100,1)", (hosted_run,))
        store._settle_envelope(db, hosted_run)
    app = create_hosted_app(settings)
    client, _, _, _ = login(app, store, tenant=claim.tenant_id, user=auth.user_sub)
    http = client.get(f"/v1/runs/{hosted_run}/result")
    assert http.status_code == 200, http.text
    assert canonical_hash(http.json()) == canonical_hash(result)
    source_response = client.get(
        f"/v1/runs/{hosted_run}/source-pages/36/manifest", params={"claim_id": claim.claim_id}
    )
    assert source_response.status_code == 200, source_response.text
    manifest = source_response.json()
    image = client.get(
        f"/v1/runs/{hosted_run}/source-pages/36/image",
        params=dict(
            image_sha256=manifest["image_sha256"],
            document_version_id=manifest["document_version_id"],
        ),
    )
    assert image.status_code == 200, image.text[:200]
    assert sha256(image.content).hexdigest() == manifest["image_sha256"]
    write("source-manifest.json", manifest)
    (OUT / "source-p36.png").write_bytes(image.content)
    other, _, _, _ = login(app, store)
    assert other.get(f"/v1/runs/{hosted_run}/result").status_code == 404
    assert (
        TestClient(app, base_url="https://api.example.com")
        .get(f"/v1/runs/{hosted_run}/result")
        .status_code
        == 401
    )
    old_result = (hosted_path / "result-1.json").read_bytes()
    with store.transaction() as db:
        store._publish_snapshot(db, hosted_run, hosted_path, content)
    assert (hosted_path / "result-1.json").read_bytes() == old_result
    write(
        "http-verification.json",
        dict(
            http_status=200,
            other_tenant_status=404,
            anonymous_status=401,
            source_manifest_status=200,
            source_image_status=200,
            source_sha256=graph.source_sha256,
            same_semantic_hash=inputs.decision.semantic_hash,
            old_snapshot_preserved=True,
            mode="actual local hosted auth/router/store/source renderer; no deployed worker E2E",
        ),
    )

    reviewer = AuthContext(
        "c4-local-reviewer", claim.tenant_id, "reviewer", frozenset({"viewer", "reviewer"}), "test"
    )
    body = dict(
        base_tag_revision=1,
        track="management",
        reason="C4 원문 태깅 유지",
        elements=[asdict(e) for e in inputs.consensus.candidate_elements],
    )
    try:
        publication.service.resolve_review(
            reviewer,
            review["review_id"],
            body,
            if_match='"2"',
            idempotency_key="c4-stale-revision-request",
        )
    except ReviewRejected as exc:
        assert exc.status == 412
    else:
        raise AssertionError("stale If-Match accepted")
    assert (
        canonical_hash(publication.store.history(claim.tenant_id, run, claim.claim_id))
        == original_history
    )
    resolved = publication.service.resolve_review(
        reviewer,
        review["review_id"],
        body,
        if_match='"1"',
        idempotency_key="c4-current-revision-request",
    )
    after = publication.store.history(claim.tenant_id, run, claim.claim_id)
    assert after["tags"][0] == before["tags"][0] and after["decisions"][0] == before["decisions"][0]
    assert resolved["new_tag_revision"] == 2
    assert canonical_hash(json.loads((OUT / "export.json").read_text())) == canonical_hash(export)
    write(
        "lifecycle.json",
        dict(
            stored_resumed_reloaded=True,
            public_auto_confirmed=1,
            api_export_same_semantic_hash=True,
            stale_if_match_status=412,
            human_new_tag_revision=2,
            old_revision_preserved=True,
            old_export_preserved=True,
            receipt_sha256=receipt.receipt_sha256,
        ),
    )
    negatives(data, active["receipt"])
    print(json.dumps(dict(confirmed=1, http=200, cas=412, negative_false_confirmation_count=0)))


def negatives(data, receipt, *, output_name="negative-measurements.json"):
    def seal(vote):
        value = {k: v for k, v in vote.items() if k not in ("vote_sha256", "raw_sha256")}
        value["raw_sha256"] = canonical_hash(value["raw"])
        return value | dict(vote_sha256=canonical_hash(value))

    variants = [
        ("C03-facility", "dimensions", "boundary", dict(source_index=1, quote="2025")),
        ("C03-period", "dimensions", "period", dict(source_index=0, quote="2026")),
        (
            "C04-page",
            "elements",
            "M3",
            dict(state="present", evidence=dict(source_index=0, quote="GRI 3-3")),
        ),
        (
            "C09-overlap",
            "elements",
            "M3",
            dict(state="present", evidence=dict(source_index=1, quote="2025")),
        ),
        (
            "iso-conform",
            "elements",
            "M3",
            dict(state="present", evidence=dict(source_index=0, quote="ISO 14001")),
        ),
        ("nonpossession", "elements", "M3", dict(state="unknown", evidence=None)),
        ("other-product", "dimensions", "activity", dict(source_index=0, quote="재활용 제품")),
        (
            "partial-to-all",
            "dimensions",
            "boundary",
            dict(source_index=0, quote="글로벌 전 생산 사업장"),
        ),
        ("report-year-as-validity", None, "period_kind", "explicit_current"),
        ("body-scope-conflict", "elements", "M3", dict(state="conflict", evidence=None)),
        ("missing-m4", "elements", "M4", dict(state="unknown", evidence=None)),
        ("2-of-3", "elements", "M2", dict(state="unknown", evidence=None)),
    ]
    rows = []
    for name, section, key, value in variants:
        votes = deepcopy(receipt["raw_receipts"])
        for v in votes[2:] if name == "2-of-3" else votes:
            if section:
                v["raw"][section][key] = value
            else:
                v["raw"][key] = value
        for v in votes:
            v.update(provider="c4-adversarial-extraction-fixture", simulated=True)
        result = assemble(
            [seal(v) for v in votes],
            **{k: data[k] for k in ("context", "graph", "packet", "rulepack")},
        ).to_dict()
        assert not result["candidate_auto_confirmed"] and not result["public_auto_confirmed"]
        rows.append(
            dict(
                case_id=name,
                candidate_auto_confirmed=False,
                public_auto_confirmed=False,
                blockers=result["unresolved"],
                receipt_sha256=result["receipt_sha256"],
                mode="actual-source mutated tagging fixture; not live negative-model/gold",
            )
        )
    write(output_name, dict(twelve_types=rows, false_confirmation_count=0))


if __name__ == "__main__":
    main()
