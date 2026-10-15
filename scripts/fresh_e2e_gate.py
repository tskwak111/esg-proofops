"""Offline fresh-run release gate in an exact Linux arm64 server image.

The original PDF enters the real API; worker and analysis subprocesses execute
all stages. Only model transport I/O generates deterministic replies, from each
new request. No saved model responses, production keys or network are available.
This is a wiring/performance gate, not an accuracy or live provider-speed claim.
"""

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from pathlib import Path

from predeploy_gate import docker, run_case

ROOT = Path(__file__).resolve().parents[1]
LG_SHA256 = "c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde"
LG_PAGES = [24, 32, 36, 40, 41, 44, 100, 109, 110, 111, 112, 113, 117]
LG_CLAIM_PAGES = [24, 32, 36, 40, 41, 44, 100, 113]
KAKAO_SHA256 = "43804a2d5eccfc6aa9c5b5480ec6714c7d07bea13ed68729c0af7a3b622ce76d"
KAKAO_STAGES = dict(parse=450.42, extract=549.58, tag=516.49, publish=184.29)


def validate_manifest(manifest):
    cases = manifest.get("cases", [])
    kinds = [c.get("kind") for c in cases]
    if not cases or len(kinds) != len(set(kinds)) or set(kinds) - {"lg13", "kakao"}:
        raise ValueError("FRESH_LG13_CASE_REQUIRED")
    for case in cases:
        if case["kind"] == "kakao":
            validate_kakao(case)
        else:
            validate_lg(case)


def validate_lg(case):
    if (
        case.get("kind") != "lg13"
        or case.get("source_sha256") != LG_SHA256
        or case.get("pages") != LG_PAGES
        or case.get("claim_pages") != LG_CLAIM_PAGES
        or case.get("tenant_id") != "d1b9e025-a759-4d28-8713-cbb5940ec89b"
        or case.get("recorded_states")
    ):
        raise ValueError("FRESH_E14_SCOPE_REQUIRED")
    baseline = case.get("baseline", {})
    if (
        not baseline.get("evidence")
        or type(baseline.get("min_claims")) is not int
        or baseline["min_claims"] < 107
        or baseline.get("stage_seconds")
        != dict(parse=199.32, extract=161.02, tag=228.37, publish=52.55)
        or type(baseline.get("max_stage_ratio")) not in (int, float)
        or not 1 <= baseline["max_stage_ratio"] <= 1.5
        or type(baseline.get("max_seconds")) not in (int, float)
        or not 0 < baseline["max_seconds"] <= 984.6
    ):
        raise ValueError("FRESH_E14_BASELINE_REQUIRED")
    if baseline.get("c3_scope") or case.get("selection_mode") == "automatic":
        raise ValueError("FRESH_E14_SCOPE_REQUIRED")


def validate_kakao(case):
    if (
        case.get("source_sha256") != KAKAO_SHA256
        or case.get("selection_mode") != "automatic"
        or case.get("pages") is not None
        or case.get("claim_pages") is not None
        or case.get("recorded_states")
    ):
        raise ValueError("FRESH_KAKAO_AUTOMATIC_SCOPE_REQUIRED")
    baseline = case.get("baseline", {})
    if (
        not baseline.get("evidence")
        or type(baseline.get("min_claims")) is not int
        or baseline["min_claims"] < 133
        or baseline.get("stage_seconds") != KAKAO_STAGES
        or type(baseline.get("max_stage_ratio")) not in (int, float)
        or not 1 <= baseline["max_stage_ratio"] <= 1.5
        or type(baseline.get("max_seconds")) not in (int, float)
        or not 0 < baseline["max_seconds"] <= 2567.7
        or baseline.get("c3_scope") != "outside_approved_source"
    ):
        raise ValueError("FRESH_KAKAO_BASELINE_REQUIRED")


