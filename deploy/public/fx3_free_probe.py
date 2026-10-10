"""Network-isolated Linux upload/scope/preparation measurements; no analysis dispatch."""

import json
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from proofops_api.hosted import create_hosted_app
from proofops_api.hosted_store import HostedSettings


def main():
    import resource
    import sys

    from proofops.application.authorization import authorize

    name, source, output = sys.argv[1:]
    output = Path(output)
    settings = HostedSettings(
        root=Path("/data"),
        origin="https://probe.example.com",
        secret="local-free-probe-secret-value-0000",
        event_id="fx3-free",
        accept_uploads=True,
        consent_version="fx3-local",
        backend="r108",
        accept_runs=True,
    )
    app = create_hosted_app(settings)
    store = app.state.composition
    code = store.invite(
        "11111111-1111-4111-8111-111111111111", "fx3-free", "admin", now=time.time()
    )
    sid = store.redeem(code, now=time.time())
    csrf = store.sessions.csrf_token_for(sid)
    stop = threading.Event()
    stage = ["startup"]
    samples = {}

    def sample():
        while not stop.wait(0.01):
            current = int(Path("/sys/fs/cgroup/memory.current").read_text())
            rss = 0
            for path in Path("/proc").glob("[0-9]*/statm"):
                try:
                    rss += int(path.read_text().split()[1]) * resource.getpagesize()
                except (OSError, ValueError, IndexError):
                    pass
            rec = samples.setdefault(stage[0], dict(cgroup_max_bytes=0, rss_sum_max_bytes=0))
            rec["cgroup_max_bytes"] = max(rec["cgroup_max_bytes"], current)
            rec["rss_sum_max_bytes"] = max(rec["rss_sum_max_bytes"], rss)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="critical"))
    serving = threading.Thread(target=server.run, daemon=True)
    serving.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    record = dict(
        name=name,
        input_bytes=Path(source).stat().st_size,
        paid_calls=0,
        memory_limit_bytes=int(Path("/sys/fs/cgroup/memory.max").read_text()),
    )
    passed = False
    try:
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=100) as client:
            headers = {
                "Origin": settings.origin,
                "X-CSRF-Token": csrf,
                "Cookie": "__Host-proofops_session=" + sid,
            }
            stage[0] = "upload"
            started = time.monotonic()
            with Path(source).open("rb") as file:

                def chunks():
                    while chunk := file.read(65536):
                        yield chunk

                response = client.post(
                    "/v1/documents",
                    content=chunks(),
                    headers=headers
                    | {"Content-Type": "application/pdf", "Idempotency-Key": "fx3-free-upload01"},
                )
            record["upload"] = dict(
                status=response.status_code,
                seconds=time.monotonic() - started,
                response=response.json(),
            )
            print(json.dumps(dict(name=name, stage="upload", **record["upload"])), flush=True)
            assert response.status_code == 201
            doc = response.json()
            stage[0] = "scope"
            started = time.monotonic()
            response = client.post(
                f'/v1/documents/{doc["document_id"]}/scope-plan', json={}, headers=headers
            )
            scope = response.json()
            record["scope"] = dict(
                status=response.status_code,
                seconds=time.monotonic() - started,
                plan_status=scope.get("plan", {}).get("status"),
                selected_claim_pages=scope.get("plan", {}).get("selected_claim_pages"),
                selected_evidence_pages=scope.get("plan", {}).get("selected_evidence_pages"),
            )
            print(json.dumps(dict(name=name, stage="scope", **record["scope"])), flush=True)
            assert response.status_code == 200 and scope["selection"]
            auth = authorize(
                session_id=sid,
                now=time.time(),
                session_port=store.sessions,
                membership_port=store.memberships,
                required_capability="editor",
            )
            run = store.create_run(
                auth,
                doc["document_id"],
                None,
                "fx3-free-run0001",
                now=time.time(),
                auto_scope=True,
                scope_selection_sha256=scope["selection"]["selection_sha256"],
            )
            stage[0] = "prepare"
            started = time.monotonic()
            job = store.claim(now=time.time())
            prepared = store.prepare(job, now=time.time())
            record["prepare"] = dict(
                seconds=time.monotonic() - started,
                bytes=prepared.stat().st_size,
                selected_pages=len(json.loads(job["pages"])),
            )
            print(json.dumps(dict(name=name, stage="prepare", **record["prepare"])), flush=True)
            assert prepared.stat().st_size < Path(source).stat().st_size
            store.finish(job, "partial_blocked", now=time.time())
            with store.transaction() as db:
                assert db.execute("SELECT count(*) FROM deletion.costs").fetchone()[0] == 0
            assert store.budget_totals()["event_reserved_usd"] == "0.000000"
            assert store.get_run(auth.tenant_id, run["run_id"])["status"] == "partial_blocked"
            passed = True
    finally:
        stop.set()
        sampler.join()
        server.should_exit = True
        serving.join(5)
        record["stages_memory"] = samples
        record["cgroup_peak_bytes"] = int(Path("/sys/fs/cgroup/memory.peak").read_text())
        record["oom_events"] = Path("/sys/fs/cgroup/memory.events").read_text()
        record["status"] = "passed" if passed else "failed"
        output.write_text(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
