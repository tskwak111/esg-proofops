"""Sequential resource proof and USD0.4 live trials after deterministic comparison."""

import argparse
import json
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.root.resolve(), args.output.resolve()
    work = Path(__file__).resolve().parents[1]
    while not (out / "comparison.json").is_file():
        print("Waiting for deterministic LG comparison", flush=True)
        time.sleep(30)
    for label, module_args, network in (
        (
            "resources",
            [
                "evaluation.s5_resource_probe",
                "--source",
                str(root / "outputs/agent-results/R108-redesign/lab/perf/I7/native/lgchem/lgchem"),
                "--output",
                str(out / "resources"),
            ],
            False,
        ),
        (
            "live-8w-4rps",
            [
                "evaluation.s5_live",
                "--root",
                str(root),
                "--output",
                str(out),
                "--workers",
                "8",
                "--rps",
                "4",
            ],
            True,
        ),
        (
            "live-12w-6rps",
            [
                "evaluation.s5_live",
                "--root",
                str(root),
                "--output",
                str(out),
                "--workers",
                "12",
                "--rps",
                "6",
            ],
            True,
        ),
    ):
        name = "proofops-s5-" + label
        command = [
            "docker",
            "run",
            "--name",
            name,
            "--platform",
            "linux/arm64",
            "--user",
            "0:0",
            "--cpus",
            "2",
            "--memory",
            "4g",
            "--memory-swap",
            "4g",
            "--no-healthcheck",
            "-v",
            f"{root}:{root}:ro",
            "-v",
            f"{out}:{out}",
        ]
        if network:
            shared = root / "outputs/agent-results/R108-redesign/lab/sprint3/E2E"
            command += ["-v", f"{shared}:{shared}"]
        else:
            command += ["--network", "none"]
        for part in (
            "packages",
            "apps/api",
            "apps/worker",
            "apps/agent",
            "evaluation",
            "config",
            "contracts",
            "prompts",
            "scripts",
        ):
            command += ["-v", f"{work / part}:/app/{part}:ro"]
        command += [
            "-e",
            "APP_ENV=local",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PROOFOPS_WORKER_CPUS=2",
            "-e",
            "PROOFOPS_WORKER_MEMORY=4g",
            "-e",
            "PYTHONPATH=/app:/app/packages:/app/apps/api/src:/app/apps/worker/src:/app/apps/agent/src",
            "proofops-r108-public:ec1-arm64-874f05f",
            "python",
            "-m",
            *module_args,
        ]
        (out / (label + "-command.json")).write_text(json.dumps(command, indent=2))
        started = time.monotonic()
        samples = []
        with (out / (label + ".log")).open("w") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            while process.poll() is None:
                sample = subprocess.run(
                    [
                        "docker",
                        "exec",
                        name,
                        "cat",
                        "/sys/fs/cgroup/cpu.stat",
                        "/sys/fs/cgroup/memory.peak",
                        "/sys/fs/cgroup/memory.events",
                    ],
                    capture_output=True,
                    text=True,
                )
                samples.append(dict(seconds=time.monotonic() - started, cgroup=sample.stdout))
                time.sleep(5)
        inspected = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
        status = dict(
            exit_code=process.returncode,
            container_seconds=time.monotonic() - started,
            state=inspected["State"],
            resources={k: inspected["HostConfig"][k] for k in ("NanoCpus", "Memory", "MemorySwap")},
        )
        (out / (label + "-resources.json")).write_text(json.dumps(samples))
        (out / (label + "-exit.json")).write_text(json.dumps(status, indent=2))
        print(json.dumps(dict(case=label, **status)), flush=True)
        if process.returncode:
            raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
