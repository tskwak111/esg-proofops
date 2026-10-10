"""One explicitly authorized two-page local canary; reserves existing R108 USD ledger first."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
from proofops_api.hosted_store import HostedSettings, HostedStore


@contextmanager
def locked_spend(path):
    # Same lock used by the independent R108 decision/OCR reservation adapters.
    with path.with_suffix(".decisions.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield json.loads(path.read_text())


def save(path, value):
    temporary = path.with_suffix(".p2.tmp")
    with temporary.open("w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pages", default="22,41")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--research-root", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise ValueError("MACOS_CANARY_REQUIRED")
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (output / "live-result.json").exists() or (output / "data").exists():
        raise ValueError("ONE_CANARY_ONLY_USE_EXISTING_EVIDENCE")
    selected = [int(x) for x in args.pages.split(",")]
    if len(selected) != 2 or len(set(selected)) != 2:
        raise ValueError("EXACTLY_TWO_PAGES_REQUIRED")
    ledger = (
        args.research_root / "outputs/agent-results/R108-redesign/lab/sprint3/E2E/r108-spend.json"
    )
    operator = output / "operator.json"
    save(
        operator,
        dict(
            enabled=True,
            openrouter_key_file=str(args.research_root / ".env.openrouter.local"),
            upstage_key_file=str(args.research_root / ".env.upstage.local"),
            report_year=2025,
            period_start="2024-01-01",
            period_end="2024-12-31",
        ),
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.endswith("_API_KEY") and not k.startswith(("LOCAL_", "HOSTED_", "APP_"))
    }
    env.update(
        APP_ENV="hosted",
        MODEL_ADAPTER="disabled",
        HOSTED_DATA_DIR=str(output / "data"),
        APP_ORIGIN="https://app.example.com",
        HOSTED_SESSION_SECRET=secrets.token_urlsafe(48),
        HOSTED_EVENT_ID="p2-local-canary",
        HOSTED_ACCEPT_UPLOADS="true",
        HOSTED_CONSENT_VERSION="approved-original-7d-p2-canary",
        ANALYSIS_BACKEND="r108",
        R108_ACCEPT_NEW_RUNS="true",
        LIVE_DISABLED="false",
        HOSTED_RUN_USD=".30",
        HOSTED_LIVE_CONFIG=str(operator),
    )
    settings = HostedSettings.from_env(env)
    store = HostedStore(settings)
    tenant = str(uuid4())
    code = store.invite(tenant, "p2-authorized-local-canary", "admin", now=time.time())
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log = (output / "api-private.log").open("w")
    os.fchmod(log.fileno(), 0o600)
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "proofops_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
            "--no-proxy-headers",
        ],
        env=env,
        stdout=log,
        stderr=log,
    )
    operation = str(uuid4())
    reservation = False
    actual = None
    result = None
    run = None
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120) as client:
            for _ in range(100):
                try:
                    if client.get("/v1/health/live").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            response = client.post(
                "/v1/auth/invitation", json=dict(code=code), headers={"Origin": settings.origin}
            )
            response.raise_for_status()
            cookie = response.headers["set-cookie"].split(";", 1)[0]
            client.headers.update(
                {
                    "Cookie": cookie,
                    "Origin": settings.origin,
                    "X-CSRF-Token": response.json()["csrf_token"],
                }
            )
            response = client.post(
                "/v1/documents",
                content=args.pdf.read_bytes(),
                headers={
                    "Content-Type": "application/pdf",
                    "Idempotency-Key": "p2-live-upload-001",
                },
            )
            response.raise_for_status()
            document = response.json()
            response = client.post(
                "/v1/runs",
                json=dict(document_id=document["document_id"], selected_pages=selected),
                headers={"Idempotency-Key": "p2-live-run-00001"},
            )
            response.raise_for_status()
            run = response.json()
            with locked_spend(ledger) as spend:
                committed = Decimal(spend["cumulative_usd"])
                if committed + Decimal(".30") > Decimal(spend["limit_usd"]):
                    raise ValueError("R108_BUDGET_EXCEEDED")
                spend["cumulative_usd"] = str(committed + Decimal(".30"))
                spend["executions"].append(
                    dict(
                        operation_id=operation,
                        task="deploy-P2",
                        run_id=run["run_id"],
                        limit_usd=".30",
                        delta_usd=".30",
                        status="reserved",
                        ledger=str(store.ledger),
                    )
                )
                save(ledger, spend)
                reservation = True
            worker = subprocess.run(
                [sys.executable, "scripts/hosted_control.py", "worker", "--once"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=880,
            )
            response = client.get(run["status_url"])
            response.raise_for_status()
            polled = response.json()
            result_response = client.get(
                polled.get("result_url") or f'/v1/runs/{run["run_id"]}/result'
            )
            with sqlite3.connect(store.ledger) as db:
                calls = [
                    dict(zip(("provider", "bound", "actual", "status"), r))
                    for r in db.execute(
                        "SELECT provider,bound,actual,status FROM costs WHERE run_id=?",
                        (run["run_id"],),
                    )
                ]
                spend_row = db.execute(
                    "SELECT amount,status FROM spend WHERE run_id=?", (run["run_id"],)
                ).fetchone()
            accounted = Decimal(spend_row[0]) / Decimal(1000000)
            actual = sum((Decimal(c["actual"] or 0) / Decimal(1000000) for c in calls), Decimal(0))
            result = dict(
                status="passed" if result_response.status_code == 200 else "blocked",
                upload_http=201,
                run_http=202,
                result_http=result_response.status_code,
                run=polled,
                result=result_response.json(),
                provider_calls=len(calls),
                calls=calls,
                actual_settled_usd=str(actual),
                accounted_usd=str(accounted),
                limit_usd=".30",
                worker_exit=worker.returncode,
                research_operation_id=operation,
            )
            save(output / "live-result.json", result)
            if accounted > Decimal(".30"):
                raise ValueError("CANARY_CAP_EXCEEDED")
            with locked_spend(ledger) as spend:
                execution = next(
                    e for e in spend["executions"] if e.get("operation_id") == operation
                )
                spend["cumulative_usd"] = str(
                    Decimal(spend["cumulative_usd"]) - Decimal(".30") + accounted
                )
                execution.update(
                    status=spend_row[1],
                    delta_usd=str(accounted),
                    actual_settled_usd=str(actual),
                    provider_calls=len(calls),
                    result_http=result_response.status_code,
                )
                save(ledger, spend)
                reservation = False
            cleanup = client.post(
                f'/v1/documents/{document["document_id"]}/deletion-requests',
                json=dict(
                    reason="Authorized canary finished; remove original and analysis payload"
                ),
                headers={"Idempotency-Key": "p2-live-delete-001"},
            )
            cleanup.raise_for_status()
            result["cleanup"] = cleanup.json()
            save(output / "live-result.json", result)
            if result["cleanup"]["status"] != "completed":
                raise ValueError("CANARY_PURGE_INCOMPLETE")
            print(
                json.dumps(
                    {
                        k: result[k]
                        for k in (
                            "status",
                            "provider_calls",
                            "actual_settled_usd",
                            "accounted_usd",
                            "result_http",
                        )
                    }
                )
            )
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        log.close()
        # Unknown/exception leaves the USD.30 research reservation intact.
        if reservation:
            save(
                output / "canary-blocked.json",
                dict(operation_id=operation, status="reservation_retained"),
            )


if __name__ == "__main__":
    main()
