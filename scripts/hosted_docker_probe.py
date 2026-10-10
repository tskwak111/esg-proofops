"""Build/run a bounded local Docker smoke; no key inheritance or cloud access."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path


def run(*args: str, timeout: int = 120) -> str:
    return subprocess.check_output(
        ["docker", *args], text=True, stderr=subprocess.STDOUT, timeout=timeout
    ).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="proofops-r108-public:p1")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    name = "r108-p1-" + secrets.token_hex(5)
    volume = name + "-data"
    image = args.image
    result: dict = {
        "image": image,
        "network": "none",
        "memory_limit_bytes": 3 * 1024**3,
        "target_host_bytes": 4 * 1024**3,
        "paid_calls": 0,
        "cloud_calls": 0,
    }
    run("volume", "create", volume)

    def health():
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                body = run(
                    "exec",
                    name,
                    "python",
                    "-c",
                    "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/v1/health/live',timeout=2).read().decode())",
                    timeout=5,
                )
                if json.loads(body)["status"] == "ok":
                    return
            except (subprocess.SubprocessError, ValueError):
                time.sleep(0.1)
        raise RuntimeError("liveness unavailable")

    try:
        with tempfile.NamedTemporaryFile("w", prefix="r108-p1-", suffix=".env") as env:
            os.chmod(env.name, 0o600)
            env.write(
                "APP_ORIGIN=https://app.example.com\nHOSTED_SESSION_SECRET="
                + secrets.token_urlsafe(48)
                + "\nHOSTED_ACCEPT_UPLOADS=true\n"
                "HOSTED_CONSENT_VERSION=approved-original-7d-local-test\n"
                "R108_ACCEPT_NEW_RUNS=true\nANALYSIS_BACKEND=r108\nLIVE_DISABLED=true\n"
            )
            env.flush()
            started = time.monotonic()
            run(
                "run",
                "-d",
                "--name",
                name,
                "--network",
                "none",
                "--read-only",
                "--memory",
                "3g",
                "--memory-swap",
                "3g",
                "--cpus",
                "2",
                "--pids-limit",
                "128",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,size=512m",
                "--mount",
                f"type=volume,src={volume},dst=/data",
                "--env-file",
                env.name,
                image,
            )
            health()
            result["startup_seconds"] = round(time.monotonic() - started, 3)
            result["smoke"] = json.loads(run("exec", name, "python", "deploy/public/smoke.py"))
            restart_started = time.monotonic()
            run("restart", name)
            health()
            result["restart_seconds"] = round(time.monotonic() - restart_started, 3)
            check = """import json,urllib.request,pathlib
p=pathlib.Path('/data/smoke-session.json'); state=json.loads(p.read_text())
r=urllib.request.Request('http://127.0.0.1:8000/v1/session',headers={'Cookie':state['cookie']})
with urllib.request.urlopen(r) as response:
 body=json.load(response)
 assert body['csrf_token']==state['csrf']
 assert body['tenant_id']==state['tenant']
p.unlink(); print('session+csrf survived Uvicorn restart')
"""
            result["restart_session"] = run("exec", name, "python", "-c", check)
            result["image_size_bytes"] = int(
                run("image", "inspect", image, "--format", "{{.Size}}")
            )
            result["image_id"] = run("image", "inspect", image, "--format", "{{.Id}}")
            result["architecture"] = run(
                "image", "inspect", image, "--format", "{{.Os}}/{{.Architecture}}"
            )
            result["container_state"] = json.loads(
                run("inspect", name, "--format", "{{json .State}}")
            )
            result["stats"] = json.loads(
                run("stats", "--no-stream", name, "--format", "{{json .}}")
            )
            result["status"] = "passed"
    except BaseException:
        result["status"] = "failed"
        try:
            (args.output / "docker-runtime.log").write_text(run("logs", name))
        except subprocess.SubprocessError:
            pass
        raise
    finally:
        (args.output / "runtime-results.json").write_text(json.dumps(result, indent=2) + "\n")
        run("rm", "-f", name)
        run("volume", "rm", volume)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