def prepare(case, base, directory):
    batch_calls = case.get("extract_batch_calls", 100)
    if type(batch_calls) is not int or not 1 <= batch_calls <= 256:
        raise ValueError("FRESH_EXTRACTION_BATCH_INVALID")
    directory.mkdir()
    source = (base / case["pdf"]).resolve()
    if hashlib.sha256(source.read_bytes()).hexdigest() != case["source_sha256"]:
        raise ValueError("FRESH_ORIGINAL_SHA_MISMATCH")
    shutil.copyfile(source, directory / "original.pdf")
    (directory / "case.json").write_text(json.dumps(case))
    for provider in ("openai", "openrouter", "upstage"):
        (directory / f"dummy-{provider}.env").write_text(
            f"{provider.upper()}_API_KEY=offline-test\n"
        )
    config = dict(
        enabled=True,
        openai_key_file="/fixtures/dummy-openai.env",
        openrouter_key_file="/fixtures/dummy-openrouter.env",
        upstage_key_file="/fixtures/dummy-upstage.env",
        llm_provider="openai",
        analysis_profile="finals-unattended-v2",
        llm_max_workers=4,
        llm_requests_per_second=8,
        extract_batch_calls=batch_calls,
        **case["reporting_scope"],
    )
    if case.get("analysis_policy_sha256"):
        config["analysis_policy_sha256"] = case["analysis_policy_sha256"]
    (directory / "live.json").write_text(json.dumps(config))
    return dict(
        source_sha256=case["source_sha256"],
        mode="fresh-generated-model-transport",
        saved_responses=0,
    )


