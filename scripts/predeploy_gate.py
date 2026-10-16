"""Fail closed on regressions through the exact server image's API/worker/FD path.

python scripts/predeploy_gate.py --manifest CASES.json --output /tmp/predeploy \
  --image proofops-r108-public:ec1-arm64-ca141f0

Compare an already captured result without Docker or provider calls:
python scripts/predeploy_gate.py --manifest CASES.json --output /tmp/e12-check \
  --captured-result tests/fixtures/predeploy/E12-lg.result.json \
  --case lg13 --captured-seconds 905.467630147934

CASES.json has three cases (kind: lg13, kakao, table), each with original pdf,
source_sha256, pages, claim_pages, reporting_scope, recorded_states and baseline
{claims, verified, tentative, max_seconds, evidence}. Paths are relative to the
manifest. No keys or production data volume are mounted; only compiled provider
replies and PDFs enter isolated --network none containers. Exit 1 means promotion
failed, including fixture gaps; it does not mean the underlying regressions were
fixed. Replay timing excludes provider latency and is not a live speed claim.
"""

import argparse
import hashlib
import json
import math
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from predeploy_replies import compile_replies

ROOT = Path(__file__).resolve().parents[1]
CAPS = dict(
    api_cpus="0.5",
    api_memory="512m",
    worker_cpus="6.0",
    worker_memory="12g",
    pids=128,
    tmpfs_bytes=536870912,
    active_runs=1,
    http_workers=16,
    rps=8,
)


def metrics(result):
    claims = (result or {}).get("claims", [])
    return dict(
        claims=len(claims),
        verified=sum(c.get("source_quality") == "verified" for c in claims),
        tentative=sum(
            (c.get("provisional_grade") or {}).get("evidence_grade") is not None for c in claims
        ),
        confirmed=sum(c.get("confirmed_grade") is not None for c in claims),
    )


def compare(observation, baseline):
    """A completed status alone can never pass this gate."""
    failures = []
    measured = metrics(observation.get("result"))
    for name in ("claims", "verified", "tentative"):
        if measured[name] < baseline[name]:
            failures.append(f"{name}:{measured[name]}<{baseline[name]}")
    if measured["claims"] == 0:
        failures.append("empty_result")
    if measured["verified"] == 0:
        failures.append("no_positive_source_proof")
    if observation.get("status") != "completed":
        failures.append("run_not_completed:" + str(observation.get("error_code")))
    result = observation.get("result") or {}
    pipeline = result.get("pipeline", {})
    if pipeline.get("status") != "completed" or result.get("hold_reasons"):
        failures.append("pipeline_blocked")
    extraction = pipeline.get("extraction_outcome", {})
    if extraction and (
        extraction.get("status") not in {"completed", "claims"}
        or (extraction.get("status") == "claims" and extraction.get("code") != "OK")
        or extraction.get("failed_sources")
        or extraction.get("page_failures")
    ):
        failures.append("extraction_partial")
    seconds = observation.get("seconds")
    if (
        type(seconds) not in (int, float)
        or not math.isfinite(seconds)
        or seconds < 0
        or seconds > baseline["max_seconds"]
    ):
        failures.append(f'time:{seconds}>{baseline["max_seconds"]}')
    if observation.get("unsettled_costs"):
        failures.append("unsettled_reservations")
    return dict(
        status="failed" if failures else "passed",
        metrics=measured,
        baseline=baseline,
        seconds=seconds,
        failures=failures,
    )


def validate_manifest(manifest):
    cases = manifest["cases"]
    if len(cases) != 3 or {c["kind"] for c in cases} != {"lg13", "kakao", "table"}:
        raise ValueError("Exactly LG13, Kakao and one table report are required")
    for case in cases:
        if not case.get("recorded_states") or not case["baseline"].get("evidence"):
            raise ValueError("Recorded responses and baseline provenance are required")
        if any(
            type(case["baseline"].get(k)) is not int or case["baseline"][k] <= 0
            for k in ("claims", "verified", "tentative")
        ):
            raise ValueError("Positive baseline claims/verified/tentative are required")
        seconds = case["baseline"].get("max_seconds")
        if type(seconds) not in (int, float) or not 0 < seconds < 14400:
            raise ValueError("A bounded comparable time baseline is required")
        if (
            not 1 <= len(case["claim_pages"]) <= 10
            or not 1 <= len(case["pages"]) <= 30
            or not set(case["claim_pages"]) <= set(case["pages"])
        ):
            raise ValueError("Invalid selected scope")
        if case["kind"] == "lg13" and len(case["pages"]) != 13:
            raise ValueError("LG13 must retain all thirteen selected pages")


