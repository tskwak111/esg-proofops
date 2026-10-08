"""Real Uvicorn HTTP smoke inside network-none container; no provider transport."""

from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from proofops_api.hosted_store import HostedSettings, HostedStore
from pypdf import PdfWriter

BASE = "http://127.0.0.1:8000"
ORIGIN = os.environ["APP_ORIGIN"]


def main() -> None:
    assert all(
        not os.environ.get(name)
        for name in ("OPENROUTER_API_KEY", "UPSTAGE_API_KEY", "OPENAI_API_KEY", "AWS_ACCESS_KEY_ID")
    )
    store = HostedStore(HostedSettings.from_env(os.environ))
    sampled_peak = 0
    stop = threading.Event()

    def sample():
        nonlocal sampled_peak
        while not stop.wait(0.01):
            total = 0
            for status in Path("/proc").glob("[0-9]*/status"):
                try:
                    text = status.read_text()
                    if "Name:\tpython" not in text:
                        continue
                    for line in text.splitlines():
                        if line.startswith("VmRSS:"):
                            total += int(line.split()[1]) * 1024
                except (OSError, ValueError):
                    pass
            sampled_peak = max(sampled_peak, total)

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()

    def request(path, *, method="GET", body=None, headers=None, cookie=None):
        h = {"Origin": ORIGIN} | (headers or {})
        if cookie:
            h["Cookie"] = cookie
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(BASE + path, data=body, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read()
                return response.status, json.loads(content) if content else {}, response.headers
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read()), exc.headers

    assert request("/v1/health/live")[1]["app_env"] == "hosted"
    assert request("/v1/health/ready")[1]["control_plane"]
    assert request("/v1/session")[0] == 401
    tenant = str(uuid4())
    code = store.invite(tenant, "smoke-admin", "admin", now=time.time())
    status, session, headers = request("/v1/auth/invitation", method="POST", body={"code": code})
    assert status == 200
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    assert "Secure" in headers["Set-Cookie"] and "HttpOnly" in headers["Set-Cookie"]
    assert request("/v1/auth/invitation", method="POST", body={"code": code})[0] == 401
    assert request("/v1/session", cookie=cookie)[1]["tenant_id"] == tenant
    csrf = {"X-CSRF-Token": session["csrf_token"]}
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    upload_headers = {"Content-Type": "application/pdf", "Idempotency-Key": "docker-upload-001"}
    assert (
        request(
            "/v1/documents",
            method="POST",
            body=buffer.getvalue(),
            headers=upload_headers,
            cookie=cookie,
        )[0]
        == 403
    )
    status, doc, _ = request(
        "/v1/documents",
        method="POST",
        body=buffer.getvalue(),
        headers=upload_headers | csrf,
        cookie=cookie,
    )
    assert status == 201 and doc["page_count"] == 3
    status, run, _ = request(
        "/v1/runs",
        method="POST",
        body={"document_id": doc["document_id"]},
        headers=csrf | {"Idempotency-Key": "docker-run-000001"},
        cookie=cookie,
    )
    assert status == 202, (status, run)
    assert run["selected_pages"] == [1, 2]
    subprocess.run([sys.executable, "scripts/hosted_control.py", "worker", "--once"], check=True)
    polled = request(run["status_url"], cookie=cookie)[1]
    assert polled["status"] == "partial_blocked" and polled["prepared_sha256"]
    code2 = store.invite(str(uuid4()), "smoke-other", "admin", now=time.time())
    _, _, h2 = request("/v1/auth/invitation", method="POST", body={"code": code2})
    other_cookie = h2["Set-Cookie"].split(";", 1)[0]
    assert request(f'/v1/documents/{doc["document_id"]}', cookie=other_cookie)[0] == 404
    status, deletion, _ = request(
        f'/v1/documents/{doc["document_id"]}/deletion-requests',
        method="POST",
        body={"reason": "docker smoke cleanup"},
        headers=csrf | {"Idempotency-Key": "docker-delete-001"},
        cookie=cookie,
    )
    assert status == 202 and deletion["status"] == "completed"
    assert not store.document_dir(tenant, doc["document_id"]).exists()
    assert request(run["status_url"], cookie=cookie)[0] == 404
    assert request("/v1/auth/logout", method="POST", headers=csrf, cookie=cookie)[0] == 204
    assert request("/v1/session", cookie=cookie)[0] == 401
    persisted = request("/v1/session", cookie=other_cookie)[1]
    store._write(
        Path("/data/smoke-session.json"),
        json.dumps(
            {
                "cookie": other_cookie,
                "csrf": persisted["csrf_token"],
                "tenant": persisted["tenant_id"],
            }
        ).encode(),
    )
    stop.set()
    monitor.join()
    api_hwm = next(
        int(line.split()[1]) * 1024
        for line in Path("/proc/1/status").read_text().splitlines()
        if line.startswith("VmHWM:")
    )
    cgroup_peak = Path("/sys/fs/cgroup/memory.peak")
    print(
        json.dumps(
            {
                "status": "passed",
                "http_upload": "201",
                "run_acceptance": "202",
                "poll": "partial_blocked",
                "purge": "completed",
                "tenant_isolation": "404",
                "auth_restart": "durable_sqlite",
                "provider_calls": 0,
                "cloud_calls": 0,
                "api_peak_rss_bytes": api_hwm,
                "sampled_all_python_peak_rss_bytes": sampled_peak,
                "worker_maxrss_bytes": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
                * 1024,
                "cgroup_peak_bytes": int(cgroup_peak.read_text()) if cgroup_peak.exists() else None,
            }
        )
    )


if __name__ == "__main__":
    main()