def compare(observation, baseline):
    failures = []
    claims = (observation.get("result") or {}).get("claims", [])
    if observation.get("status") != "completed":
        failures.append("run_not_completed")
    if len(claims) < baseline["min_claims"]:
        failures.append("claim_coverage_regressed")
    verified = sum(c.get("source_quality") == "verified" for c in claims)
    if not verified:
        failures.append("no_positive_source_proof")
    w18 = observation.get("w18", {})
    if w18.get("exact_refs", 0) <= 0 or w18.get("default_unchanged") is not True:
        failures.append("W18_EXACT_COORDINATES_REQUIRED")
    if any(c.get("confirmed_grade") is not None for c in claims):
        failures.append("unknown_simulation_published_confirmation")
    result = observation.get("result") or {}
    if result.get("pipeline", {}).get("status") != "completed" or result.get("hold_reasons"):
        failures.append("pipeline_blocked")
    if baseline.get("c3_scope") == "outside_approved_source":
        if observation.get("c3_generated_calls") != 0 or (
            observation.get("outcome", {}).get("bounded_c3", {}).get("status")
            != "outside_approved_source"
        ):
            failures.append("C3_UNAPPROVED_SOURCE_DISPATCH")
        selection = observation.get("selection", {})
        proposal = selection.get("proposal", {})
        if (
            selection.get("automatic") is not True
            or selection.get("pages") != proposal.get("selected_evidence_pages")
            or selection.get("claim_pages") != proposal.get("selected_claim_pages")
            or 51 not in selection.get("claim_pages", [])
        ):
            failures.append("KAKAO_AUTOMATIC_SELECTION_REQUIRED")
    elif observation.get("c3_generated_calls") != 3:
        failures.append("C3_FRESH_THREE_CALLS_REQUIRED")
    if (observation.get("outcome", {}).get("bounded_c3") or {}).get("published"):
        failures.append("unknown_simulation_c3_confirmation")
    errors = observation.get("errors", {})
    reasons = observation.get("hold_distribution", {})
    for name in ("REPLICA_HEADER_UNRESOLVED", "TAG_INPUT_INVALID", "TAGGING_INPUT_COUNT_INVALID"):
        if errors.get(name, 0) + reasons.get(name, 0):
            failures.append(name)
    if observation.get("inventory_completed", 0) <= 0:
        failures.append("SC1_INVENTORY_EMPTY")
    if observation.get("inventory_completed", 0) != observation.get("inventory_planned", 0):
        failures.append("SC1_INVENTORY_INCOMPLETE")
    measured = observation.get("outcome", {}).get("stage_seconds", {})
    ratios = {}
    for stage, seconds in baseline["stage_seconds"].items():
        actual = measured.get(stage)
        if type(actual) not in (int, float) or not math.isfinite(actual) or actual < 0:
            failures.append("stage_missing:" + stage)
        else:
            ratios[stage] = actual / seconds
            if ratios[stage] > baseline["max_stage_ratio"]:
                failures.append("stage_regression:" + stage)
    seconds = observation.get("seconds")
    if (
        type(seconds) not in (int, float)
        or not math.isfinite(seconds)
        or seconds < 0
        or seconds > baseline["max_seconds"]
    ):
        failures.append("total_time_regression")
    if observation.get("unsettled_costs"):
        failures.append("unsettled_reservations")
    if observation.get("clock_discontinuity_seconds", 0) > 5:
        failures.append("environment_clock_discontinuity")
    return dict(
        status="failed" if failures else "passed",
        failures=failures,
        claims=len(claims),
        verified=verified,
        c3_generated_calls=observation.get("c3_generated_calls"),
        selection=observation.get("selection"),
        w18=observation.get("w18"),
        bounded_c3=observation.get("outcome", {}).get("bounded_c3"),
        hold_distribution=reasons,
        errors=errors,
        inventory_completed=observation.get("inventory_completed"),
        inventory_planned=observation.get("inventory_planned"),
        stage_seconds=measured,
        stage_ratios_to_E14=ratios,
        seconds=seconds,
        clock_discontinuity_seconds=observation.get("clock_discontinuity_seconds"),
        baseline=baseline,
        semantic_accuracy="not_evaluated",
        live_provider_speed="not_evaluated",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--timing", action="store_true", help="Observe per-function durations")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    validate_manifest(manifest)
    if not 1 <= args.timeout <= 7200:
        parser.error("--timeout must be 1..7200")
    info = json.loads(docker("image", "inspect", args.image))[0]
    if (info["Os"], info["Architecture"]) != ("linux", "arm64"):
        raise ValueError("LINUX_ARM64_IMAGE_REQUIRED")
    args.output.mkdir(parents=True, exist_ok=False)
    generator = ROOT / "scripts" / "fresh_e2e_runtime.py"
    shutil.copyfile(generator, args.output / "fresh_e2e_runtime.py")
    if args.timing:
        shutil.copyfile(ROOT / "scripts/fresh_e2e_timing.py", args.output / "fresh_e2e_timing.py")
    records = []
    with tempfile.TemporaryDirectory(prefix="fxh-harness-") as temp:
        harness = Path(temp)
        harness.chmod(0o755)
        for source, target in (
            ("predeploy_runtime.py", "predeploy_runtime_base.py"),
            ("predeploy_replies.py", "predeploy_replies.py"),
            ("fresh_e2e_runtime.py", "fresh_e2e_runtime.py"),
        ):
            shutil.copyfile(ROOT / "scripts" / source, harness / target)
        (harness / "sitecustomize.py").write_text(
            "import os,traceback\ntry:\n"
            + (
                " from fresh_e2e_timing import install as timing\n timing()\n"
                if args.timing
                else ""
            )
            + " from fresh_e2e_runtime import install\n install()\n"
            + "except BaseException:\n traceback.print_exc()\n os._exit(70)\n"
        )
        if args.timing:
            shutil.copyfile(ROOT / "scripts/fresh_e2e_timing.py", harness / "fresh_e2e_timing.py")
        (harness / "predeploy_runtime.py").write_text(
            "import json,sys\nfrom fresh_e2e_runtime import intake,verify\n"
            "from predeploy_runtime_base import DATA,request\n"
            "def keepalive():\n"
            " record=json.loads((DATA/'gate-session.json').read_text())\n"
            " status,_=request(record['run']['status_url'],auth=record['auth'])\n"
            " return {'status':status['status']}\n"
            "print(json.dumps({'intake':intake,'verify':verify,'keepalive':keepalive}"
            "[sys.argv[1]]()))\n"
        )
        for case in manifest["cases"]:
            baseline = case["baseline"]
            if not baseline.get("evidence") or baseline.get("min_claims", 0) <= 0:
                raise ValueError("FRESH_BASELINE_REQUIRED")
            record = run_case(
                case,
                args.manifest.parent,
                args.output,
                info["Id"],
                harness,
                args.timeout,
                prepare_case=prepare,
                compare_result=compare,
                response_event="generated_reply",
                verification_in_observer=True,
                keep_session_alive=True,
            )
            record["simulated"] = True
            if args.timing:
                from fresh_e2e_timing import summarize

                audit_path = args.output / case["kind"] / "audit.jsonl"
                if audit_path.exists():
                    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
                    (audit_path.parent / "function-timing.json").write_text(
                        json.dumps(summarize(events), indent=2) + "\n"
                    )
            records.append(record)
    report = dict(
        schema="fxh-fresh-e2e-v1",
        transport_generator_sha256=hashlib.sha256(generator.read_bytes()).hexdigest(),
        runtime_network="none",
        real_provider_calls=0,
        image_id=info["Id"],
        platform="linux/arm64",
        status="passed" if all(r["status"] == "passed" for r in records) else "failed",
        cases=records,
    )
    if args.timing:
        report["timing_observer_sha256"] = hashlib.sha256(
            (args.output / "fresh_e2e_timing.py").read_bytes()
        ).hexdigest()
    (args.output / "fresh-e2e-gate.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
