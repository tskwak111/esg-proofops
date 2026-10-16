"""Build the public image and run a separate API/worker offline pipeline smoke.

Usage: uv run python scripts/hosted_pipeline_smoke.py --output /tmp/hx2-smoke
All runtime containers have --network none. No key files or host data are mounted.
"""

import argparse
import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, timeout=120):
    return subprocess.check_output(
        ["docker", *args], text=True, stderr=subprocess.STDOUT, timeout=timeout, cwd=ROOT
    ).strip()


def phase(container, name):
    output = run("exec", container, "python", "-m", "deploy.public.offline_smoke", name)
    return json.loads(output.splitlines()[-1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="proofops-public:hx2-offline")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--worker-cpus", default="6")
    parser.add_argument("--worker-memory", default="12g")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = dict(status="failed", real_provider_calls=0, runtime_network="none")
    name = "proofops-hx2-" + secrets.token_hex(5)
    volume = name + "-data"
    try:
        if not args.skip_build:
            with (args.output / "build.log").open("w") as log:
                subprocess.run(
                    ["docker", "build", "-f", "deploy/public/Dockerfile", "-t", args.image, "."],
                    cwd=ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=900,
                    check=True,
                )
        run("volume", "create", volume)
        with tempfile.NamedTemporaryFile("w", prefix="hx2-offline-", suffix=".env") as env:
            os.chmod(env.name, 0o600)
            env.write(
                "APP_ORIGIN=https://app.example.com\nHOSTED_SESSION_SECRET="
                + secrets.token_urlsafe(48)
                + "\nHOSTED_ACCEPT_UPLOADS=true\nHOSTED_CONSENT_VERSION=hx2-offline-test\n"
                "R108_ACCEPT_NEW_RUNS=true\nANALYSIS_BACKEND=r108\nLIVE_DISABLED=true\n"
                "RC1_RESULT_REUSE_ENABLED=true\nHOSTED_LIVE_CONFIG=/data/offline-operator.json\n"
            )
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
                "256",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=1g",
                "--env-file",
                env.name,
                "--mount",
                f"type=volume,src={volume},dst=/data",
            ]
            run("run", "-d", "--name", name, "--memory", "1g", "--cpus", "1", *common, args.image)
            deadline = time.monotonic() + 60
            while True:
                try:
                    run(
                        "exec",
                        name,
                        "python",
                        "-c",
                        "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/v1/health/live',timeout=2)",
                        timeout=5,
                    )
                    break
                except subprocess.SubprocessError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("API health unavailable") from None
                    time.sleep(0.2)
            result["intake"] = phase(name, "intake")
            output = run(
                "run",
                "--rm",
                "--name",
                name + "-worker",
                "--memory",
                args.worker_memory,
                "--cpus",
                args.worker_cpus,
                *common,
                args.image,
                "python",
                "-m",
                "deploy.public.offline_smoke",
                "worker",
                timeout=240,
            )
            result["worker"] = json.loads(output.splitlines()[-1])
            result["verification"] = phase(name, "verify")
            result["reuse_verification"] = phase(name, "reuse")
            run("restart", name)
            # Restart waits for process start; phase retries only loopback connection failures.
            for attempt in range(20):
                try:
                    result["restart_verification"] = phase(name, "verify")
                    break
                except subprocess.CalledProcessError:
                    if attempt == 19:
                        raise
                    time.sleep(0.2)
            result["image_id"] = run("image", "inspect", args.image, "--format", "{{.Id}}")
            result["status"] = "passed"
    except subprocess.CalledProcessError as error:
        (args.output / "failure.log").write_text(error.output or "command failed")
        raise
    finally:
        (args.output / "pipeline-smoke.json").write_text(json.dumps(result, indent=2) + "\n")
        for container in (name + "-worker", name):
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        subprocess.run(["docker", "volume", "rm", volume], capture_output=True)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
