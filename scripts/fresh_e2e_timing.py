"""Optional offline-gate timing; observes calls without changing product results.

Inclusive durations overlap across threads and nesting: never sum them as stage
wall time. No arguments, source text, credentials or provider responses are logged.
"""

import functools
import importlib
import importlib.util
import inspect
import json
import re
import sys
import threading
import time
from collections import Counter
from pathlib import Path


def observe_parser_child(owner, parser_path):
    from predeploy_runtime_base import audit

    execute = owner._execute
    parser_path = Path(parser_path).resolve()

    def child(command, work, env, profile):
        # _execute also isolates unrelated helpers, including the W18 glyph
        # reader. Only replace the actual parser entrypoint.
        if not (
            len(command) == 4 and command[1] == "-I" and Path(command[2]).resolve() == parser_path
        ):
            return execute(command, work, env, profile)
        entry = Path(__file__).with_name("fresh_parser_timing.py")
        try:
            return execute([*command[:-2], str(entry), str(work)], work, env, profile)
        finally:
            path = work / "spp-timing.json"
            if path.exists():
                for record in json.loads(path.read_bytes()):
                    audit("function_timing", **record)
                path.unlink()

    owner._execute = staticmethod(child)


def observe(owner, name, *, label=None):
    from predeploy_runtime_base import audit

    original = getattr(owner, name)
    label = label or f"{original.__module__}.{original.__qualname__}"

    @functools.wraps(original)
    def timed(*args, **kwargs):
        started = time.monotonic()
        failed = True
        identity = {}
        if label == "proofops.adapters.local.openai.OpenAIProbe.complete":
            probe = args[0]
            role, replica = probe._response_context.get() or (probe.response_role, 0)
            identity = dict(request_id=kwargs.get("request_id"), role=role, replica=replica)
        try:
            value = original(*args, **kwargs)
            failed = False
            return value
        finally:
            audit(
                "function_timing",
                function=label,
                started=started,
                seconds=time.monotonic() - started,
                thread=threading.get_ident(),
                failed=failed,
                **identity,
            )

    descriptor = inspect.getattr_static(owner, name)
    setattr(owner, name, staticmethod(timed) if isinstance(descriptor, staticmethod) else timed)


