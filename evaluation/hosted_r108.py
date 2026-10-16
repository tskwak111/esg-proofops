"""Private subprocess: existing R108 pipeline with explicit hosted provider factories."""

import json
import os
import sys
import threading
import time
from contextlib import nullcontext
from pathlib import Path

from proofops.adapters.local.upstage import UpstageProbe
from proofops.application.pipeline_failures import PUBLIC_CODES
from proofops.application.ports.jobs import JobMessage
from proofops_api.hosted_analysis import (
    FINALS_PROFILES,
    HostedLunaProbe,
    HostedOpenAILunaProbe,
    HostedParseProbe,
    operator_profiles,
    read_key,
    read_operator_config,
)
from proofops_api.hosted_store import HostedSettings, HostedStore
from proofops_worker.composition import build_composition


def stage_failure_code(jobs, messages):
    """Read durable job codes, never expose exception messages or source text."""
    for message in messages:
        code = jobs.get_job(message).get("error_code")
        if code in PUBLIC_CODES:
            return code
    return None


def pinned_reporting_scope(config, options):
    from evaluation.reporting_period import FIELDS, validate_period

    if "reporting_scope" in options:
        validate_period(options["reporting_scope"])
        return options["reporting_scope"]
    return {k: config[k] for k in FIELDS}  # Frozen pre-FX7 runs.


