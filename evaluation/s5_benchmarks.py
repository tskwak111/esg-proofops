"""Linux 2CPU, identical LG13 retained pipeline; no network or provider spend."""

import argparse
import hashlib
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
    source = root / "outputs/agent-results/R108-redesign/lab/perf/I7/native/lgchem/lgchem"
    files = [p for p in source.rglob("*") if p.is_file()]
    identity = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (out / "fixture-integrity.json").write_text(json.dumps(identity))
    # Other agents own these containers. Observe only; never stop their work.
    while True:
        names = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"], text=True
        ).splitlines()
        other = [name for name in names if name.startswith("proofops-")]
        if not other:
            break
        print(json.dumps(dict(waiting_for_other_benchmarks=other)), flush=True)
        time.sleep(30)
    cases = {}
    for workers, rps in ((8, 4), (8, 6), (12, 6)):
        label = f"replay-{workers}w-{rps}rps-v2"
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
            "--network",
            "none",
            "--no-healthcheck",
            "-v",
            f"{root}:{root}:ro",
            "-v",
            f"{out}:{out}",
        ]
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
            "PYTHONPATH=/app:/app/packages:/app/apps/api/src:/app/apps/worker/src:/app/apps/agent/src",
            "proofops-r108-public:ec1-arm64-874f05f",
            "python",
            "-m",
            "evaluation.pa3_replay",
            "--source",
            str(source),
            "--output",
            str(out / label),
            "--stage",
            "pipeline",
            "--cache-profile",
            "exact-verified-read-v7",
            "--workers",
            str(workers),
            "--scheduler-rps",
            str(rps),
            "--recorded-wait",
            "--no-profile",
        ]
        (out / (label + "-command.json")).write_text(json.dumps(command, indent=2))
        samples = []
        started = time.monotonic()
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
                host = subprocess.run(
                    [
                        "docker",
                        "stats",
                        "--no-stream",
                        "--format",
                        "{{.Name}} {{.CPUPerc}} {{.MemUsage}}",
                    ],
                    capture_output=True,
                    text=True,
                )
                samples.append(
                    dict(seconds=time.monotonic() - started, cgroup=sample.stdout, host=host.stdout)
                )
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
        measurement = json.loads((out / label / "measurement.json").read_text())
        assert measurement["original_checkpoint_identical"]
        cases[label] = {k: v for k, v in measurement.items() if k != "events"}
    assert len({case["result_sha256"] for case in cases.values()}) == 1
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in identity.items())
    (out / "comparison.json").write_text(
        json.dumps(
            dict(
                cases=cases,
                source_files_unchanged=len(identity),
                network="none",
                paid_usd="0",
                limitation="Retained response/latency replay; fresh-provider reliability unproven",
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
