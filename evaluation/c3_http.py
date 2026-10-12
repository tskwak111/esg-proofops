"""Authenticated real hosted HTTP reads over the frozen C3 local result revision."""

import json
import shutil
import time
from decimal import Decimal
from hashlib import sha256

from fastapi.testclient import TestClient
from proofops.adapters.local.c3_publication import LocalC3Publication
from proofops.adapters.local.tag_store import _fact_assembly_reader
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted import HostedSettings, HostedStore, create_hosted_app
from proofops_api.hosted_results import read_result

from evaluation.c3_activation import C2, OUT, case, write
from tests.test_hosted_public import actor, login


def main():
    source_path = OUT / "publication-surface"
    source_path.mkdir(exist_ok=True)
    data = case()
    receipt = _fact_assembly_reader(json.loads((OUT / "lg-active-assembly.json").read_text()))
    publication = LocalC3Publication(source_path)
    publication.initialize(
        data,
        receipt,
        source=(OUT / "publication/original.pdf").read_bytes(),
        parser_artifact=json.loads((C2 / "lg-pilot-graph.json").read_text()),
    )
    for name in ("pilot.json", "outcome.json"):
        if not (source_path / name).exists():
            shutil.copyfile(OUT / "publication" / name, source_path / name)
    root = OUT / "http-surface"
    settings = HostedSettings(
        root=root,
        origin="https://app.example.com",
        secret="c3-local-test-" * 4,
        event_id="c3-local",
        run_usd=Decimal("0.50"),
        day_usd=Decimal("5"),
        event_usd=Decimal("5"),
        accept_uploads=True,
        consent_version="c3-local-integration-v1",
        backend="r108",
        accept_runs=True,
    )
    store = HostedStore(settings)
    manifest = json.loads((source_path / "pilot.json").read_text())
    tenant = manifest["tenant_id"]
    auth = actor(store, tenant=tenant)
    document = store.upload(
        auth,
        (OUT / "publication/original.pdf").read_bytes(),
        "c3-original-http-upload",
        now=time.time(),
    )
    response = store.create_run(
        auth, document["document_id"], [36], "c3-http-local-run", now=time.time()
    )
    run = response["run_id"]
    path = store.document_dir(tenant, document["document_id"]) / "analysis" / run
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        shutil.copytree(source_path, path)
    # Publish the already verified automatic revision, not the newer human head.
    result = read_result(source_path, tenant, [36])
    content = json.dumps(
        dict(
            tenant_id=tenant,
            page_map=[36],
            result=result,
            source_hashes={
                name: sha256((path / name).read_bytes()).hexdigest()
                for name in ("original.pdf", "c3-evidence.json", "pilot.json")
            },
        ),
        ensure_ascii=False,
    ).encode()
    with store.transaction() as db:
        store._publish_snapshot(db, run, path, content)
        db.execute("UPDATE runs SET status='completed',error_code=NULL WHERE run_id=?", (run,))
        db.execute("INSERT OR REPLACE INTO run_progress VALUES (?, 'result',100,1)", (run,))
        store._settle_envelope(db, run)
    app = create_hosted_app(settings)
    client, _, _, _ = login(app, store, tenant=tenant, user=auth.user_sub)
    http = client.get(f"/v1/runs/{run}/result")
    assert http.status_code == 200, http.text
    value = http.json()
    assert canonical_hash(value) == canonical_hash(result)
    assert value["claims"][0]["confirmed_grade"] == "E3"
    assert value["claims"][0]["confirmation_source"] == "auto_direct_certification_c3_v1"
    source_response = client.get(
        f"/v1/runs/{run}/source-pages/36/manifest", params={"claim_id": manifest["claim_id"]}
    )
    assert source_response.status_code == 200, source_response.text
    source_manifest = source_response.json()
    assert source_manifest["document_version_id"] == data["graph"].document_version_id
    assert source_manifest["physical_page"] == 36 and source_manifest["highlights"]
    image_response = client.get(
        f"/v1/runs/{run}/source-pages/36/image",
        params={
            "image_sha256": source_manifest["image_sha256"],
            "document_version_id": source_manifest["document_version_id"],
        },
    )
    assert image_response.status_code == 200, image_response.text[:200]
    assert sha256(image_response.content).hexdigest() == source_manifest["image_sha256"]
    write("source-manifest.json", source_manifest)
    (OUT / "source-p36.png").write_bytes(image_response.content)
    other, _, _, _ = login(app, store)
    denied = other.get(f"/v1/runs/{run}/result")
    assert denied.status_code == 404
    anonymous = TestClient(app, base_url="https://api.example.com").get(f"/v1/runs/{run}/result")
    assert anonymous.status_code == 401
    old_file = path / "result-1.json"
    old_bytes = old_file.read_bytes()
    with store.transaction() as db:
        store._publish_snapshot(db, run, path, content)
    assert old_file.read_bytes() == old_bytes
    write("http-result.json", value)
    write(
        "http-verification.json",
        dict(
            status=200,
            other_tenant_status=404,
            anonymous_status=401,
            same_c3_result_hash=canonical_hash(value),
            old_result_snapshot_preserved=True,
            mode=(
                "actual hosted auth/router/store; local frozen C3 result; "
                "no deployed worker/model E2E"
            ),
        ),
    )
    print(json.dumps(dict(http_status=200, tenant_guard=404, auth_guard=401)))


if __name__ == "__main__":
    main()