def prepare_argv(pdf, state, tenant, config, options=None):
    from pypdf import PdfReader

    pages = ",".join(str(p) for p in range(1, len(PdfReader(pdf).pages) + 1))
    options = options or {}
    period = pinned_reporting_scope(config, options)
    if options.get("pipeline_profile") in ("unattended-v1", "strict-v1"):
        config = dict(analysis_profile="r108-default") | config
    selected = options.get("analysis_profile") or (
        options.get("pipeline_profile")
        if options.get("pipeline_profile") in FINALS_PROFILES
        else None
    )
    config = config | (dict(analysis_profile=selected) if selected else {})
    if options.get("analysis_profile_sha256"):
        config["analysis_policy_sha256"] = options["analysis_profile_sha256"]
        from proofops.application.analysis_profile import publication_policy_for

        pinned = publication_policy_for(
            config.get("analysis_profile", "finals-unattended-v2"),
            pinned_hash=options["analysis_profile_sha256"],
        )
        if not pinned.get("provider_scheduler"):
            config = {k: v for k, v in config.items() if k != "llm_requests_per_second"}
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
        str(period["report_year"]),
        "--period-start",
        period["period_start"],
        "--period-end",
        period["period_end"],
        "--parser",
        "upstage",
        "--llm-provider",
        profiles["llm_provider"],
        "--vision-parse",
        "off",
        "--max-calls",
        str(profiles["extract_batch_calls"]),
        "--extraction-total-calls",
        "2000",
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
    if profiles["analysis_profile"] in FINALS_PROFILES:
        if "--claim-pages" not in argv:
            argv += ["--claim-pages", pages]
        # Pilot pins parser, EV1, source, prompt and policy hashes. It prepares
        # only; hosted dispatch below remains the sole money authority.
        argv += ["--analysis-profile", profiles["analysis_profile"]]
        from proofops.application.analysis_profile import publication_policy_for

        selected_policy = publication_policy_for(
            profiles["analysis_profile"], pinned_hash=options.get("analysis_profile_sha256")
        )
        if selected_policy.get("tagging_budget"):
            argv[argv.index("--tagging-max-calls") + 1] = str(
                selected_policy["tagging_budget"]["max_calls"]
            )
        if options.get("analysis_profile_sha256"):
            from proofops.application.analysis_profile import (
                CF1_3OF3_POLICY,
                CF1_POLICY,
                CF4_SOURCE_POLICY,
                CF5_POLICY,
                CF6_POLICY,
                CF6_V2_POLICY,
                FINALS_C24_POLICY,
                FINALS_D2_POLICY,
                FINALS_E05_POLICY,
                FINALS_FXB_POLICY,
                FINALS_FXC_POLICY,
                FINALS_HX6_COMPLETE_POLICY,
                FINALS_HX6_POLICY,
                FINALS_HX6_RESILIENT_POLICY,
                FINALS_I3_POLICY,
                FINALS_I7_POLICY,
                FINALS_I8_POLICY,
                FINALS_I13_POLICY,
                FINALS_I16_POLICY,
                FINALS_I19_POLICY,
                FINALS_I20_INITIAL_POLICY,
                FINALS_I20_POLICY,
                FINALS_I21_POLICY,
                FINALS_I22_POLICY,
                FINALS_I23_POLICY,
                FINALS_I24_POLICY,
                FINALS_I25_POLICY,
                FINALS_I26_POLICY,
                FINALS_I27_POLICY,
                FINALS_I27_PRE_RB2_POLICY,
                FINALS_I28_POLICY,
                FINALS_I29_INITIAL_POLICY,
                FINALS_I29_POLICY,
                FINALS_Q1_POLICY,
                FINALS_RG1_POLICY,
                FINALS_S2_SPEED_POLICY,
                FINALS_S5_POLICY,
                FXH_POLICY,
                OPS2_POLICY,
                RB1_POLICY,
                RB2_POLICY,
                RB3_POLICY,
                RB4_POLICY,
                RB4_STREAM_POLICY,
                S1_POLICY,
                S2_POLICY,
                S4_POLICY,
                S5_LIVE_POLICY,
                W3_POLICY,
                policy_for,
            )
            from proofops.domain.provenance import canonical_hash

            policy_for(profiles["analysis_profile"], pinned_hash=options["analysis_profile_sha256"])
            if options["analysis_profile_sha256"] not in {
                canonical_hash(policy_for(profiles["analysis_profile"])),
                canonical_hash(CF5_POLICY),
                canonical_hash(FINALS_E05_POLICY),
                canonical_hash(FINALS_D2_POLICY),
                canonical_hash(FINALS_FXB_POLICY),
                canonical_hash(FINALS_FXC_POLICY),
                canonical_hash(FINALS_HX6_POLICY),
                canonical_hash(FINALS_HX6_COMPLETE_POLICY),
                canonical_hash(FINALS_HX6_RESILIENT_POLICY),
                canonical_hash(CF4_SOURCE_POLICY),
                canonical_hash(FINALS_C24_POLICY),
                canonical_hash(FINALS_Q1_POLICY),
                canonical_hash(W3_POLICY),
                canonical_hash(FINALS_I3_POLICY),
                canonical_hash(FINALS_I7_POLICY),
                canonical_hash(FINALS_I8_POLICY),
                canonical_hash(FINALS_I13_POLICY),
                canonical_hash(FINALS_I16_POLICY),
                canonical_hash(FINALS_I19_POLICY),
                canonical_hash(FINALS_I20_INITIAL_POLICY),
                canonical_hash(FINALS_I20_POLICY),
                canonical_hash(FINALS_I21_POLICY),
                canonical_hash(FINALS_I22_POLICY),
                canonical_hash(FINALS_I23_POLICY),
                canonical_hash(FINALS_I24_POLICY),
                canonical_hash(FINALS_I25_POLICY),
                canonical_hash(FINALS_I26_POLICY),
                canonical_hash(FINALS_I27_POLICY),
                canonical_hash(FINALS_I27_PRE_RB2_POLICY),
                canonical_hash(FINALS_I28_POLICY),
                canonical_hash(FINALS_I29_INITIAL_POLICY),
                canonical_hash(FINALS_I29_POLICY),
                canonical_hash(CF1_3OF3_POLICY),
                canonical_hash(CF1_POLICY),
                canonical_hash(OPS2_POLICY),
                canonical_hash(FXH_POLICY),
                canonical_hash(RB3_POLICY),
                canonical_hash(RB1_POLICY),
                canonical_hash(RB2_POLICY),
                canonical_hash(RB4_POLICY),
                canonical_hash(RB4_STREAM_POLICY),
                canonical_hash(FINALS_RG1_POLICY),
                canonical_hash(S1_POLICY),
                canonical_hash(S2_POLICY),
                canonical_hash(S4_POLICY),
                canonical_hash(S5_LIVE_POLICY),
                canonical_hash(FINALS_S5_POLICY),
                canonical_hash(FINALS_S2_SPEED_POLICY),
                canonical_hash(CF6_POLICY),
                canonical_hash(CF6_V2_POLICY),
            }:
                raise ValueError("HOSTED_PROFILE_PIN_MISMATCH")
            argv += ["--analysis-policy-sha256", options["analysis_profile_sha256"]]
            if options["analysis_profile_sha256"] == canonical_hash(S2_POLICY):
                argv[argv.index("--tagging-max-calls") + 1] = str(
                    S2_POLICY["tagging_budget"]["max_calls"]
                )
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
    options = store.run_options(job)
    if options.get("analysis_profile_sha256"):
        config = config | dict(analysis_policy_sha256=options["analysis_profile_sha256"])
    if options.get("analysis_profile"):
        config = config | dict(analysis_profile=options["analysis_profile"])
    else:
        # Stored pre-HS3 runs must keep their original operator composition.
        config = dict(analysis_profile="r108-default") | config
    if "provider_execution" in options:
        from proofops.domain.provenance import canonical_hash

        if canonical_hash(options["provider_execution"]) != options["provider_execution_sha256"]:
            raise ValueError("PROVIDER_EXECUTION_PIN_MISMATCH")
        config = config | options["provider_execution"]
    from proofops.application.analysis_profile import publication_policy_for

    selected = (
        publication_policy_for(
            config["analysis_profile"], pinned_hash=config.get("analysis_policy_sha256")
        )
        if (config["analysis_profile"] in FINALS_PROFILES)
        else {}
    )
    resource_runtime = None
    from proofops.application.rb3_deadline import from_parent

    deadline = from_parent(selected)
    if selected.get("provider_scheduler") and "provider_execution" not in options:
        raise ValueError("PROVIDER_EXECUTION_PIN_REQUIRED")
    if not selected.get("provider_scheduler"):
        config = {k: v for k, v in config.items() if k != "llm_requests_per_second"}
    if selected.get("worker_resources"):
        from proofops.adapters.local.worker_resources import apply_resources

        resource_runtime = apply_resources()
    else:
        os.environ.pop("PROOFOPS_RESOURCE_PROFILE", None)
    old_argv = sys.argv
    sys.argv = prepare_argv(workspace / "selected.pdf", state, job["tenant_id"], config, options)
    try:
        if pilot.main() != 0:
            raise ValueError("HOSTED_PREPARATION_FAILED")
    finally:
        sys.argv = old_argv
    manifest = json.loads((state / "pilot.json").read_text())
    if resource_runtime is not None:
        from proofops.domain.provenance import canonical_hash

        # Private create-only runtime evidence; not an imported source approval.
        with (state / "worker-runtime.json").open("x") as stream:
            json.dump(
                dict(
                    resources=resource_runtime,
                    provider_execution=options.get("provider_execution"),
                    policy_sha256=canonical_hash(selected),
                ),
                stream,
            )
            stream.flush()
            os.fsync(stream.fileno())
        (state / "worker-runtime.json").chmod(0o400)
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
    hosted_ocr_store = None
    if profiles["source_reader"].startswith("upstage-ocr-page-"):
        from proofops_api.hosted_ocr import HostedOCRStore, reader_scope

        os.environ["UPSTAGE_API_KEY"] = parse_key
        hosted_ocr_store = HostedOCRStore(
            upstage_ledger,
            state / "ocr-spend.json",
            store=store,
            job=job,
            local_run_id=manifest["run_id"],
            post=ocr_post,
        )
        scope = reader_scope(hosted_ocr_store)
    factories = {
        "parse": lambda ledger: HostedParseProbe(
            parse_key,
            ledger,
            store=store,
            job=job,
            post=parse_post,
            integrated=profiles["analysis_profile"] in FINALS_PROFILES,
        ),
        "llm": lambda key, ledger, **kw: llm_probe(
            luna_key, ledger, store=store, job=job, post=llm_post, **kw
        ),
    }
    os.environ["LOCAL_LLM_MAX_WORKERS"] = str(profiles["llm_max_workers"])
    from proofops.application.analysis_profile import policy_for

    execution = (
        policy_for(profiles["analysis_profile"], pinned_hash=options.get("analysis_profile_sha256"))
        if profiles["analysis_profile"] in FINALS_PROFILES
        else {}
    )
    cache = execution.get("verified_read_cache", {})
    os.environ["PROOFOPS_VERIFIED_READ_CACHE"] = cache.get("profile", "disabled")
    if profiles["analysis_profile"] in FINALS_PROFILES:
        if resource_runtime is None:
            os.environ["PROOFOPS_DISPLAY_PREFETCH_WORKERS"] = "4"
    observed = []
    stage_seconds = {}
    extraction_stop = None
    processed_claims = set()
    progress_lock = threading.Lock()

    def claim_progress(claim_id, total):
        with progress_lock:
            processed_claims.add(claim_id)
            store.update_progress(
                job, "tag", 75, claims_extracted=total, claims_processed=len(processed_claims)
            )

    if execution.get("model_response_policy"):
        # Document payload ownership makes authorized purge remove cached model
        # content and its immutable origin receipts together. Never share tenants.
        def scoped_llm(key, ledger, **kw):
            probe = llm_probe(luna_key, ledger, store=store, job=job, post=llm_post, **kw)
            probe.response_cache_path = (
                store.document_dir(job["tenant_id"], job["document_id"]) / "model-responses.sqlite3"
            )
            return probe

        factories["llm"] = scoped_llm

    c3_factory = factories["llm"]
    ops2_state = None
    if execution.get("ops2_provider_fallback"):
        from proofops_api.hosted_ops2 import FallbackState, OPS2Probe

        ops2_state = FallbackState()

        def ops2_llm(key, ledger, **kw):
            probe = OPS2Probe(
                luna_key,
                ledger,
                store=store,
                job=job,
                post=llm_post,
                fallback_state=ops2_state,
                fallback_key=lambda: read_key(config["openrouter_key_file"], "OPENROUTER_API_KEY"),
                **kw,
            )
            probe.response_cache_path = (
                store.document_dir(job["tenant_id"], job["document_id"]) / "model-responses.sqlite3"
            )
            return probe

        factories["llm"] = ops2_llm

    from proofops.adapters.local.i27_inventory_execution import Failures

    inventory_failures = Failures() if execution.get("i27_sc1_optional_transient") else None
    provider_gate = None
    if execution.get("execution_profile") in ("w3-speed-v1", "s2-server-v1"):
        from proofops.adapters.local.provider_concurrency import ProviderConcurrency

        gate_type = ProviderConcurrency
        gate_options = {}
        if execution.get("provider_scheduler"):
            from proofops.adapters.local.provider_scheduler import RoleProviderConcurrency

            gate_type = RoleProviderConcurrency
            gate_options["requests_per_second"] = profiles["llm_requests_per_second"]
            gate_options["scheduler_policy"] = execution["provider_scheduler"]
        provider_gate = gate_type(
            profiles["llm_max_workers"],
            **gate_options,
            max_cooldown_seconds=execution["http_max_cooldown_seconds"],
            resilience_directory=(
                store.document_dir(job["tenant_id"], job["document_id"])
                / "provider-resilience"
                / job["run_id"]
                if execution.get("provider_resilience")
                else None
            ),
        )
        original_llm = factories["llm"]
        original_c3_llm = c3_factory
        original_parse = factories["parse"]

        def bounded_llm(*a, **k):
            probe = provider_gate.bind(original_llm(*a, **k))
            if inventory_failures is not None:
                probe.i27_inventory_failures = inventory_failures
            return probe

        def bounded_c3_llm(*a, **k):
            return provider_gate.bind(original_c3_llm(*a, **k))

        c3_factory = bounded_c3_llm

        def bounded_parse(*a, **k):
            probe = original_parse(*a, **k)
            probe.download_workers = execution["parse_download_workers"]
            return probe

        factories["llm"] = bounded_llm
        factories["parse"] = bounded_parse

    with scope:
        for stage, progress in (("parse", 15), ("extract", 45), ("tag", 75)):
            started = time.monotonic()
            store.update_progress(job, stage, progress)
            worker = build_composition(
                stage=stage,
                verify_paragraphs=stage == "parse",
                provider_factories=factories,
                provider_ledgers=(upstage_ledger, luna_ledger),
                claim_progress=claim_progress,
            )
            if deadline is not None:
                worker.rb3_deadline = deadline
            try:
                stage_messages = [
                    JobMessage(**event["message"])
                    for event in worker.store.jobs.pending_outbox(
                        job["tenant_id"], manifest["run_id"], now=int(time.time())
                    )
                    if event["message"]["stage"] == stage
                ]
                outcome = worker.run_once(tenant_id=job["tenant_id"], run_id=manifest["run_id"])
                failure = stage_failure_code(worker.store.jobs, stage_messages)
                if failure:
                    extraction_stop = failure
                    if failure == "BUDGET_EXHAUSTED" and outcome == "failed":
                        outcome = "budget_unanalyzed"
                observed.append(dict(stage=stage, outcome=outcome))
                if stage == "extract" and outcome == "committed":
                    from proofops_worker.extract_batch import run_batches

                    def extract_progress(_summary=None):
                        coverage = worker.store.jobs.get_run(job["tenant_id"], manifest["run_id"])[
                            "coverage"
                        ]
                        store.update_progress(
                            job, "extract", 45, claims_extracted=coverage["claims_discovered"]
                        )

                    extract_progress()
                    batches = run_batches(
                        worker,
                        tenant_id=job["tenant_id"],
                        run_id=manifest["run_id"],
                        batches=100,
                        on_batch=extract_progress,
                    )
                    if batches and batches[-1].get("stop_code"):
                        extraction_stop = batches[-1]["stop_code"]
                        observed.append(dict(stage=stage, outcome=extraction_stop))
                        # Publish genuine extracted claims through tagging even if
                        # extraction stopped. Every paid tag still uses the broker.
                if outcome not in {"committed", "completed", "partial"}:
                    break
            finally:
                stage_seconds[stage] = round(time.monotonic() - started, 6)
                worker.uploads.close()
                worker.uploads.registry.close()
    # Preserve genuine partial work and reasons. Only completed tag publication
    # may be called completed; domain decisions still carry their own hold states.
    if deadline is not None and deadline.summary()["stopped_stages"] and not extraction_stop:
        extraction_stop = "TIME_BUDGET"
    complete = bool(
        not extraction_stop and observed and observed[-1] == dict(stage="tag", outcome="completed")
    )
    result = dict(
        status="completed" if complete else "partial_blocked",
        stages=observed,
        stage_seconds=stage_seconds,
        reason=None
        if complete
        else (
            extraction_stop
            if extraction_stop
            else "BUDGET_EXHAUSTED"
            if observed[-1]["outcome"] in {"budget_unanalyzed", "BUDGET_EXHAUSTED"}
            else "R108_" + observed[-1]["outcome"].upper()
        ),
        profiles=operator_profiles(config),
        scope=store.run_options(job),
        pipeline_profile=store.run_options(job).get("pipeline_profile", "strict-v1"),
        reporting_scope=pinned_reporting_scope(config, options),
        pipeline_failure_projection="specific-pipeline-reasons-h4-v1",
    )
    if deadline is not None:
        result["rb3_deadline"] = deadline.summary()
    if provider_gate is not None:
        result["provider_concurrency"] = provider_gate.snapshot()
        admission = result["provider_concurrency"]
        if execution.get("provider_resilience"):
            failed = admission["failed_calls"]
            deferred = admission["circuit_deferred"]
            result["provider_failures"] = dict(
                failed_calls=failed, deferred_calls=deferred, total=failed + deferred
            )
            recovered = 0
            if ops2_state is not None:
                recovered = min(failed, ops2_state.summary()["recovered_primary_failures"])
                result["provider_failures"].update(
                    recovered_by_fallback=recovered,
                    unresolved_total=failed - recovered + deferred,
                )
            optional = 0
            if inventory_failures is not None:
                result["i27_sc1_failures"] = inventory_failures.summary()
                optional = result["i27_sc1_failures"]["optional_failed_calls"]
                result["provider_failures"].update(
                    optional_inventory_failures=optional,
                    unresolved_total=max(0, failed - recovered - optional) + deferred,
                )
            if failed > recovered + optional or deferred:
                result.update(status="partial_blocked", reason="PROVIDER_PROCESSING_FAILED")
    if complete and execution.get("direct_certification_policy", {}).get("profile") == (
        "management-direct-certification-c3-v2"
    ):
        from proofops.application.fxh_policy import enabled as fxh_enabled

        from evaluation.hosted_c3 import publish_current

        try:
            with (
                (
                    reader_scope(hosted_ocr_store)
                    if fxh_enabled(execution) and hosted_ocr_store is not None
                    else nullcontext()
                ),
                (
                    hosted_ocr_store.original_page_scope()
                    if fxh_enabled(execution) and hosted_ocr_store is not None
                    else nullcontext()
                ),
            ):
                result["bounded_c3"] = publish_current(
                    store, job, state, execution, c3_factory, simulated=llm_post is not None
                )
        except (ValueError, OSError, KeyError, RuntimeError) as error:
            # Keep completed regular claims; a failed bounded candidate never
            # creates confirmation authority or turns missing evidence absent.
            result["bounded_c3"] = dict(status="current_source_or_tags_unresolved", published=False)
            if fxh_enabled(execution):
                import re

                code = str(error)
                result["bounded_c3"]["fxh_error_code"] = (
                    code if re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", code) else type(error).__name__
                )
    if ops2_state is not None:
        result["ops2_provider_fallback"] = ops2_state.summary()
    (state / "outcome.json").write_text(json.dumps(result))
    return state, result


def main():
    settings = HostedSettings.from_env(os.environ)
    store = HostedStore(settings)
    run, fence, workspace = sys.argv[1:4]
    with store.transaction() as db:
        job = dict(db.execute("SELECT * FROM runs WHERE run_id=?", (run,)).fetchone())
        if job["fence"] != int(fence):
            raise ValueError("LEASE_LOST")
        store._fenced(db, job, time.time())
    state, _ = drive(store, job, Path(workspace), read_operator_config(settings.live_config))
    if len(sys.argv) == 5:
        from proofops_api.hosted_publication import make_handoff

        packet = make_handoff(state, job, json.loads(job["pages"]))
        if packet is not None:
            with os.fdopen(os.dup(int(sys.argv[4])), "wb") as publication:
                publication.write(packet)


if __name__ == "__main__":
    main()