def compare_captured(path, case, seconds):
    """Compare a retained API result; this is evidence, not an image E2E run."""
    raw = path.read_bytes()
    observation = dict(status="completed", result=json.loads(raw), seconds=seconds)
    return dict(
        schema="predeploy-captured-comparison-v1",
        mode="captured-result-only",
        case=case["kind"],
        result_path=str(path.resolve()),
        result_sha256=hashlib.sha256(raw).hexdigest(),
        **compare(observation, case["baseline"]),
    )


def docker(*args, timeout=120):
    return subprocess.check_output(
        ["docker", *args], text=True, stderr=subprocess.STDOUT, timeout=timeout
    ).strip()


def phase(container, name):
    output = docker("exec", container, "python", "/harness/predeploy_runtime.py", name, timeout=180)
    return json.loads(output.splitlines()[-1])


def prepare(case, base, directory):
    directory.mkdir()
    source = (base / case["pdf"]).resolve()
    if hashlib.sha256(source.read_bytes()).hexdigest() != case["source_sha256"]:
        raise ValueError("Original PDF SHA mismatch")
    shutil.copyfile(source, directory / "original.pdf")
    replies = compile_replies([(base / p).resolve() for p in case["recorded_states"]])
    (directory / "replies.json").write_text(json.dumps(replies, ensure_ascii=False))
    (directory / "case.json").write_text(json.dumps(case))
    # Dummy key files satisfy the real operator validation and remain local.
    (directory / "dummy-openai.env").write_text("OPENAI_API_KEY=offline-test\n")
    (directory / "dummy-upstage.env").write_text("UPSTAGE_API_KEY=offline-test\n")
    (directory / "live.json").write_text(
        json.dumps(
            dict(
                enabled=True,
                openai_key_file="/fixtures/dummy-openai.env",
                upstage_key_file="/fixtures/dummy-upstage.env",
                llm_provider="openai",
                analysis_profile="finals-unattended-v2",
                llm_max_workers=16,
                llm_requests_per_second=8,
                extract_batch_calls=100,
                **case["reporting_scope"],
            )
        )
    )
    return dict(
        llm_pairs=sum(len(v) for v in replies["llm"].values()),
        ocr_pages=len(replies["ocr"]),
        parse_requests=len(replies["parse"]),
        replies_sha256=hashlib.sha256((directory / "replies.json").read_bytes()).hexdigest(),
    )


def health(container):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            docker(
                "exec",
                container,
                "python",
                "-S",
                "-c",
                "import urllib.request; "
                "urllib.request.urlopen('http://127.0.0.1:8000/v1/health/live',timeout=2)",
                timeout=5,
            )
            return
        except subprocess.SubprocessError:
            time.sleep(0.5)
    raise RuntimeError("API health unavailable")


