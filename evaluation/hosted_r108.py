"""Private subprocess: existing R108 pipeline with explicit hosted provider factories."""

import json
import os
import sys
import time
from contextlib import nullcontext
from pathlib import Path

from proofops.adapters.local.upstage import UpstageProbe
from proofops_api.hosted_analysis import (
    HostedLunaProbe,
    HostedOpenAILunaProbe,
    HostedParseProbe,
    operator_profiles,
    read_key,
    read_operator_config,
)
from proofops_api.hosted_store import HostedSettings, HostedStore
from proofops_worker.composition import build_composition


def prepare_argv(pdf, state, tenant, config, options=None):
    from pypdf import PdfReader

    pages = ",".join(str(p) for p in range(1, len(PdfReader(pdf).pages) + 1))
    profiles = operator_profiles(config)
    argv = [
        "hosted-r108",
        "--pdf",
        str(pdf),
        "--state",
        str(state),
        "--tenant-id",
        tenant,
        "--pages",
        pages,
        "--report-year",
        str(config["report_year"]),
        "--period-start",
        config["period_start"],
        "--period-end",
        config["period_end"],
        "--parser",
        "upstage",
        "--llm-provider",
        profiles["llm_provider"],
        "--vision-parse",
        "off",
        "--max-calls",
        "20",
        "--extraction-total-calls",
        "100",
        "--tagging-max-calls",
        "600",
        "--relation-profile",
        "occurrence-v3",
        "--claim-source-profile",
        profiles["claim_source"],
        "--verify-paragraphs",
        "--verify-merged-tables",
        "--repair-table-headers",
        "--verify-claim-spans",
        "--extraction-context",
        "--extraction-table-context",
        "--extraction-source-ids",
        "--extraction-assertion-prompt",
        "--live-tagging",
        "--live-relations",
        "--preliminary-context",
        "--preliminary-table-context",
        "--preliminary-table-role",
        "--capacity-policy-refresh",
        "--compact-element-wire",
        "--position-context-order",
        "--claim-span-render-resolution",
        "--claim-span-bullet-spacing",
        "--claim-span-typography",
        "--ai-project-review",
        "--display-text-profile",
        "glyph-joined-display-v1",
    ]
    options = options or {}
    if options.get("pipeline_profile") == "unattended-v1":
        argv += ["--pipeline-profile", "unattended-v1"]
    if options.get("claim_pages"):
        physical = [int(p) for p in pages.split(",")]
        # Prepared PDF is a subset: map original physical pages to its own 1-based pages.
        page_map = options["pages"]
        claim_pages = [
            i
            for i, original in zip(physical, page_map, strict=True)
            if original in options["claim_pages"]
        ]
        argv += ["--claim-pages", ",".join(str(p) for p in claim_pages)]
    if profiles["analysis_profile"] in ("r108-finals-candidate", "r108-finals-candidate-v2"):
        v2 = profiles["analysis_profile"] == "r108-finals-candidate-v2"
        argv[argv.index("--vision-parse") + 1] = "auto"
        argv.remove("--position-context-order")
        if profiles["claim_source"] == "glyph-alignment-v1":
            argv.append("--r108-finals-candidate-v2" if v2 else "--r108-finals-candidate")
        else:
            # The frozen I1 macro pins Apple. Keep it unchanged; reuse its exact
            # feature flags with the independently approved Linux source policy.
            from evaluation.local_upstage_pilot import (
                FINALS_CANDIDATE_FLAGS,
                FINALS_CANDIDATE_V2_FLAGS,
            )

            flags = FINALS_CANDIDATE_V2_FLAGS if v2 else FINALS_CANDIDATE_FLAGS
            for name in flags:
                flag = "--" + name.replace("_", "-")
                if name == "capacity_refresh":
                    flag = "--capacity-policy-refresh"
                if flag not in argv:
                    argv.append(flag)
    return argv