def install():
    from predeploy_runtime_base import audit

    previous_hook = sys.excepthook

    def exception(kind, value, trace):
        code = str(value)
        audit(
            "process_exception",
            exception_type=kind.__name__,
            code=code if re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", code) else None,
        )
        previous_hook(kind, value, trace)

    sys.excepthook = exception
    targets = {
        "evaluation.hosted_scope_plan": ["inspect_streaming"],
        "proofops_api.hosted_store": ["HostedStore.upload", "HostedStore.upload_file"],
        "proofops.adapters.parsing.opendataloader": [
            "OpenDataLoaderParser.parse",
            "OpenDataLoaderParser.load_verified",
            "OpenDataLoaderParser._execute",
            "_table_verifier",
            "_batch",
            "fuse_candidates",
            "verify_quarantined_pdf",
        ],
        "proofops.adapters.parsing.h6_local_pages_v2": ["execute", "subset"],
        "proofops.adapters.parsing.hx6_upstage": ["recover", "native_pages"],
        "proofops.adapters.parsing.upstage_document": ["candidate_batch"],
        "proofops.adapters.local.upstage_parse": ["UpstageParseProbe.parse_async"],
        "proofops.adapters.local.upstage_ocr_page": ["PageOCRStore.fetch", "render_page"],
        "proofops.adapters.local.upstage_ocr_profile_d2_v21": [
            "Reader.attest_native_sources",
            "Reader.attest_tables",
            "Reader.replay_native_sources",
        ],
        "proofops.adapters.local.s3_table_replay": ["attest", "replay"],
        "proofops.adapters.local.i21_table_replay": ["attest", "replay"],
        "proofops.adapters.local.evidence_source_verification_v1": ["attest_evidence_sources"],
        "proofops.adapters.local.job_store": ["LocalSQLiteJobStore.commit_job"],
        "proofops_worker.local_runner": ["LocalParserRunner.run_once"],
        "proofops.adapters.local.openai": ["OpenAIProbe.complete"],
        "proofops_api.hosted_analysis": ["HostedOpenAILunaProbe._post"],
        "proofops.adapters.local.provider_scheduler": ["RoleProviderConcurrency.pace_transport"],
        "proofops.adapters.local.claim_store": ["LocalClaimStore.load_evidence"],
        "proofops.adapters.local.tag_store": ["LocalTagStore.load_inputs"],
        "proofops.adapters.local.verified_read_cache": ["replay_cached"],
        "proofops.adapters.local.claim_source_policies": ["attest_claims"],
        "proofops.adapters.local.fxh_claim_source": [
            "Reader.attest_claim_spans",
            "Reader.recompute_claim_receipt",
            "_ScopedFXERaster.read",
        ],
        "proofops.adapters.local.run_artifacts": ["load_run_graph"],
        "proofops.adapters.local.sc1_inventory_store": ["SC1InventoryProvider.__call__"],
        "proofops.application.tagging.element_inventory": ["plan_inventory", "replay_inventory"],
        "proofops_worker.tag_runner": ["LocalTagRunner._execute"],
        "proofops_worker.live_tagging": [
            "LiveTaggingRuntime.preliminary",
            "LiveTaggingRuntime.relations",
            "LiveTaggingRuntime.display_packet",
            "LiveTaggingRuntime.invoke",
            "LiveTaggingRuntime._source_replicas",
        ],
        "proofops_worker.sc1_inventory": ["load_inventory"],
        "proofops_api.hosted_publication": ["make_handoff", "_authoritative_state"],
        "fresh_e2e_runtime": ["generate_llm", "generate_parse", "generate_ocr"],
    }
    if importlib.util.find_spec("proofops.adapters.local.s4_claim_source") is not None:
        targets["proofops.adapters.local.s4_claim_source"] = ["_ScopedFXERaster.read"]
    if importlib.util.find_spec("proofops.adapters.parsing.spp_execution") is not None:
        targets["proofops.adapters.parsing.spp_execution"] = ["table_verifier"]
    for module_name, names in targets.items():
        module = importlib.import_module(module_name)
        for dotted in names:
            owner = module
            parts = dotted.split(".")
            for part in parts[:-1]:
                owner = getattr(owner, part)
            observe(owner, parts[-1], label=f"{module_name}.{dotted}")

    # The product's -I child intentionally excludes sitecustomize. Use a private
    # harness entrypoint invoking that exact child, then remove only its timing
    # sidecar before the parent hashes artifacts. Production code is untouched.
    from proofops.adapters.parsing import opendataloader

    observe_parser_child(opendataloader.OpenDataLoaderParser, opendataloader.__file__)


def summarize(events):
    functions = {}
    for event in events:
        if event.get("event") != "function_timing":
            continue
        value = functions.setdefault(
            event["function"],
            dict(calls=0, failures=0, inclusive_seconds=0.0, max_seconds=0.0, intervals=[]),
        )
        value["calls"] += 1
        value["failures"] += int(event["failed"])
        value["inclusive_seconds"] += event["seconds"]
        value["max_seconds"] = max(value["max_seconds"], event["seconds"])
        value["intervals"].append((event["started"], event["started"] + event["seconds"]))
    for value in functions.values():
        intervals = sorted(value.pop("intervals"))
        edges = [(start, 1) for start, _ in intervals] + [(end, -1) for _, end in intervals]
        active = peak = 0
        for _, delta in sorted(edges):
            active += delta
            peak = max(peak, active)
        covered = 0.0
        end = 0.0
        for start, stop in intervals:
            covered += max(0, stop - max(start, end))
            end = max(end, stop)
        value.update(wall_union_seconds=covered, peak_concurrent=peak)
    return dict(
        schema="s4-fresh-function-timing-v1",
        functions=functions,
        generated_calls=dict(
            Counter(
                e.get("role", e.get("provider", "unknown"))
                for e in events
                if e.get("event") == "generated_reply"
            )
        ),
    )
