"""Two actual hosted slots/locks/leases driving isolated offline LG replays."""

import argparse
import json
import os
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4


def main():
    from proofops.application.authorization import authorize
    from proofops_api import hosted_analysis
    from proofops_api.hosted_store import HostedSettings, HostedStore

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert len(args.source) == 2
    root = args.output.resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.environ["HOSTED_MAX_ACTIVE_RUNS"] = "2"
    settings = HostedSettings.from_env(
        dict(
            APP_ENV="hosted",
            HOSTED_DATA_DIR=str(root / "control"),
            APP_ORIGIN="https://pa3.example.com",
            HOSTED_SESSION_SECRET=secrets.token_urlsafe(48),
            HOSTED_EVENT_ID="PA3-offline-only",
            HOSTED_ACCEPT_UPLOADS="true",
            HOSTED_CONSENT_VERSION="PA3-authorized-stored-public-report",
            ANALYSIS_BACKEND="r108",
            R108_ACCEPT_NEW_RUNS="true",
            LIVE_DISABLED="true",
            HOSTED_MAX_ACTIVE_RUNS="2",
        )
    )
    store = HostedStore(settings)
    by_document = {}
    for i, source in enumerate(args.source):
        source = source.resolve()
        manifest = json.loads((source / "pilot.json").read_text())
        invitation = store.invite(manifest["tenant_id"], str(uuid4()), "admin", now=time.time())
        sid = store.redeem(invitation, now=time.time())
        auth = authorize(
            session_id=sid,
            now=time.time(),
            session_port=store.sessions,
            membership_port=store.memberships,
            required_capability="editor",
        )
        original = (
            source
            / "objects/original"
            / manifest["tenant_id"]
            / f'{manifest["document_version_id"]}.pdf'
        )
        doc = store.upload_file(auth, original, f"pa3-upload-{i:06}", now=time.time())
        run = store.create_run(
            auth,
            doc["document_id"],
            list(range(1, 14)),
            f"pa3-replay-{i:06}",
            now=time.time(),
            auto_scope=True,
        )
        by_document[doc["document_id"]] = (source, root / f"run-{i}", run["run_id"])
    barrier = threading.Barrier(2)
    samples = []
    stopped = threading.Event()
    pids = {}
    lock = threading.Lock()
    original_popen = hosted_analysis.subprocess.Popen

    def popen(*a, **k):
        analysis = a and "evaluation.pa3_replay" in a[0]
        stream = None
        if analysis:
            target = Path(a[0][a[0].index("--output") + 1])
            stream = target.with_suffix(".log").open("wb")
            k["stderr"] = stream
        try:
            child = original_popen(*a, **k)
            if analysis:
                with lock:
                    pids[child.pid] = time.monotonic()
        finally:
            if stream is not None:
                stream.close()
        return child

    hosted_analysis.subprocess.Popen = popen

    def sample():
        while not stopped.wait(1):
            with lock:
                active_pids = list(pids)
            memory = {str(pid): hosted_analysis.process_tree_bytes(pid) for pid in active_pids}
            with store.transaction() as db:
                active = db.execute("SELECT count(*) FROM runs WHERE status='running'").fetchone()[
                    0
                ]
            samples.append(
                dict(
                    at=time.monotonic(),
                    active_runs=active,
                    rss=memory,
                    aggregate_rss=sum(memory.values()),
                )
            )

    monitor = threading.Thread(target=sample)
    monitor.start()

    def replay(current, job, prepared):
        source, output, _ = by_document[job["document_id"]]
        directory = current.document_dir(job["tenant_id"], job["document_id"])
        with (directory / "analysis.lock").open("a+b") as document_lock:
            hosted_analysis.acquire_analysis_lock(document_lock)
            barrier.wait(timeout=30)
            hosted_analysis.run_analysis_process(
                [
                    sys.executable,
                    "-m",
                    "evaluation.pa3_replay",
                    "--source",
                    str(source),
                    "--output",
                    str(output),
                    "--stage",
                    "pipeline",
                    "--cache-profile",
                    "exact-verified-read-v3",
                ],
                current,
                job,
                document_lock,
            )
        result = json.loads((output / "measurement.json").read_text())
        assert result["original_result_identical"]
        # This is a local retained-fixture replay, not a new publishable analysis.
        current.finish(job, "partial_blocked", now=time.time())

    start = time.monotonic()
    try:
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(store.tick, now=time.time(), analysis=replay) for _ in range(2)]
            statuses = [f.result() for f in futures]
        measurements = [
            json.loads((root / f"run-{i}/measurement.json").read_text()) for i in range(2)
        ]
        assert all(m["original_result_identical"] for m in measurements)
        result = dict(
            seconds=time.monotonic() - start,
            max_active_runs=2,
            peak_active_runs=max(s["active_runs"] for s in samples),
            aggregate_peak_rss_bytes=max(s["aggregate_rss"] for s in samples),
            per_run_peak_rss_bytes={
                pid: max(s["rss"].get(pid, 0) for s in samples)
                for pid in {p for s in samples for p in s["rss"]}
            },
            budget_totals=store.budget_totals(),
            provider_calls=0,
            paid_usd="0",
            statuses=[s["status"] for s in statuses],
            runs=measurements,
            rss_samples=samples,
            container_memory_max=Path("/sys/fs/cgroup/memory.max").read_text().strip(),
            vm_memory_total=next(
                line.strip()
                for line in Path("/proc/meminfo").read_text().splitlines()
                if line.startswith("MemTotal:")
            ),
        )
        (root / "measurement.json").write_text(json.dumps(result, indent=2))
        print(
            json.dumps({k: v for k, v in result.items() if k not in {"runs", "rss_samples"}}),
            flush=True,
        )
    finally:
        stopped.set()
        monitor.join()
        hosted_analysis.subprocess.Popen = original_popen


if __name__ == "__main__":
    main()
