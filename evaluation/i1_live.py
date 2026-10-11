"""Four-page fresh-model canary on disposable copies of attested source states.

Reuse the proven HX1 evaluation harness. No imported run is published. One
shared USD .50 guard covers both companies; first provider error stops all
subsequent paid dispatch. Parsing/OCR responses are retained, not purchased.
"""

import argparse
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from proofops.adapters.local import openai, spend_guard
from proofops.adapters.local.provider_concurrency import ProviderConcurrency
from proofops.adapters.local.upstage_parse import PARSE_MODEL_PINNED, UpstageParseProbe
from proofops.adapters.parsing import opendataloader, upstage_document
from proofops.application.analysis_profile import V2_POLICY, apply_pilot_profile
from proofops.application.ingest.graph_fusion import ParserProfile
from proofops.application.registry import Registry
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor
from proofops_worker import composition

from evaluation.local_upstage_pilot import live_tagging_settings
from evaluation.w7_sentence_replay import NoTransport


def main(
    *, claim_pages=None, workers=1, budget="0.5", event_id="I1-USD0.5", integration_policy=None
):
    selected_policy = integration_policy or V2_POLICY
    if not Decimal(0) < Decimal(budget) <= Decimal("0.6"):
        raise ValueError("CANARY_BUDGET_INVALID")
    physical_pages = claim_pages or dict(naver=[84, 88], kia=[26, 106])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--company", choices=("naver", "kia"))
    parser.add_argument("--spend-ledger", type=Path)
    parser.add_argument("--seed-response-root", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    spend_ledger = args.spend_ledger or args.output / "spend.sqlite3"
    spec = importlib.util.spec_from_file_location("i1_hx1_harness", args.harness)
    assert spec and spec.loader
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    original_pin = harness.pin_scratch_policy
    original_batch = opendataloader._batch

    def pin(output, tenant, run):
        if args.seed_response_root:
            seeded = args.seed_response_root / company
            for name in ("model-responses.sqlite3", "model-responses.origins"):
                path = seeded / name
                if path.is_dir():
                    shutil.copytree(path, output / name)
                elif path.is_file():
                    shutil.copy2(path, output / name)
        settings_path = output / "settings.json"
        settings = json.loads(settings_path.read_text())
        from argparse import Namespace

        options = Namespace(
            analysis_profile="finals-unattended-v2",
            analysis_policy_sha256=canonical_hash(selected_policy),
        )
        apply_pilot_profile(options)
        for flag in (
            "j3",
            "j7",
            "j8",
            "i3_wire",
            "i4_identity",
            "k1",
            "k3",
            "sentence_prefix",
            "table_footnotes",
        ):
            name = "extraction_" + flag
            if getattr(options, name):
                settings[name] = True
            else:
                settings.pop(name, None)
        source_policy = None
        if options.claim_source_profile == "upstage-ocr-page-v11":
            from proofops.adapters.local import upstage_ocr_profile_v11

            source_policy = upstage_ocr_profile_v11.claim_source_policy()
            settings["claim_source_policy"] = source_policy
        settings.update(
            extraction_w9=True,
            extraction_sentence_prefix=True,
            extraction_table_footnotes=True,
            analysis_policy_sha256=canonical_hash(selected_policy),
        )
        flags = {
            k: v for k, v in settings.items() if k.startswith("extraction_") and type(v) is bool
        }
        flags.update(
            position_order="position_context_order" in settings,
            display_text_profile=settings.get("display_text_policy", {}).get("profile"),
        )
        extraction_profile = asdict(
            UpstageClaimExtractor(NoTransport(), output / "profile-only", **flags).profile
        )
        settings["extraction_profile"] = extraction_profile
        guidance = live_tagging_settings(
            600,
            prompt_profile=selected_policy.get("tagging_prompt_profile"),
            model_id="gpt-6-luna",
            element_definition_profile=selected_policy["element_definition_profile"],
            relations=True,
            relation_profile="occurrence-v3",
            preliminary_context=True,
            preliminary_table_context=True,
            preliminary_table_role=True,
            preliminary_goal_role=True,
            preliminary_actor_role=True,
            preliminary_pb1=True,
            compact_element_wire=True,
            capacity_refresh=True,
        )
        settings.update(guidance)
        settings_path.write_text(json.dumps(settings))
        parser_path = output / "parser.json"
        config = json.loads(parser_path.read_text())
        config.update(table_claims_profile="pb1-w9-v1")
        parser_path.write_text(json.dumps(config))
        with sqlite3.connect(output / "state.sqlite3") as db:
            triggers = list(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
            for name, _ in triggers:
                assert name.replace("_", "").isalnum()
                db.execute(f"DROP TRIGGER {name}")
            frozen = json.loads(
                db.execute("SELECT payload FROM run_snapshots WHERE run_id=?", (run,)).fetchone()[0]
            )
            frozen.update(
                extraction_profile=extraction_profile,
                extraction_profile_hash=canonical_hash(extraction_profile),
                parser_profile=config,
                parser_profile_hash=ParserProfile(
                    frozen["document"]["version_id"], **config
                ).config_hash(),
                **guidance,
            )
            if source_policy:
                frozen["claim_source_policy"] = source_policy
            for prefix in ("tagging", "preliminary", "relation"):
                frozen[prefix + "_settings_hash"] = canonical_hash(frozen[prefix + "_settings"])
                frozen[prefix + "_runtime"]["runtime_binding_id"] = frozen[prefix + "_settings"][
                    "binding"
                ]["binding_id"]
                frozen[prefix + "_runtime"]["tagging_settings_sha256"] = frozen[
                    prefix + "_settings_hash"
                ]
                frozen[prefix + "_runtime_artifact_hash"] = canonical_hash(
                    frozen[prefix + "_runtime"]
                )
            frozen["input_reservation_policy_hash"] = canonical_hash(
                frozen["input_reservation_policy"]
            )
            page_map = json.loads(
                (
                    args.root
                    / "outputs/agent-results/R108-redesign/lab/perf/PA9"
                    / (company + "-server")
                    / "result-1.json"
                ).read_text()
            )["page_map"]
            frozen["extraction_limits"]["claim_pages"] = [
                page_map.index(page) + 1 for page in physical_pages[company]
            ]
            db.execute(
                "UPDATE run_snapshots SET payload=? WHERE run_id=?", (json.dumps(frozen), run)
            )
            for _, sql in triggers:
                db.execute(sql)
        registry = Registry.sqlite(output / "state.sqlite3")
        try:
            for prefix in ("tagging", "preliminary", "relation"):
                runtime = frozen[prefix + "_runtime"]
                registry.with_option(
                    tenant,
                    "runtime",
                    runtime["runtime_binding_id"],
                    "I1 authorized local canary " + prefix,
                    status="approved",
                    version="1",
                    artifact=runtime,
                    sha256=canonical_hash(runtime),
                    approved_by=runtime["approved_by"],
                    approved_at=runtime["approved_at"],
                    local_synthetic=False,
                )
        finally:
            registry.close()
        from proofops.application import analysis_profile

        prior_default = analysis_profile.V2_POLICY
        try:
            analysis_profile.V2_POLICY = selected_policy
            frozen = original_pin(output, tenant, run)
        finally:
            analysis_profile.V2_POLICY = prior_default
        from proofops.adapters.local.tag_store import tagging_settings

        tagging_settings(frozen)
        tagging_settings(frozen, preliminary=True)
        tagging_settings(frozen, relation=True)
        return frozen

    harness.pin_scratch_policy = pin
    original_build = composition.build_composition
    admission = ProviderConcurrency(workers)
    original_candidate_batch = upstage_document.candidate_batch

    def candidate_batch(*a, **kw):
        state = (
            args.root / "outputs/agent-results/R108-redesign/lab/perf/PA9" / (company + "-server")
        )
        batches = json.loads(next((state / "parser-prepared").rglob("candidates.json")).read_text())
        identifier = next(
            b["parser_run_id"] for b in batches if b["parser_name"] == "upstage_async_" + kw["mode"]
        )
        previous = upstage_document.uuid4
        upstage_document.uuid4 = lambda: UUID(identifier)
        try:
            return original_candidate_batch(*a, **kw)
        finally:
            upstage_document.uuid4 = previous

    upstage_document.candidate_batch = candidate_batch

    def build(**kwargs):
        os.environ["PROOFOPS_VERIFIED_READ_CACHE"] = "exact-verified-read-v5"
        factories = kwargs["provider_factories"]
        llm = factories["llm"]

        def parse(ledger):
            state = (
                args.root
                / "outputs/agent-results/R108-redesign/lab/perf/PA9"
                / (company + "-server")
            )
            receipts = {}
            with sqlite3.connect((state / "upstage.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
                for (raw,) in db.execute(
                    "SELECT receipt FROM probe_calls WHERE receipt IS NOT NULL"
                ):
                    value = json.loads(raw)
                    if "duration_seconds" in value:
                        receipts[value["mode"]] = value
            responses = {}
            for path in (state / "parse-responses").glob("*-async.json"):
                values = json.loads(path.read_text())
                mode = next(m for m in ("standard", "enhanced") if m in values[0]["usage"])
                responses[mode] = values

            class RetainedParse(UpstageParseProbe):
                def parse_async(self, pdf_bytes, *, request_id, mode="standard"):
                    receipt = receipts[mode]
                    expected = canonical_hash(
                        dict(
                            model=PARSE_MODEL_PINNED,
                            mode=mode,
                            pdf_sha256=sha256(pdf_bytes).hexdigest(),
                            pages=receipt["pages"],
                            bytes_len=len(pdf_bytes),
                            transport="async",
                        )
                    )
                    assert expected == receipt["request_sha256"], "I1_RETAINED_PARSE_INPUT_CHANGED"
                    assert canonical_hash(responses[mode]) == receipt["response_sha256"]
                    return receipt | dict(raw_batches=responses[mode])

            return RetainedParse("offline-fixture", ledger)

        kwargs["provider_factories"] = dict(
            llm=lambda *a, **kw: admission.bind(llm(*a, **kw)), parse=parse
        )
        return original_build(**kwargs)

    composition.build_composition = build
    OriginalGuard = spend_guard.SpendGuard

    class SharedGuard(OriginalGuard):
        def __init__(self, path, **kwargs):
            super().__init__(
                path, **(kwargs | dict(event_id=event_id, daily_limit=budget, event_limit=budget))
            )

        def configure_run(self, run_id, **kwargs):
            kwargs["run_limit"] = str(min(Decimal(kwargs.get("run_limit", "1")), Decimal(budget)))
            return super().configure_run(run_id, **kwargs)

    spend_guard.SpendGuard = SharedGuard
    original_post = openai.OpenAIProbe._post
    stopped = []
    dispatches = []

    def post(probe, body, **kwargs):
        if stopped:
            raise ValueError("I1_PROVIDER_STOPPED_NO_RETRY")
        dispatches.append(dict(company=company, request_id=body.get("request_id")))
        try:
            return original_post(probe, body, **kwargs)
        except ValueError as error:
            code = str(error)
            if code.startswith("OPENAI_HTTP_"):
                stopped.append(dict(company=company, code=code))
            raise

    openai.OpenAIProbe._post = post
    results = {}
    lab = args.root / "outputs/agent-results/R108-redesign/lab"
    for company in (args.company,) if args.company else ("naver", "kia"):
        if stopped:
            results[company] = dict(status="not_run", reason="provider_error_no_paid_retry")
            continue
        sys.argv = [
            "i1-live",
            "--source",
            str(lab / f"perf/PA9/{company}-server"),
            "--output",
            str(args.output / company),
            "--spend-ledger",
            str(spend_ledger),
            "--key-file",
            str(args.key_file),
            "--workers",
            str(workers),
        ]
        try:
            opendataloader._batch = original_batch
            harness.main()
            results[company] = dict(status="completed")
        except Exception as error:
            # Only codes/types are recorded; exception bodies can contain data.
            results[company] = dict(status="not_run", exception_type=type(error).__name__)
            measurement = args.output / company / "measurement.json"
            if measurement.exists():
                results[company]["measurement"] = json.loads(measurement.read_text())
            results["kia"] = dict(status="not_run", reason="earlier_local_stage_failure")
            break
        measurement = args.output / company / "measurement.json"
        if measurement.exists():
            results[company]["measurement"] = json.loads(measurement.read_text())
        if stopped:
            results[company]["status"] = "not_run"
    guard = OriginalGuard(spend_ledger, event_id=event_id, daily_limit=budget, event_limit=budget)
    result = dict(
        policy_sha256=canonical_hash(selected_policy),
        results=results,
        provider_errors=stopped,
        dispatches=len(dispatches),
        spend=guard.summary(),
        paid_retry_after_provider_error=0,
        physical_claim_pages=physical_pages,
        admission=admission.snapshot(),
        budget_usd=budget,
        parser="retained responses; source gates rerun; fresh extraction/tagging only",
        production_revisions_written=0,
    )
    (args.output / "measurement.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    main()
