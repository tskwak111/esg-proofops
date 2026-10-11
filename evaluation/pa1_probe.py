"""Local authorized PA1 canary using the hosted store and subprocess composition."""

import argparse
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path


def main():
    from uuid import uuid4

    from proofops.application.authorization import authorize
    from proofops_api import hosted_analysis
    from proofops_api.hosted_store import HostedSettings, HostedStore

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--cap", default="1")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    config = output / "operator.json"
    config.write_text(
        json.dumps(
            dict(
                enabled=True,
                llm_provider="openai",
                analysis_profile="finals-unattended-v2",
                rendered_reader_profile="upstage-ocr-page-v6",
                llm_max_workers=8,
                openai_key_file=str(Path.home() / "proofops-keys/openai.env"),
                upstage_key_file=str(Path.home() / "proofops-keys/upstage.env"),
                report_year=2024,
                period_start="2024-01-01",
                period_end="2024-12-31",
            )
        )
    )
    config.chmod(0o600)
    env = dict(
        APP_ENV="hosted",
        MODEL_ADAPTER="disabled",
        HOSTED_DATA_DIR=str(output / "data"),
        APP_ORIGIN="https://pa1.example.com",
        HOSTED_SESSION_SECRET=secrets.token_urlsafe(48),
        HOSTED_EVENT_ID="PA1-USD2",
        HOSTED_ACCEPT_UPLOADS="true",
        HOSTED_CONSENT_VERSION="PA1-authorized-public-report",
        ANALYSIS_BACKEND="r108",
        R108_ACCEPT_NEW_RUNS="true",
        LIVE_DISABLED="false",
        HOSTED_LIVE_CONFIG=str(config),
        HOSTED_RUN_USD=args.cap,
        HOSTED_DAY_USD=args.cap,
        HOSTED_EVENT_USD=args.cap,
        PA1_PROFILE_DIR=str(output),
    )
    os.environ.update(env)
    store = HostedStore(HostedSettings.from_env(os.environ))
    invitation = store.invite(str(uuid4()), "PA1-local-evaluator", "admin", now=time.time())
    session = store.redeem(invitation, now=time.time())
    auth = authorize(
        session_id=session,
        now=time.time(),
        session_port=store.sessions,
        membership_port=store.memberships,
        required_capability="editor",
    )
    document = store.upload_file(auth, args.pdf.resolve(), "pa1-local-upload", now=time.time())
    scope = store.generate_scope(auth, document["document_id"])
    (output / "scope.json").write_text(json.dumps(scope))
    run = store.create_run(
        auth,
        document["document_id"],
        None,
        "pa1-local-run-001",
        now=time.time(),
        auto_scope=True,
        pipeline_profile="finals-unattended-v2",
    )
    (output / "accepted.json").write_text(json.dumps(run))
    print(json.dumps(dict(run_id=run["run_id"], pages=run["selected_pages"])), flush=True)
    original = hosted_analysis.run_analysis_process

    def profiled(command, store, job, lock):
        command[command.index("evaluation.hosted_r108")] = "evaluation.pa1_profile"
        return original(command, store, job, lock)

    hosted_analysis.run_analysis_process = profiled
    hosted_analysis.ANALYSIS_TIMEOUT_SECONDS = 5400
    start = time.monotonic()
    result = store.tick(now=time.time())
    (output / "status.json").write_text(json.dumps(result, ensure_ascii=False))
    with sqlite3.connect(store.ledger) as db:
        costs = [
            dict(provider=p, calls=n, bound=b, actual=a, status=s)
            for p, n, b, a, s in db.execute(
                "SELECT provider,count(*),sum(bound),sum(actual),status "
                "FROM costs GROUP BY provider,status"
            )
        ]
    (output / "measurement.json").write_text(
        json.dumps(dict(seconds=time.monotonic() - start, costs=costs))
    )
    print(
        json.dumps(
            dict(
                status=result["status"],
                error_code=result.get("error_code"),
                seconds=time.monotonic() - start,
                costs=costs,
            )
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