def run_case(
    case,
    base,
    output,
    image_id,
    harness,
    timeout,
    capture_misses=False,
    *,
    prepare_case=prepare,
    compare_result=compare,
    response_event="recorded_reply",
    verification_in_observer=False,
    keep_session_alive=False,
):
    directory = output / case["kind"]
    directory.mkdir()
    record = dict(status="failed", case=case["kind"], failures=[])
    name = "proofops-p5-" + secrets.token_hex(6)
    volume = name + "-data"
    try:
        fixtures = directory / "fixtures"
        record["fixtures"] = prepare_case(case, base, fixtures)
        docker("volume", "create", volume)
        with tempfile.NamedTemporaryFile("w", suffix=".env") as env:
            os.chmod(env.name, 0o600)
            env.write(
                "APP_ORIGIN=https://app.example.com\nHOSTED_SESSION_SECRET="
                + secrets.token_urlsafe(48)
                + "\nHOSTED_ACCEPT_UPLOADS=true\nR108_ACCEPT_NEW_RUNS=true\n"
                "HOSTED_CONSENT_VERSION=predeploy-offline-v1\nANALYSIS_BACKEND=r108\n"
                "LIVE_DISABLED=false\nHOSTED_LIVE_CONFIG=/fixtures/live.json\n"
                "HOSTED_MAX_ACTIVE_RUNS=1\nHOSTED_EVENT_ID=predeploy-offline\n"
                "PYTHONPATH=/harness:/app\nPROOFOPS_WORKER_CPUS=6.0\n"
                "PROOFOPS_WORKER_MEMORY=12g\nPROOFOPS_OCR_PROCESSES=2\n"
                "PROOFOPS_PDFIUM_WORKERS=4\n"
            )
            env.flush()
            if capture_misses:
                env.write("PREDEPLOY_CAPTURE_MISSES=1\n")
                env.flush()
            common = [
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--pids-limit",
                "128",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=536870912,mode=1777",
                "--env-file",
                env.name,
                "--mount",
                f"type=volume,src={volume},dst=/data",
                "--mount",
                f"type=bind,src={fixtures.resolve()},dst=/fixtures,readonly",
                "--mount",
                f"type=bind,src={harness},dst=/harness,readonly",
            ]

            def verification():
                if not verification_in_observer:
                    return phase(name, "verify")
                # Inspect large receipt DBs without consuming the API's 512 MiB.
                # Share only its already-isolated loopback namespace; no external network.
                output = docker(
                    "run",
                    "--rm",
                    "--name",
                    name + "-observer",
                    "--network",
                    "container:" + name,
                    "--memory",
                    CAPS["worker_memory"],
                    "--memory-swap",
                    CAPS["worker_memory"],
                    "--cpus",
                    "1",
                    *common[2:],
                    image_id,
                    "python",
                    "/harness/predeploy_runtime.py",
                    "verify",
                    timeout=180,
                )
                return json.loads(output.splitlines()[-1])

            docker(
                "run",
                "-d",
                "--name",
                name,
                "--memory",
                CAPS["api_memory"],
                "--memory-swap",
                CAPS["api_memory"],
                "--cpus",
                CAPS["api_cpus"],
                *common,
                image_id,
            )
            health(name)
            record["intake"] = phase(name, "intake")
            docker(
                "run",
                "-d",
                "--name",
                name + "-worker",
                "--no-healthcheck",
                "--memory",
                CAPS["worker_memory"],
                "--memory-swap",
                CAPS["worker_memory"],
                "--cpus",
                CAPS["worker_cpus"],
                *common,
                image_id,
                "python",
                "scripts/hosted_control.py",
                "worker",
                "--once",
            )
            deadline = time.monotonic() + timeout
            next_keepalive = time.monotonic() + 240
            while True:
                state = json.loads(docker("inspect", name + "-worker"))[0]["State"]
                if not state["Running"]:
                    record["worker_exit_code"] = state["ExitCode"]
                    record["worker_oom"] = state["OOMKilled"]
                    break
                if time.monotonic() >= deadline:
                    record["failures"].append("worker_timeout")
                    docker("stop", "--time", "1", name + "-worker")
                    break
                if keep_session_alive and time.monotonic() >= next_keepalive:
                    phase(name, "keepalive")
                    record["session_keepalives"] = record.get("session_keepalives", 0) + 1
                    next_keepalive = time.monotonic() + 240
                time.sleep(2)
            # GET runs through the API's cold artifact replay and source guards.
            observation = verification()
            (directory / "observation.json").write_text(json.dumps(observation, indent=2))
            comparison = compare_result(observation, case["baseline"])
            comparison["failures"] = record["failures"] + comparison["failures"]
            record.update(comparison)
            if record.get("worker_exit_code") != 0 or record.get("worker_oom"):
                record["failures"].append("worker_failed")
            if observation["status"] == "completed":
                docker("restart", name)
                health(name)
                restart = verification()
                if (
                    restart["result"] != observation["result"]
                    or restart["snapshot_sha256"] != observation["snapshot_sha256"]
                ):
                    record["failures"].append("restart_snapshot_changed")
                record["restart_verified"] = True
            audit_text = docker("exec", name, "cat", "/data/gate-audit.jsonl")
            (directory / "audit.jsonl").write_text(audit_text + "\n")
            events = [json.loads(line) for line in audit_text.splitlines()]
            record["fixture_misses"] = sum(e["event"] == "fixture_miss" for e in events)
            record[response_event + "_count"] = sum(e["event"] == response_event for e in events)
            if response_event == "recorded_reply":
                record["recorded_replies"] = record["recorded_reply_count"]
            if record["fixture_misses"]:
                record["failures"].append("recorded_wire_or_image_gap")
            subprocesses = [e for e in events if e["event"] == "analysis_subprocess"]
            handoffs = [e for e in events if e["event"] == "child_handoff" and e["bytes"] > 0]
            record["subprocess_fd_observed"] = bool(subprocesses)
            record["child_handoff_observed"] = bool(handoffs)
            if not subprocesses or not handoffs:
                record["failures"].append("subprocess_fd_handoff_incomplete")
            record["runtime"] = observation["runtime"]
            record["table_blocks"] = observation["table_blocks"]
            if case["kind"] == "table" and not observation["table_blocks"]:
                record["failures"].append("no_actual_table_graph")
            for container in (name, name + "-worker"):
                info = json.loads(docker("inspect", container))[0]
                if info["RestartCount"]:
                    record["failures"].append("unexpected_container_restart")
                if info["State"]["OOMKilled"]:
                    record["failures"].append("container_oom")
            record["status"] = "failed" if record["failures"] else "passed"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        # No arbitrary exception messages/credentials in the summary.
        record["failures"].append(type(error).__name__)
        record["status"] = "failed"
        if isinstance(error, subprocess.CalledProcessError):
            (directory / "harness-failure.log").write_text(error.output or "")
    finally:
        subprocess.run(["docker", "rm", "-f", name + "-observer"], capture_output=True)
        # Failed/expired runs still need the same call-level diagnostic evidence.
        subprocess.run(
            ["docker", "cp", name + ":/data/gate-audit.jsonl", str(directory / "audit.jsonl")],
            capture_output=True,
        )
        # Preserve the exact unmatched public-report wire for fixture diagnosis.
        # No production credentials are mounted in these isolated containers.
        files = subprocess.run(
            ["docker", "exec", name, "sh", "-c", "ls /data/gate-miss-* 2>/dev/null"],
            capture_output=True,
            text=True,
        )
        for path in files.stdout.splitlines():
            subprocess.run(
                ["docker", "cp", name + ":" + path, str(directory / Path(path).name)],
                capture_output=True,
            )
        for container in (name + "-worker", name):
            inspected = subprocess.run(
                ["docker", "inspect", "--format", "{{json .State}}", container],
                capture_output=True,
                text=True,
            )
            (
                directory
                / ("worker-state.json" if container.endswith("-worker") else "api-state.json")
            ).write_text(inspected.stdout)
            logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True)
            (directory / ("worker.log" if container.endswith("-worker") else "api.log")).write_text(
                logs.stdout + logs.stderr
            )
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
        (directory / "comparison.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--image", help="Exact already built server image/tag/digest")
    mode.add_argument("--captured-result", type=Path, help="Retained API result JSON; no image run")
    parser.add_argument("--case", choices=("lg13", "kakao", "table"))
    parser.add_argument(
        "--captured-seconds", type=float, help="Captured accepted-to-result seconds"
    )
    parser.add_argument(
        "--timeout", type=int, default=1800, help="Per-case worker watchdog seconds"
    )
    parser.add_argument(
        "--capture-misses",
        action="store_true",
        help="Copy unmatched OCR PNGs/parse PDFs for offline fixture recovery",
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    validate_manifest(manifest)
    if args.captured_result:
        if args.case is None or args.captured_seconds is None:
            parser.error("--captured-result requires --case and --captured-seconds")
        case = next(c for c in manifest["cases"] if c["kind"] == args.case)
        result = compare_captured(args.captured_result, case, args.captured_seconds)
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "captured-comparison.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
        return 0 if result["status"] == "passed" else 1
    if args.case is not None or args.captured_seconds is not None:
        parser.error("--case and --captured-seconds are only for --captured-result")
    if not 1 <= args.timeout <= 7200:
        parser.error("--timeout must be 1..7200")
    args.output.mkdir(parents=True, exist_ok=False)
    image_id = docker("image", "inspect", args.image, "--format", "{{.Id}}")
    result = dict(
        schema="predeploy-gate-v1",
        image_id=image_id,
        requested_image=args.image,
        runtime_network="none",
        real_provider_calls=0,
        caps=CAPS,
        cases=[],
        status="failed",
        timing_scope="accepted-to-first-result; offline-provider-I/O",
        mode="strict-offline-gate",
    )
    with tempfile.TemporaryDirectory(prefix="proofops-p5-harness-") as temp:
        harness = Path(temp)
        harness.chmod(0o755)
        for name in ("predeploy_runtime.py", "predeploy_replies.py"):
            shutil.copyfile(ROOT / "scripts" / name, harness / name)
        (harness / "sitecustomize.py").write_text(
            "import sys\nif sys.argv[0] != '-c':\n"
            "    from predeploy_runtime import install\n    install()\n"
        )
        for case in manifest["cases"]:
            print(f'Running {case["kind"]} through {image_id}', flush=True)
            row = run_case(
                case,
                args.manifest.resolve().parent,
                args.output,
                image_id,
                harness,
                args.timeout,
                args.capture_misses,
            )
            result["cases"].append(row)
            print(
                json.dumps(dict(case=case["kind"], status=row["status"], failures=row["failures"])),
                flush=True,
            )
            (args.output / "predeploy-gate.json").write_text(json.dumps(result, indent=2) + "\n")
    result["status"] = (
        "passed" if all(c["status"] == "passed" for c in result["cases"]) else "failed"
    )
    (args.output / "predeploy-gate.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