def drive(store, job, workspace, config, *, llm_post=None, parse_post=None, ocr_post=None):
    from evaluation import local_upstage_pilot as pilot

    state = workspace / "state"
    old_argv = sys.argv
    sys.argv = prepare_argv(
        workspace / "selected.pdf", state, job["tenant_id"], config, store.run_options(job)
    )
    try:
        if pilot.main() != 0:
            raise ValueError("HOSTED_PREPARATION_FAILED")
    finally:
        sys.argv = old_argv
    manifest = json.loads((state / "pilot.json").read_text())
    # Keys stay inside the private process; fake transports use explicit dummy keys.
    profiles = operator_profiles(config)
    llm_provider = profiles["llm_provider"]
    llm_key_path, llm_key_name, llm_probe = (
        ("openai_key_file", "OPENAI_API_KEY", HostedOpenAILunaProbe)
        if llm_provider == "openai"
        else ("openrouter_key_file", "OPENROUTER_API_KEY", HostedLunaProbe)
    )
    luna_key = "fake-test" if llm_post else read_key(config[llm_key_path], llm_key_name)
    parse_key = (
        "fake-test" if parse_post else read_key(config["upstage_key_file"], "UPSTAGE_API_KEY")
    )
    upstage_ledger, luna_ledger = state / "upstage.sqlite3", state / "luna.sqlite3"
    UpstageProbe(parse_key, upstage_ledger)  # local receipts only; hosted broker grants money
    scope = nullcontext()
    if profiles["source_reader"].startswith("upstage-ocr-page-"):
        from proofops_api.hosted_ocr import HostedOCRStore, reader_scope

        os.environ["UPSTAGE_API_KEY"] = parse_key
        scope = reader_scope(
            HostedOCRStore(
                upstage_ledger,
                state / "ocr-spend.json",
                store=store,
                job=job,
                local_run_id=manifest["run_id"],
                post=ocr_post,
            )
        )
    factories = {
        "parse": lambda ledger: HostedParseProbe(
            parse_key, ledger, store=store, job=job, post=parse_post
        ),
        "llm": lambda key, ledger, **kw: llm_probe(
            luna_key, ledger, store=store, job=job, post=llm_post, **kw
        ),
    }
    os.environ["LOCAL_LLM_MAX_WORKERS"] = str(profiles["llm_max_workers"])
    observed = []
    stage_seconds = {}
    with scope:
        for stage, progress in (("parse", 15), ("extract", 45), ("tag", 75)):
            started = time.monotonic()
            store.update_progress(job, stage, progress)
            worker = build_composition(
                stage=stage,
                verify_paragraphs=stage == "parse",
                provider_factories=factories,
                provider_ledgers=(upstage_ledger, luna_ledger),
            )
            try:
                outcome = worker.run_once(tenant_id=job["tenant_id"], run_id=manifest["run_id"])
                observed.append(dict(stage=stage, outcome=outcome))
                if stage == "extract" and outcome == "committed":
                    from proofops_worker.extract_batch import run_batches

                    batches = run_batches(
                        worker, tenant_id=job["tenant_id"], run_id=manifest["run_id"], batches=100
                    )
                    if batches and batches[-1].get("stop_code"):
                        observed.append(dict(stage=stage, outcome=batches[-1]["stop_code"]))
                        break
                if outcome not in {"committed", "completed", "partial"}:
                    break
            finally:
                stage_seconds[stage] = round(time.monotonic() - started, 6)
                worker.uploads.close()
                worker.uploads.registry.close()
    # Preserve genuine partial work and reasons. Only completed tag publication
    # may be called completed; domain decisions still carry their own hold states.
    complete = bool(observed and observed[-1] == dict(stage="tag", outcome="completed"))
    result = dict(
        status="completed" if complete else "partial_blocked",
        stages=observed,
        stage_seconds=stage_seconds,
        reason=None if complete else "R108_" + observed[-1]["outcome"].upper(),
        profiles=operator_profiles(config),
        scope=store.run_options(job),
        pipeline_profile=store.run_options(job).get("pipeline_profile", "strict-v1"),
        reporting_scope={k: config[k] for k in ("report_year", "period_start", "period_end")},
    )
    (state / "outcome.json").write_text(json.dumps(result))
    return state, result


def main():
    settings = HostedSettings.from_env(os.environ)
    store = HostedStore(settings)
    run, fence, workspace = sys.argv[1:]
    with store.transaction() as db:
        job = dict(db.execute("SELECT * FROM runs WHERE run_id=?", (run,)).fetchone())
        if job["fence"] != int(fence):
            raise ValueError("LEASE_LOST")
        store._fenced(db, job, time.time())
    drive(store, job, Path(workspace), read_operator_config(settings.live_config))


if __name__ == "__main__":
    main()
