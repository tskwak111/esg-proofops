"""Offline release smoke phases, invoked only by hosted_pipeline_smoke.py.

The API and worker are separate processes/containers sharing their normal data
volume. Only provider transport I/O uses synthetic replies. No hosted runtime
switch can activate this fixture; production entrypoints remain unchanged.
"""

import argparse
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

from proofops.adapters.local.claim_source_policies import page_ocr_profile
from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.application.analysis_profile import V2_POLICY
from proofops.application.ports.jobs import JobMessage
from proofops.domain.provenance import canonical_hash
from proofops_api.hosted_store import HostedSettings, HostedStore

from deploy.public.offline_fixture import async_parse_replies, fake_llm, fake_page_ocr, source_pdf
from evaluation.hosted_r108 import drive

ROOT = Path(os.environ.get("HOSTED_DATA_DIR", "/data"))
RECORD = ROOT / "offline-smoke.json"


def request(path, *, body=None, cookie=None, csrf=None, key=None, pdf=False):
    headers = {"Origin": os.environ["APP_ORIGIN"]}
    if cookie:
        headers["Cookie"] = cookie
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if key:
        headers["Idempotency-Key"] = key
    if body is not None:
        headers["Content-Type"] = "application/pdf" if pdf else "application/json"
        if not pdf:
            body = json.dumps(body).encode()
    req = urllib.request.Request("http://127.0.0.1:8000" + path, body, headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response), response.headers


def intake():
    store = HostedStore(HostedSettings.from_env(os.environ))
    tenant = str(uuid4())
    invite = store.invite(tenant, str(uuid4()), "editor", now=time.time())
    session, headers = request("/v1/auth/invitation", body={"code": invite})
    auth = dict(cookie=headers["Set-Cookie"].split(";", 1)[0], csrf=session["csrf_token"])
    document, _ = request(
        "/v1/documents", body=source_pdf(), pdf=True, key="offline-smoke-upload01", **auth
    )
    runtime, _ = request("/v1/runtime")
    run, _ = request(
        "/v1/runs",
        body=dict(document_id=document["document_id"], selected_pages=[1, 2]),
        key="offline-smoke-run0001",
        **auth,
    )
    assert run["pipeline_profile"] == runtime["pipeline_profile"] == "finals-unattended-v2"
    RECORD.write_text(json.dumps(dict(auth=auth, tenant=tenant, document=document, run=run)))
    RECORD.chmod(0o600)
    return dict(phase="intake", status="passed", profile=run["pipeline_profile"])


def worker():
    store = HostedStore(HostedSettings.from_env(os.environ))
    workspace = ROOT / "offline-worker"
    workspace.mkdir()

    def analyze(store, job, prepared):
        (workspace / "selected.pdf").write_bytes(prepared.read_bytes())
        with async_parse_replies() as submit:
            state, outcome = drive(
                store,
                job,
                workspace,
                dict(report_year=2024, period_start="2024-01-01", period_end="2024-12-31"),
                llm_post=fake_llm,
                parse_post=submit,
                ocr_post=fake_page_ocr,
            )
        assert outcome["stages"] == [
            dict(stage="parse", outcome="committed"),
            dict(stage="extract", outcome="committed"),
            dict(stage="tag", outcome="completed"),
        ], outcome
        store.publish_analysis(job, state, outcome["status"], outcome["reason"])

    result = store.tick(now=time.time(), analysis=analyze)
    assert result and result["status"] == "completed", result
    return dict(phase="worker", status="passed", real_provider_calls=0)


def verify():
    record = json.loads(RECORD.read_text())
    run, _ = request(record["run"]["status_url"], cookie=record["auth"]["cookie"])
    assert run["status"] == "completed", run
    result, _ = request(run["result_url"], cookie=record["auth"]["cookie"])
    assert len(result["claims"]) == 2 and not result["hold_reasons"], result
    assert all(c["confirmed_grade"] is None for c in result["claims"])
    assert all(e["state"] == "unknown" for c in result["claims"] for e in c["elements"])
    store = HostedStore(HostedSettings.from_env(os.environ))
    directory = store.document_dir(record["tenant"], record["document"]["document_id"])
    assert (
        hashlib.sha256((directory / "original.pdf").read_bytes()).hexdigest()
        == (record["document"]["sha256"])
    )
    state = directory / "analysis" / run["run_id"]
    manifest = json.loads((state / "pilot.json").read_text())
    jobs = LocalSQLiteRunStore(state / "state.sqlite3").jobs
    local_run = jobs.get_run(record["tenant"], manifest["run_id"])
    message = JobMessage(**local_run["parse_job"])
    policy = jobs.parser_native_policy(message)
    assert policy == page_ocr_profile(manifest["claim_source_profile"]).native_policy()
    assert V2_POLICY["integration_profile"] == "finals-20261014-v16"
    assert manifest["claim_source_profile"] == "upstage-ocr-page-v16"
    assert manifest["analysis_policy_sha256"] == canonical_hash(V2_POLICY)
    assert manifest["extraction_qc_native_figures"] is True
    saved_settings = json.loads((state / "settings.json").read_text())
    assert saved_settings["extraction_qc_native_figures"] is True
    from proofops.application.tagging.q1_contract import QA2_POLICY

    assert V2_POLICY["structural_quality_policy"] == QA2_POLICY

    snapshot_sha = hashlib.sha256((state / "result-1.json").read_bytes()).hexdigest()
    if record.get("snapshot_sha256"):
        assert record["snapshot_sha256"] == snapshot_sha
    else:
        record["snapshot_sha256"] = snapshot_sha
        RECORD.write_text(json.dumps(record))
    with store.transaction() as db:
        assert (
            db.execute("SELECT count(*) FROM deletion.costs WHERE status!='settled'").fetchone()[0]
            == 0
        )
    return dict(
        phase="verify",
        status="passed",
        claims=2,
        confirmed_grades=0,
        policy_sha256=manifest["analysis_policy_sha256"],
        native_mode=policy["mode"],
        integration_profile=V2_POLICY["integration_profile"],
        claim_source_profile=manifest["claim_source_profile"],
        stages=result["pipeline"]["stages"],
        stage_seconds=result["pipeline"]["stage_seconds"],
        source_preserved=True,
        snapshot_sha256=snapshot_sha,
        real_provider_calls=0,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("intake", "worker", "verify"))
    args = parser.parse_args()
    print(json.dumps({"intake": intake, "worker": worker, "verify": verify}[args.phase]()))


if __name__ == "__main__":
    main()
